"""Accounts management page — add / remove Outlook 365 accounts."""

import streamlit as st

from auth.msal_helper import (
    GRAPH_SCOPES,
    build_public_client_app,
    interactive_login,
    serialize_cache,
)
from auth.storage import save_accounts, save_token_cache
from observability.audit import ACCOUNT_ADDED, ACCOUNT_REMOVED, write_audit
from observability.logger import get_logger

_log = get_logger(__name__)

st.title("Accounts")
st.caption("Connect your Outlook 365 accounts via Microsoft login.")

# ── helpers ──────────────────────────────────────────────────────────────────


def _save_cache(cache) -> None:
    st.session_state.token_cache = serialize_cache(cache)
    # Persist to disk
    save_token_cache(st.session_state.token_cache)


# ── Add account ──────────────────────────────────────────────────────────────

st.subheader("Add Account")

label_input = st.text_input(
    "Account label",
    placeholder="e.g. Work, Personal",
    help="A short friendly name you'll use to refer to this account in chat.",
)

if st.button("Login with Microsoft", type="primary"):
    if not label_input.strip():
        st.error("Please enter a label before logging in.")
    elif label_input.strip() in st.session_state.get("accounts", {}):
        st.error(f"An account with label '{label_input.strip()}' already exists.")
    else:
        with st.spinner("Opening browser for Microsoft login…"):
            try:
                app, cache = build_public_client_app(
                    st.session_state.get("token_cache", "")
                )
                result = interactive_login(app, GRAPH_SCOPES)

                if "error" in result:
                    st.error(
                        f"Login failed: {result.get('error_description', result['error'])}"
                    )
                    _log.warning(
                        "Interactive login failed",
                        extra={"error": result.get("error")},
                    )
                else:
                    claims = result.get("id_token_claims", {})
                    email = claims.get("preferred_username") or claims.get(
                        "email", "unknown"
                    )

                    label = label_input.strip()
                    if "accounts" not in st.session_state:
                        st.session_state.accounts = {}

                    # Store only the email — the MSAL account object is looked
                    # up fresh from the cache on every token request so it is
                    # always bound to the current PublicClientApplication instance.
                    st.session_state.accounts[label] = {
                        "email": email,
                    }
                    _save_cache(cache)
                    # Persist accounts to disk
                    save_accounts(st.session_state.accounts)

                    write_audit(
                        ACCOUNT_ADDED,
                        {"label": label, "email": email},
                        st.session_state.get("session_id", ""),
                    )
                    _log.info(
                        "Account added",
                        extra={"label": label, "email": email},
                    )
                    st.success(f"Account '{label}' ({email}) added successfully.")
                    st.rerun()

            except Exception as exc:  # noqa: BLE001
                _log.exception("Unexpected error during login")
                st.error(f"Unexpected error: {exc}")

# ── Existing accounts ─────────────────────────────────────────────────────────

st.divider()
st.subheader("Configured Accounts")

accounts: dict = st.session_state.get("accounts", {})

if not accounts:
    st.info("No accounts configured yet. Use the form above to add one.")
else:
    for label, info in list(accounts.items()):
        col_label, col_email, col_action = st.columns([2, 4, 1])

        with col_label:
            st.write(f"**{label}**")
        with col_email:
            st.write(info.get("email", "—"))
        with col_action:
            if st.button("Remove", key=f"remove_{label}"):
                # Remove from MSAL cache if possible
                try:
                    app, cache = build_public_client_app(
                        st.session_state.get("token_cache", "")
                    )
                    msal_acct = info.get("account")
                    if msal_acct:
                        app.remove_account(msal_acct)
                    _save_cache(cache)
                except Exception:  # noqa: BLE001
                    _log.warning("Could not remove account from MSAL cache", extra={"label": label})

                del st.session_state.accounts[label]
                # Persist changes to disk
                save_accounts(st.session_state.accounts)

                write_audit(
                    ACCOUNT_REMOVED,
                    {"label": label},
                    st.session_state.get("session_id", ""),
                )
                _log.info("Account removed", extra={"label": label})
                st.rerun()
