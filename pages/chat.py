"""Chat page — multi-calendar assistant powered by Semantic Kernel."""

import asyncio
import uuid

import nest_asyncio  # must be applied before any asyncio.run in Streamlit
import pytz
import streamlit as st

from agent.agent_builder import build_agent, extract_token_usage
from auth.msal_helper import GRAPH_SCOPES, build_public_client_app, get_token_for_account
from observability.audit import CHAT_TURN, write_audit
from observability.logger import get_logger

nest_asyncio.apply()

_log = get_logger(__name__)

# ── page title ────────────────────────────────────────────────────────────────

st.title("SlotPilot")
st.caption("Ask about your calendar or book an appointment.")

# ── sidebar — active accounts & timezone ─────────────────────────────────────

with st.sidebar:
    st.header("Settings")

    all_labels = list(st.session_state.get("accounts", {}).keys())

    if not all_labels:
        st.warning("No accounts configured. Go to **Accounts** to add one.")
        active_labels = []
    else:
        active_labels = st.multiselect(
            "Active accounts",
            options=all_labels,
            default=all_labels,
            help="The agent will query only these accounts.",
        )

    timezone = st.selectbox(
        "Your timezone",
        options=pytz.all_timezones,
        index=pytz.all_timezones.index("UTC"),
        help="Used when you don't specify a timezone in your message.",
    )
    st.session_state.active_timezone = timezone

    st.divider()
    st.subheader("Token Usage (this session)")

    totals = st.session_state.get(
        "token_totals", {"prompt": 0, "completion": 0, "total": 0}
    )
    col1, col2 = st.columns(2)
    col1.metric("Prompt", totals["prompt"])
    col2.metric("Completion", totals["completion"])
    st.metric("Total", totals["total"])

    if st.button("Clear Chat", use_container_width=True):
        st.session_state.chat_history = []
        st.session_state.sk_thread = None
        st.session_state.token_totals = {"prompt": 0, "completion": 0, "total": 0}
        st.rerun()

# ── chat history rendering ────────────────────────────────────────────────────

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ── chat input ────────────────────────────────────────────────────────────────

user_input = st.chat_input(
    "Ask about free slots, upcoming events, or book an appointment…",
    disabled=not active_labels,
)

if user_input:
    # Render user message immediately
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    # Build active accounts map (only selected labels)
    active_accounts: dict = {
        label: info
        for label, info in st.session_state.get("accounts", {}).items()
        if label in active_labels
    }

    if not active_accounts:
        reply = "No active accounts selected. Please choose at least one account in the sidebar."
        st.session_state.chat_history.append({"role": "assistant", "content": reply})
        with st.chat_message("assistant"):
            st.markdown(reply)
        st.stop()

    # Rebuild MSAL app from current cache so silent token calls work
    app, cache = build_public_client_app(st.session_state.get("token_cache", ""))

    def _get_token(label: str) -> str | None:
        """Closure: acquire a token silently for the given label."""
        info = active_accounts.get(label)
        if info is None:
            _log.warning("Token requested for unknown account label", extra={"label": label})
            return None
        email = info.get("email", "")

        # 1. Try exact username match (fastest path)
        candidates = app.get_accounts(username=email)

        # 2. Fallback: username in cache may differ from preferred_username in
        #    id_token claims (e.g. UPN vs alias).  Search all cached accounts
        #    and pick the one whose username contains the local-part of the email.
        if not candidates:
            all_cached = app.get_accounts()
            _log.debug(
                "Exact username lookup missed; scanning all cached accounts",
                extra={"label": label, "email": email, "cached": [a.get("username") for a in all_cached]},
            )
            local = email.split("@")[0].lower() if "@" in email else email.lower()
            candidates = [
                a for a in all_cached
                if a.get("username", "").lower().startswith(local)
            ] or all_cached  # last resort: try every cached account

        if not candidates:
            _log.warning("No accounts in token cache", extra={"label": label, "email": email})
            return None

        token = get_token_for_account(app, candidates[0], GRAPH_SCOPES)
        if token:
            return token

        # 3. If silent call still fails (e.g. expired refresh token), log clearly
        _log.warning(
            "Silent token acquisition failed for all candidates",
            extra={"label": label, "email": email},
        )
        return None

    # Ensure session ID persists
    if "session_id" not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())

    # Build (or rebuild) the agent each turn — CalendarPlugin holds fresh token closure
    agent = build_agent(
        get_token_fn=_get_token,
        accounts_map=active_accounts,
        session_id=st.session_state.session_id,
    )

    # Inject user timezone hint into the message if not already mentioned
    tz_hint = st.session_state.get("active_timezone", "UTC")
    augmented_input = (
        f"[User timezone: {tz_hint}]\n{user_input}"
        if tz_hint.lower() not in user_input.lower()
        else user_input
    )

    tools_invoked: list[str] = []

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            try:
                from semantic_kernel.agents import ChatHistoryAgentThread  # noqa: PLC0415

                thread: ChatHistoryAgentThread | None = st.session_state.get("sk_thread")

                response = asyncio.run(
                    agent.get_response(
                        messages=augmented_input,
                        thread=thread,
                    )
                )

                # Persist thread for conversation continuity
                st.session_state.sk_thread = response.thread

                reply_text = str(response.message.content)

                # Extract token usage
                usage = extract_token_usage(response.message)
                if "token_totals" not in st.session_state:
                    st.session_state.token_totals = {
                        "prompt": 0,
                        "completion": 0,
                        "total": 0,
                    }
                st.session_state.token_totals["prompt"] += usage["prompt_tokens"]
                st.session_state.token_totals["completion"] += usage["completion_tokens"]
                st.session_state.token_totals["total"] += usage["total_tokens"]

                # Collect tool names that were called (from inner content items if available)
                try:
                    for item in response.message.items or []:
                        item_type = type(item).__name__
                        if "FunctionCall" in item_type or "ToolCall" in item_type:
                            tools_invoked.append(getattr(item, "name", item_type))
                except Exception:  # noqa: BLE001
                    pass

                st.markdown(reply_text)

            except Exception as exc:  # noqa: BLE001
                _log.exception("Agent error during chat turn")
                reply_text = f"An error occurred while processing your request: {exc}"
                st.error(reply_text)

    # Persist assistant message and update cache
    st.session_state.chat_history.append({"role": "assistant", "content": reply_text})
    st.session_state.token_cache = cache.serialize() if hasattr(cache, "serialize") else st.session_state.get("token_cache", "")

    # Audit the chat turn
    write_audit(
        CHAT_TURN,
        {
            "input_chars": len(user_input),
            "tools_invoked": tools_invoked,
            "active_accounts": list(active_accounts.keys()),
            "prompt_tokens": st.session_state.token_totals["prompt"],
            "completion_tokens": st.session_state.token_totals["completion"],
            "total_tokens": st.session_state.token_totals["total"],
        },
        st.session_state.get("session_id", ""),
    )

    # Rerun to refresh token meter in sidebar
    st.rerun()
