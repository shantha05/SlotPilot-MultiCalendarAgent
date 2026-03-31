"""Append-only JSONL audit log for SlotPilot.

Audit records capture security-relevant and operational events without
storing raw user message text or access tokens.

Event types
-----------
ACCOUNT_ADDED      — a new MSAL account was authenticated and stored
ACCOUNT_REMOVED    — an account was removed from session state
TOOL_INVOKED       — a CalendarPlugin kernel function was called
APPOINTMENT_BOOKED — create_event Graph call succeeded
CHAT_TURN          — one full agent conversation turn completed
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_AUDIT_FILE = Path(__file__).parent.parent / "logs" / "audit.jsonl"

# Valid event type literals (kept as strings for simplicity; not an Enum so
# callers don't need to import the class).
ACCOUNT_ADDED = "ACCOUNT_ADDED"
ACCOUNT_REMOVED = "ACCOUNT_REMOVED"
TOOL_INVOKED = "TOOL_INVOKED"
APPOINTMENT_BOOKED = "APPOINTMENT_BOOKED"
CHAT_TURN = "CHAT_TURN"


def write_audit(event_type: str, payload: dict[str, Any], session_id: str = "") -> None:
    """Append one JSONL audit record to logs/audit.jsonl.

    Args:
        event_type: One of the module-level constants (e.g. ACCOUNT_ADDED).
        payload:    Event-specific fields.  Must not contain access tokens or
                    raw user message content.
        session_id: UUID string identifying the current Streamlit session.
                    Pass st.session_state.session_id from the caller.
    """
    _AUDIT_FILE.parent.mkdir(parents=True, exist_ok=True)

    record: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "session_id": session_id,
    }
    record.update(payload)

    with _AUDIT_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")
