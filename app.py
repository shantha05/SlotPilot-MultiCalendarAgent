"""SlotPilot — Multi-Calendar Agent
Streamlit entrypoint: initialises session state, logging, and page navigation.
"""

import uuid

import streamlit as st
from dotenv import load_dotenv

# Load .env before any module reads os.environ
load_dotenv()

# Initialise structured logging (idempotent — safe to call multiple times)
from observability.logger import setup_logging  # noqa: E402

setup_logging()

# ── page config (must be the first Streamlit call) ────────────────────────────
st.set_page_config(
    page_title="SlotPilot",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── session state defaults ─────────────────────────────────────────────────────

if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())

if "token_cache" not in st.session_state:
    # Serialised MSAL token cache string; kept in memory only (not persisted to disk)
    st.session_state.token_cache = ""

if "accounts" not in st.session_state:
    # {label: {"account": msal_account_obj, "email": str}}
    st.session_state.accounts = {}

if "sk_thread" not in st.session_state:
    # Semantic Kernel ChatHistoryAgentThread; None = start a fresh thread
    st.session_state.sk_thread = None

if "chat_history" not in st.session_state:
    # Plain list of {"role": "user"|"assistant", "content": str} for rendering
    st.session_state.chat_history = []

if "token_totals" not in st.session_state:
    st.session_state.token_totals = {"prompt": 0, "completion": 0, "total": 0}

if "active_timezone" not in st.session_state:
    st.session_state.active_timezone = "UTC"

# ── navigation ────────────────────────────────────────────────────────────────

pages = st.navigation(
    [
        st.Page("pages/chat.py", title="Chat", icon="💬", default=True),
        st.Page("pages/accounts.py", title="Accounts", icon="🔑"),
    ]
)

pages.run()
