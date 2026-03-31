# Plan: SlotPilot – Multi-Calendar Agent

## Overview
A Streamlit app with a **Microsoft Semantic Kernel** (`ChatCompletionAgent`) backed by **Azure OpenAI**. It authenticates against multiple Outlook 365 accounts via **MSAL browser login (PKCE)**, queries Microsoft Graph for calendar availability across timezones, and can book personal appointments. Token state and conversation thread are persisted in `st.session_state`. Runs locally.

---

## Project Structure

```
SlotPilot-MultiCalendarAgent/
├── app.py                    # Streamlit entrypoint (st.navigation)
├── pages/
│   ├── chat.py               # Chat page — agent conversation
│   └── accounts.py           # Account management page
├── agent/
│   ├── __init__.py
│   ├── calendar_plugin.py    # CalendarPlugin class with @kernel_function methods
│   ├── agent_builder.py      # ChatCompletionAgent factory
│   └── prompts.py            # System prompt string
├── auth/
│   ├── __init__.py
│   └── msal_helper.py        # MSAL PublicClientApplication + token cache helpers
├── graph/
│   ├── __init__.py
│   └── client.py             # Microsoft Graph API wrapper
├── observability/
│   ├── __init__.py
│   ├── logger.py             # Structured JSON logger (Python logging + RotatingFileHandler)
│   └── audit.py              # Audit log writer — immutable append-only JSONL file
├── logs/                     # Runtime output (gitignored)
│   ├── app.log               # Rotating application log
│   └── audit.jsonl           # Append-only audit trail
├── .env                      # Azure OpenAI + App Registration credentials
├── requirements.txt
└── README.md
```

---

## Phase 1 — Foundation

**Step 1: `requirements.txt`**
- `streamlit>=1.35`
- `msal>=1.28`
- `semantic-kernel>=1.20.0`
- `requests>=2.31`
- `python-dotenv>=1.0`
- `pytz>=2024`
- `nest_asyncio>=1.6`

> `semantic-kernel` includes Azure OpenAI support via its bundled `openai` dependency — no separate Azure SDK package needed. Requires Python 3.10+.

Add `logs/` to `.gitignore` to prevent log files (which may contain PII such as email addresses) from being committed.

**Step 2: `.env` template**
```
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_DEPLOYMENT=
AZURE_OPENAI_API_VERSION=2024-02-01
MSAL_CLIENT_ID=
MSAL_TENANT_ID=common
MSAL_REDIRECT_URI=http://localhost
LOG_LEVEL=INFO
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=5
```

**Step 3: `README.md`**
- Azure App Registration setup instructions
- Required Graph delegated permissions: `Calendars.ReadWrite`, `User.Read`
- Run instructions: `pip install -r requirements.txt && streamlit run app.py`

---

## Phase 2 — Auth Layer (`auth/msal_helper.py`)

- `build_public_client_app(token_cache_str)` — builds `PublicClientApplication` with a `SerializableTokenCache`; deserializes cache string if provided
- `get_token_for_account(app, account, scopes)` — silent token fetch via `acquire_token_silent`; returns token string or `None`
- `interactive_login(app, scopes)` — browser PKCE login via `acquire_token_interactive(scopes, prompt=SELECT_ACCOUNT)`
- `serialize_cache(cache)` — returns serialized string for `st.session_state`
- Constant: `GRAPH_SCOPES = ["Calendars.ReadWrite", "User.Read", "offline_access"]`

---

## Phase 3 — Microsoft Graph Client (`graph/client.py`)

All functions accept `access_token: str` as first param. Base URL: `https://graph.microsoft.com/v1.0`.

| Function | Endpoint | Notes |
|---|---|---|
| `list_calendars(token)` | `GET /me/calendars` | Returns `{id, name, canEdit}` list |
| `list_events(token, calendar_id, start, end, timezone)` | `GET /me/calendars/{id}/calendarView` | Uses `Prefer: outlook.timezone` header; expands recurring events |
| `get_free_busy(token, email, start, end, timezone, interval_min=30)` | `POST /me/calendar/getSchedule` | Work/school accounts only; returns `availabilityView` + `scheduleItems` |
| `create_event(token, calendar_id, subject, start, end, timezone, body, location)` | `POST /me/calendars/{id}/events` | Personal appointment only (no attendees) |

All functions log at `DEBUG` level (request method + URL, response status code, latency ms) using the app logger. `create_event` additionally writes an **audit record** via `audit.py` on success.

---

## Phase 4 — Semantic Kernel Plugin (`agent/calendar_plugin.py`)

`CalendarPlugin` is a plain Python class. Each method is decorated with `@kernel_function` (import: `from semantic_kernel.functions import kernel_function`). Parameter descriptions are supplied via `typing.Annotated` metadata so the LLM sees accurate tool schemas. Context (token provider + accounts map) is injected via the constructor.

```python
class CalendarPlugin:
    def __init__(self, get_token_fn, accounts_map): ...
```

| Method | Params | Purpose |
|---|---|---|
| `list_configured_accounts` | none | Lists available account labels from session state |
| `list_user_calendars` | `account_label` | Lists all calendars for the account |
| `check_free_slots` | `account_label`, `date`, `start_time`, `end_time`, `timezone`, `interval_minutes` | Free/busy lookup for a date+time window |
| `list_calendar_events` | `account_label`, `calendar_name`, `start_datetime`, `end_datetime`, `timezone` | Lists events in a range |
| `book_appointment` | `account_label`, `calendar_name`, `subject`, `start_datetime`, `end_datetime`, `timezone`, `description`, `location` | Creates a personal appointment |

All methods are **synchronous** (Graph API calls via `requests`); Semantic Kernel supports sync `@kernel_function` methods without requiring `async def`.

Each `@kernel_function` method logs at `INFO` level when invoked (tool name, account label, key params — no access tokens). `book_appointment` additionally writes an **audit record** after the Graph call succeeds.

---

## Phase 5 — Agent (`agent/prompts.py` + `agent/agent_builder.py`)

**`prompts.py`**
- Plain string constant `SYSTEM_PROMPT`: calendar assistant that knows multiple Outlook accounts, always confirms timezone, names the account it is acting on, and asks for explicit user confirmation before booking.
- No template machinery required — `ChatCompletionAgent` accepts `instructions=` directly.

**`agent_builder.py`**
- `build_agent(get_token_fn, accounts_map) -> ChatCompletionAgent`
  - Instantiates `AzureChatCompletion(deployment_name, endpoint, api_key, api_version)` — reads env vars automatically from `.env` if present.
  - Instantiates `CalendarPlugin(get_token_fn, accounts_map)`.
  - Returns `ChatCompletionAgent(service=az_service, name="SlotPilot", instructions=SYSTEM_PROMPT, plugins=[plugin])`.
  - Auto function calling is **on by default** (`FunctionChoiceBehavior.Auto()`) — no extra configuration needed.

**Token consumption tracking**: After each `agent.get_response()` call in `chat.py`, the `AgentResponseItem.message` metadata is inspected for usage counts. Semantic Kernel surfaces token usage on the `ChatMessageContent` object via `metadata["usage"]` (an `CompletionsUsage`-like object containing `prompt_tokens`, `completion_tokens`, `total_tokens`). These values are:
  - Logged at `INFO` level: `[TOKEN_USAGE] prompt=X completion=Y total=Z`
  - Written to the **audit log** as part of each conversation turn record
  - Accumulated in `st.session_state.token_totals` (`{prompt: int, completion: int, total: int}`) for display in the chat sidebar

Key imports:
```
from semantic_kernel.agents import ChatCompletionAgent, ChatHistoryAgentThread
from semantic_kernel.connectors.ai.open_ai import AzureChatCompletion
```

---

## Phase 7 — Observability (`observability/logger.py` + `observability/audit.py`)

**`observability/logger.py`**
- `setup_logging()` — called once at app startup in `app.py`:
  - Creates `logs/` directory if absent
  - Attaches a `RotatingFileHandler` (`logs/app.log`, `maxBytes` from `LOG_MAX_BYTES`, `backupCount` from `LOG_BACKUP_COUNT`) with JSON formatter
  - Attaches a `StreamHandler` (console) with human-readable formatter
  - Sets root logger level from `LOG_LEVEL` env var
- `get_logger(name)` — thin wrapper around `logging.getLogger(name)`; every module calls this to get its named logger
- **JSON log format** (for log aggregation / future shipping): `{"ts": "ISO8601", "level": "INFO", "logger": "graph.client", "msg": "...", ...extra_fields}`

**`observability/audit.py`**
- `write_audit(event_type, payload: dict)` — appends a single JSONL record to `logs/audit.jsonl`:
  - `event_type` values: `ACCOUNT_ADDED`, `ACCOUNT_REMOVED`, `TOOL_INVOKED`, `APPOINTMENT_BOOKED`, `CHAT_TURN`
  - Every record includes: `ts` (UTC ISO8601), `event_type`, `session_id` (UUID generated per Streamlit session in `st.session_state`)
  - **`CHAT_TURN`** record includes: `user_input_length` (character count, not raw text for privacy), `active_accounts` (list of labels), `tools_invoked` (list of tool names called this turn), `prompt_tokens`, `completion_tokens`, `total_tokens`
  - **`APPOINTMENT_BOOKED`** record includes: `account_label`, `calendar_name`, `subject`, `start_datetime`, `end_datetime`, `timezone`, `event_id` (from Graph response)
  - **`TOOL_INVOKED`** record includes: `tool_name`, `account_label`, `success` (bool), `latency_ms`
  - **No raw user messages, email body content, or access tokens are ever written to audit log**
- File is opened in append mode (`"a"`) on each write — safe for single-process local use

---

## Phase 6 — Streamlit UI

**`app.py`** (entrypoint)
- Loads `.env` via `python-dotenv`
- Calls `observability.logger.setup_logging()` once at startup — configures root logger with `RotatingFileHandler` (`logs/app.log`, max 10 MB, 5 backups) and a `StreamHandler` for console; log level from `LOG_LEVEL` env var (default `INFO`).
- `st.navigation([st.Page("pages/chat.py", title="Chat", icon="💬"), st.Page("pages/accounts.py", title="Accounts", icon="🔑")])`
- Initializes `st.session_state` keys: `token_cache` (str), `accounts` (dict), `sk_thread` (`ChatHistoryAgentThread`), `token_totals` (dict `{prompt: 0, completion: 0, total: 0}`)

**`pages/accounts.py`**
1. **Add Account** button → `interactive_login` → on success, stores `{account: msal_account, email: str}` in `st.session_state.accounts[label]`, serializes cache to `st.session_state.token_cache`; logs `INFO`: account added (email only, no tokens)
2. **Accounts table** — shows label + email; **Remove** button calls `app.remove_account(account)` and deletes from `st.session_state.accounts`; logs `INFO`: account removed

**`pages/chat.py`**
1. Sidebar: `st.sidebar.multiselect` for active accounts; `st.sidebar.selectbox` for timezone (IANA list); **Clear Chat** button
2. Chat history display: read messages from `st.session_state.sk_thread` (a `ChatHistoryAgentThread` stored in session state); render each as `st.chat_message("user")` / `st.chat_message("assistant")`
3. `st.chat_input("Ask about your calendar...")` on submit:
   - Rebuild MSAL app from `st.session_state.token_cache`
   - Get tokens for active accounts → build `get_token_fn` closure
   - `build_agent(get_token_fn, accounts_map)` → `ChatCompletionAgent`
   - Retrieve or create `ChatHistoryAgentThread` from `st.session_state.sk_thread`
   - `response = asyncio.run(agent.get_response(user_input, thread=thread))`
   - Extract token usage from `response.message.metadata["usage"]`; log + accumulate in `st.session_state.token_totals`; write audit record
   - Store updated `thread` back to `st.session_state.sk_thread`; rerender
4. **Clear Chat**: `st.session_state.sk_thread = ChatHistoryAgentThread()`; resets `token_totals` for the session display (cumulative audit log is unaffected)
5. **Sidebar token meter**: `st.sidebar.metric` widgets showing session prompt tokens, completion tokens, and total tokens consumed

> `nest_asyncio.apply()` is called once at module top in `chat.py` to guard against `RuntimeError: This event loop is already running` in any Streamlit execution context.

---

## Verification Steps

1. `streamlit run app.py` — two pages appear: Chat and Accounts
2. Accounts page → "Add Account" → Microsoft browser login → account appears in table
3. Add a second account the same way
4. Chat page → sidebar shows both accounts in multiselect; select timezone
5. Ask "What meetings do I have tomorrow?" → agent calls `list_calendar_events`, returns formatted list
6. Ask "Am I free April 5 from 2pm to 3pm EST?" → agent calls `check_free_slots`, returns availability
7. Ask "Book a dentist appointment April 5, 2pm–3pm EST" → agent asks for confirmation → confirm → agent calls `book_appointment`, returns webLink
8. Verify the event appears in Outlook
9. Accounts page → Remove one account → it disappears from sidebar multiselect
10. Check `logs/app.log` — confirm structured JSON entries for tool invocations, token usage, Graph API calls
11. Check `logs/audit.jsonl` — confirm `APPOINTMENT_BOOKED` record with correct fields; confirm `CHAT_TURN` records include non-zero token counts
12. Chat sidebar shows session token meter updating after each response
13. Click Clear Chat — token meter resets; `logs/audit.jsonl` is unaffected (records persisted)

---

## Decisions & Scope Boundaries

- **Token cache**: stored only in `st.session_state` (not on disk) — re-login required on browser refresh. Avoids storing refresh tokens to disk on a local machine.
- **`getSchedule` limitation**: works only for work/school accounts. For personal Microsoft accounts, agent falls back to `list_events` to infer busy blocks. Documented in README.
- **No attendee invites**: `create_event` will not include an `attendees` field.
- **Booking target**: user selects active accounts in sidebar; agent always confirms before writing.
- **LLM**: Azure OpenAI via `semantic-kernel`'s `AzureChatCompletion`; all credentials via `.env`. Semantic Kernel auto-reads env vars matching `AZURE_OPENAI_*` conventions.
- **Deployment**: local machine only.
- **Logging**: structured JSON to `logs/app.log` (rotating); human-readable to console. Level controlled by `LOG_LEVEL` env var.
- **Audit log**: append-only JSONL at `logs/audit.jsonl`. Records every account change, tool call, booking, and chat turn with token consumption. No PII beyond email labels and event subjects.
- **Token tracking**: per-turn prompt/completion/total tokens extracted from SK `AgentResponseItem` metadata, accumulated in session state, and displayed in sidebar. Also written to audit log.
- **`logs/` directory**: added to `.gitignore` to prevent accidental commit of log data.

---

## Further Considerations

1. **Microsoft Agent Framework — Semantic Kernel**: The agent layer uses `semantic-kernel>=1.20.0` (`ChatCompletionAgent` + `AzureChatCompletion`). This is Microsoft's official AI orchestration SDK, replacing third-party frameworks like LangChain.
2. **Auto function calling**: `FunctionChoiceBehavior.Auto()` is the default for `ChatCompletionAgent` — no explicit configuration needed. The LLM decides when to invoke `CalendarPlugin` methods.
3. **Async in Streamlit**: All SK agent calls are `async`. `asyncio.run()` is used from synchronous Streamlit code; `nest_asyncio.apply()` is patched at startup to prevent `RuntimeError: This event loop is already running`.
4. **Conversation thread**: `ChatHistoryAgentThread` carries the full conversation history across turns within a Streamlit session. When the user clears chat, a new thread is instantiated. On page refresh, the thread is lost (session state reset); re-login is also required for tokens.
5. **MSAL browser login blocks Streamlit thread**: `acquire_token_interactive` opens a system browser and blocks until login completes. Acceptable for a local single-user app — no threading workaround needed.
6. **Personal vs. work accounts**: `getSchedule` API is restricted to work/school accounts. If personal Microsoft accounts are added, the free/busy check will gracefully fall back to event listing.
7. **Audit log privacy**: raw user message text is never written to the audit log — only character length is recorded. Event subjects from `book_appointment` are recorded (user-supplied data). This is documented in the README.
8. **Token usage extraction**: SK surfaces token counts in `ChatMessageContent.metadata["usage"]`. If a future SK version changes this structure, the extraction code is isolated in `agent_builder.py` and easy to update.
