# SlotPilot – Multi-Calendar Agent

A Streamlit chat app that checks and books Outlook 365 appointments across multiple accounts using Microsoft Semantic Kernel and Azure OpenAI.

---

## Features

- Authenticate with multiple Outlook 365 accounts via browser (OAuth2 PKCE)
- Check availability / free-busy slots across timezones
- List calendar events for any date range
- Book personal appointments
- Full structured logging and audit trail with token consumption tracking

---

## Prerequisites

- Python 3.10+
- An **Azure App Registration** (see below)
- An **Azure OpenAI** resource with a deployed chat model (e.g. `gpt-4o`)

---

## Azure App Registration Setup

1. Go to [Azure Portal → App registrations](https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps) → **New registration**
2. Name: `SlotPilot` (or any name)
3. Supported account types: **Accounts in any organizational directory and personal Microsoft accounts** (for multi-account support)
4. Redirect URI: choose **Mobile and desktop applications** → `http://localhost`
5. After creation, go to **Authentication** → scroll to **Advanced settings** → set **"Allow public client flows"** to **Yes** → **Save**
6. Copy the **Application (client) ID** → `MSAL_CLIENT_ID` in `.env`
7. Optionally copy the **Directory (tenant) ID** if you want to restrict to a single tenant (otherwise use `common`)
8. Go to **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**
9. Add the following permissions:
   - `Calendars.ReadWrite`
   - `User.Read`
10. Click **Grant admin consent** (if you are an admin), or users will consent individually on first login

> **Note on `getSchedule`**: The free/busy endpoint (`POST /me/calendar/getSchedule`) works only for **work or school accounts**. For personal Microsoft accounts, SlotPilot automatically falls back to listing events to determine busy blocks.

---

## Setup & Run

```bash
# 1. Clone the repo
git clone https://github.com/your-org/SlotPilot-MultiCalendarAgent
cd SlotPilot-MultiCalendarAgent

# 2. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure credentials
copy .env.example .env        # Windows
# cp .env.example .env        # macOS/Linux
# Fill in all values in .env

# 5. Run
streamlit run app.py
```

---

## Usage

1. Go to the **Accounts** page (sidebar) → click **Add Account** → sign in via browser
2. Add additional accounts as needed
3. Go to the **Chat** page → select active accounts and timezone in the sidebar
4. Ask questions like:
   - *"What meetings do I have today?"* (uses your selected timezone)
   - *"What meetings do I have tomorrow?"* (calculates based on your timezone)
   - *"Am I free this afternoon?"* (interprets relative to your local time)
   - *"Am I free on April 10 from 2pm to 3pm EST?"* (you can specify different timezones)
   - *"Book a dentist appointment tomorrow at 2pm for 1 hour"* (uses your timezone by default)

**Timezone Awareness**: The agent is fully timezone-aware. Select your timezone in the sidebar, and relative dates/times like "today", "tomorrow", "this morning", "next Monday" will be calculated in your local time. You can also specify different timezones explicitly in your queries (e.g., "2pm EST", "3pm Pacific").

---

## Logging & Audit

| File | Contents |
|---|---|
| `logs/app.log` | Structured JSON application log (rotating, max 10 MB × 5 backups) |
| `logs/audit.jsonl` | Append-only audit trail — account changes, tool calls, bookings, token usage per turn |

> `logs/` is gitignored. Audit records never contain raw message text or access tokens.

---

## Environment Variables Reference

| Variable | Description |
|---|---|
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | e.g. `https://myresource.openai.azure.com/` |
| `AZURE_OPENAI_DEPLOYMENT` | Chat deployment name (e.g. `gpt-4o`) |
| `AZURE_OPENAI_API_VERSION` | API version (default `2024-02-01`) |
| `MSAL_CLIENT_ID` | Azure App Registration client ID |
| `MSAL_TENANT_ID` | Tenant ID or `common` for multi-tenant |
| `MSAL_REDIRECT_URI` | Must be `http://localhost` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` (default `INFO`) |
| `LOG_MAX_BYTES` | Max log file size in bytes (default `10485760` = 10 MB) |
| `LOG_BACKUP_COUNT` | Number of rotated log backups (default `5`) |
