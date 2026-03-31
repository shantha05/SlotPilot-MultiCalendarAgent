"""MSAL authentication helpers for SlotPilot.

Provides a thin, stateless layer over the MSAL PublicClientApplication.
Token cache state is always passed in / returned as a serialised string so
callers (Streamlit pages) can store it in st.session_state without importing
MSAL internals.
"""
from __future__ import annotations

import os
from typing import Optional

import msal

from observability.logger import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Scopes
# ---------------------------------------------------------------------------
GRAPH_SCOPES: list[str] = [
    "Calendars.ReadWrite",
    "User.Read",
]

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def build_public_client_app(
    token_cache_str: Optional[str] = None,
) -> tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
    """Create a PublicClientApplication backed by a SerializableTokenCache.

    Args:
        token_cache_str: Previously serialised cache string from
                         ``serialize_cache()``.  Pass ``None`` on first run.

    Returns:
        (app, cache) tuple.  ``cache`` should be serialised and stored in
        ``st.session_state`` after every operation that may change it.
    """
    client_id = os.environ["MSAL_CLIENT_ID"]
    tenant_id = os.getenv("MSAL_TENANT_ID", "common")
    authority = f"https://login.microsoftonline.com/{tenant_id}"

    cache = msal.SerializableTokenCache()
    if token_cache_str:
        cache.deserialize(token_cache_str)

    app = msal.PublicClientApplication(
        client_id=client_id,
        authority=authority,
        token_cache=cache,
    )
    log.debug("PublicClientApplication created", extra={"authority": authority})
    return app, cache


def get_token_for_account(
    app: msal.PublicClientApplication,
    account: dict,
    scopes: list[str] = GRAPH_SCOPES,
) -> Optional[str]:
    """Attempt a silent token acquisition for the given cached account.

    Returns:
        Access token string on success, ``None`` if silent acquisition fails
        (caller should trigger interactive login).
    """
    result = app.acquire_token_silent(scopes, account=account)
    if result and "access_token" in result:
        log.debug(
            "Silent token acquisition succeeded",
            extra={"username": account.get("username")},
        )
        return result["access_token"]
    log.debug(
        "Silent token acquisition failed — interactive login required",
        extra={"username": account.get("username"), "error": (result or {}).get("error")},
    )
    return None


def interactive_login(
    app: msal.PublicClientApplication,
    scopes: list[str] = GRAPH_SCOPES,
) -> dict:
    """Open a browser window for interactive OAuth2 PKCE login.

    The call blocks the current thread until the user completes login or
    the browser is closed.

    Returns:
        MSAL result dict.  Check for ``"access_token"`` key on success or
        ``"error"`` key on failure.
    """
    log.info("Starting interactive browser login")
    result = app.acquire_token_interactive(
        scopes=scopes,
        prompt=msal.Prompt.SELECT_ACCOUNT,
    )
    if "access_token" in result:
        username = result.get("id_token_claims", {}).get("preferred_username", "unknown")
        log.info("Interactive login succeeded", extra={"username": username})
    else:
        log.warning(
            "Interactive login failed",
            extra={"error": result.get("error"), "description": result.get("error_description")},
        )
    return result


def serialize_cache(cache: msal.SerializableTokenCache) -> str:
    """Serialise the token cache to a JSON string for session state storage."""
    return cache.serialize()
