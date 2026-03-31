"""Semantic Kernel plugin providing calendar tools to the SlotPilot agent.

Each public method is decorated with @kernel_function.  Parameter
descriptions use typing.Annotated so the LLM receives accurate schema
information.  All methods are synchronous — SK supports sync kernel
functions without async def.

Context (token provider + accounts map) is injected via __init__ so tools
can be rebuilt each turn with fresh tokens while keeping a clean interface.
"""
from __future__ import annotations

import time
from typing import Annotated, Callable, Optional

import requests
from semantic_kernel.functions import kernel_function

from graph import client as graph
from observability import audit
from observability.logger import get_logger

log = get_logger(__name__)


class CalendarPlugin:
    """Semantic Kernel plugin for Outlook 365 calendar operations."""

    def __init__(
        self,
        get_token_fn: Callable[[str], Optional[str]],
        accounts_map: dict,
        session_id: str = "",
    ) -> None:
        """Initialise the plugin.

        Args:
            get_token_fn:  Callable that accepts an account_label string and
                           returns a valid Bearer access token (or None).
            accounts_map:  Dict mapping label → {account: msal_account,
                           email: str}.
            session_id:    Streamlit session UUID for audit records.
        """
        self._get_token = get_token_fn
        self._accounts = accounts_map
        self._session_id = session_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_label(self, label: str) -> str:
        """Return the canonical account label, tolerating case differences and
        partial matches (e.g. 'Work' matches 'Pearl Innovations - Work')."""
        # 1. Exact match
        if label in self._accounts:
            return label
        label_lower = label.lower()
        # 2. Case-insensitive exact match
        for key in self._accounts:
            if key.lower() == label_lower:
                return key
        # 3. Substring: stored label contains the supplied label
        for key in self._accounts:
            if label_lower in key.lower():
                return key
        # 4. Substring: supplied label contains the stored label
        for key in self._accounts:
            if key.lower() in label_lower:
                return key
        # No match — return as-is so the caller gets a clear error
        return label

    def _token(self, label: str) -> str:
        resolved = self._resolve_label(label)
        token = self._get_token(resolved)
        if not token:
            available = ", ".join(f"'{k}'" for k in self._accounts)
            raise ValueError(
                f"No valid access token for account '{label}' (resolved: '{resolved}'). "
                f"Available accounts: {available}. "
                "Please re-authenticate on the Accounts page."
            )
        return token

    def _audit_tool(self, tool_name: str, account_label: str, success: bool, latency_ms: int) -> None:
        audit.write_audit(
            audit.TOOL_INVOKED,
            {
                "tool_name": tool_name,
                "account_label": account_label,
                "success": success,
                "latency_ms": latency_ms,
            },
            session_id=self._session_id,
        )

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @kernel_function(
        name="list_configured_accounts",
        description=(
            "Returns the list of Outlook account labels that have been "
            "authenticated and are available for calendar queries."
        ),
    )
    def list_configured_accounts(self) -> str:
        """Return all configured account labels."""
        if not self._accounts:
            return "No accounts configured. Please add an account on the Accounts page."
        lines = [f"- {label} ({info['email']})" for label, info in self._accounts.items()]
        return "Configured accounts:\n" + "\n".join(lines)

    @kernel_function(
        name="list_user_calendars",
        description="Lists all calendars for a given configured Outlook account.",
    )
    def list_user_calendars(
        self,
        account_label: Annotated[str, "The account label as shown on the Accounts page (e.g. 'Work', 'Personal')."],
    ) -> str:
        t0 = time.monotonic()
        log.info("Tool invoked: list_user_calendars", extra={"account_label": account_label})
        try:
            token = self._token(account_label)
            account_label = self._resolve_label(account_label)
            calendars = graph.list_calendars(token)
            latency = int((time.monotonic() - t0) * 1000)
            self._audit_tool("list_user_calendars", account_label, True, latency)
            if not calendars:
                return f"No calendars found for account '{account_label}'."
            lines = [f"- {c['name']} (id: {c['id']}, editable: {c['canEdit']})" for c in calendars]
            return f"Calendars for '{account_label}':\n" + "\n".join(lines)
        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
            self._audit_tool("list_user_calendars", account_label, False, latency)
            log.warning("list_user_calendars failed", extra={"error": str(exc)})
            return f"Error listing calendars: {exc}"

    @kernel_function(
        name="list_calendar_events",
        description=(
            "Lists all events in a specified calendar for the given date/time range. "
            "Use this to show the user what appointments they have."
        ),
    )
    def list_calendar_events(
        self,
        account_label: Annotated[str, "Account label (e.g. 'Work')."],
        calendar_name: Annotated[str, "Calendar name (e.g. 'Calendar', 'Personal')."],
        start_datetime: Annotated[str, "Start of the range in ISO 8601 format (e.g. '2026-04-05T00:00:00')."],
        end_datetime: Annotated[str, "End of the range in ISO 8601 format (e.g. '2026-04-05T23:59:59')."],
        timezone: Annotated[str, "IANA timezone name (e.g. 'America/New_York', 'Europe/London', 'UTC')."],
    ) -> str:
        t0 = time.monotonic()
        log.info(
            "Tool invoked: list_calendar_events",
            extra={"account_label": account_label, "calendar_name": calendar_name,
                   "start": start_datetime, "end": end_datetime, "tz": timezone},
        )
        try:
            token = self._token(account_label)
            account_label = self._resolve_label(account_label)
            calendars = graph.list_calendars(token)
            cal = next((c for c in calendars if c["name"].lower() == calendar_name.lower()), None)
            if not cal:
                available = ", ".join(c["name"] for c in calendars)
                return (
                    f"Calendar '{calendar_name}' not found for account '{account_label}'. "
                    f"Available calendars: {available}"
                )
            events = graph.list_events(token, cal["id"], start_datetime, end_datetime, timezone)
            latency = int((time.monotonic() - t0) * 1000)
            self._audit_tool("list_calendar_events", account_label, True, latency)
            if not events:
                return f"No events found in '{calendar_name}' for the specified range."
            lines = [
                f"- {ev['subject']} | {ev['start']} → {ev['end']}"
                + (f" @ {ev['location']}" if ev.get("location") else "")
                for ev in events
            ]
            return f"Events in '{calendar_name}' ({account_label}):\n" + "\n".join(lines)
        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
            self._audit_tool("list_calendar_events", account_label, False, latency)
            log.warning("list_calendar_events failed", extra={"error": str(exc)})
            return f"Error listing events: {exc}"

    @kernel_function(
        name="check_free_slots",
        description=(
            "Checks the free/busy availability for an account over a specified time window. "
            "Returns whether the user is free or busy and lists existing busy blocks. "
            "For work/school accounts this uses the Graph getSchedule API. "
            "For personal Microsoft accounts it falls back to listing calendar events."
        ),
    )
    def check_free_slots(
        self,
        account_label: Annotated[str, "Account label (e.g. 'Work')."],
        date: Annotated[str, "Date to check in YYYY-MM-DD format (e.g. '2026-04-05')."],
        start_time: Annotated[str, "Start of the window in HH:MM 24-hour format (e.g. '09:00')."],
        end_time: Annotated[str, "End of the window in HH:MM 24-hour format (e.g. '17:00')."],
        timezone: Annotated[str, "IANA timezone name (e.g. 'America/New_York')."],
        interval_minutes: Annotated[int, "Slot size in minutes for the availability view (default 30)."] = 30,
    ) -> str:
        t0 = time.monotonic()
        log.info(
            "Tool invoked: check_free_slots",
            extra={"account_label": account_label, "date": date,
                   "start_time": start_time, "end_time": end_time, "tz": timezone},
        )
        start_iso = f"{date}T{start_time}:00"
        end_iso = f"{date}T{end_time}:00"
        account_label = self._resolve_label(account_label)
        email = self._accounts.get(account_label, {}).get("email", "")

        try:
            token = self._token(account_label)
            try:
                fb = graph.get_free_busy(token, email, start_iso, end_iso, timezone, interval_minutes)
                availability = fb["availabilityView"]
                busy_items = fb["scheduleItems"]
                latency = int((time.monotonic() - t0) * 1000)
                self._audit_tool("check_free_slots", account_label, True, latency)

                # Build human-readable summary
                slot_map = {"0": "free", "1": "tentative", "2": "busy", "3": "OOF", "4": "working elsewhere"}
                slots_summary = ", ".join(slot_map.get(ch, "?") for ch in availability) if availability else "no data"
                lines = [f"Availability ({interval_minutes}-min slots): [{slots_summary}]"]
                if busy_items:
                    lines.append("Busy blocks:")
                    for item in busy_items:
                        lines.append(
                            f"  - {item.get('subject', '(busy)')} | "
                            f"{item.get('start', {}).get('dateTime', '')} → "
                            f"{item.get('end', {}).get('dateTime', '')}"
                        )
                else:
                    lines.append("No busy blocks — the slot appears free.")
                return f"Free/busy for '{account_label}' on {date} {start_time}–{end_time} {timezone}:\n" + "\n".join(lines)

            except requests.HTTPError as http_err:
                # Fall back to listing events for personal accounts
                log.info(
                    "getSchedule failed, falling back to listing events",
                    extra={"status": http_err.response.status_code if http_err.response else None},
                )
                calendars = graph.list_calendars(token)
                all_events = []
                for cal in calendars:
                    all_events.extend(graph.list_events(token, cal["id"], start_iso, end_iso, timezone))
                latency = int((time.monotonic() - t0) * 1000)
                self._audit_tool("check_free_slots", account_label, True, latency)
                if not all_events:
                    return f"The slot {date} {start_time}–{end_time} {timezone} appears free (no events found)."
                lines = [f"Events found (slot may be busy):"]
                for ev in all_events:
                    lines.append(f"  - {ev['subject']} | {ev['start']} → {ev['end']}")
                return "\n".join(lines)

        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
            self._audit_tool("check_free_slots", account_label, False, latency)
            log.warning("check_free_slots failed", extra={"error": str(exc)})
            return f"Error checking availability: {exc}"

    @kernel_function(
        name="book_appointment",
        description=(
            "Creates a personal appointment in the specified calendar. "
            "Only call this after the user has explicitly confirmed the details. "
            "Always check free/busy first."
        ),
    )
    def book_appointment(
        self,
        account_label: Annotated[str, "Account label (e.g. 'Work')."],
        calendar_name: Annotated[str, "Calendar name to book into (e.g. 'Calendar')."],
        subject: Annotated[str, "Title / subject of the appointment (e.g. 'Dentist appointment')."],
        start_datetime: Annotated[str, "Start time in ISO 8601 format (e.g. '2026-04-05T14:00:00')."],
        end_datetime: Annotated[str, "End time in ISO 8601 format (e.g. '2026-04-05T15:00:00')."],
        timezone: Annotated[str, "IANA timezone name (e.g. 'America/New_York')."],
        description: Annotated[str, "Optional body/notes for the appointment."] = "",
        location: Annotated[str, "Optional location name."] = "",
    ) -> str:
        t0 = time.monotonic()
        log.info(
            "Tool invoked: book_appointment",
            extra={"account_label": account_label, "subject": subject,
                   "start": start_datetime, "end": end_datetime, "tz": timezone},
        )
        try:
            token = self._token(account_label)
            account_label = self._resolve_label(account_label)
            calendars = graph.list_calendars(token)
            cal = next((c for c in calendars if c["name"].lower() == calendar_name.lower()), None)
            if not cal:
                available = ", ".join(c["name"] for c in calendars)
                return (
                    f"Calendar '{calendar_name}' not found for account '{account_label}'. "
                    f"Available: {available}"
                )
            if not cal["canEdit"]:
                return f"Calendar '{calendar_name}' is read-only. Please choose a different calendar."

            event = graph.create_event(
                access_token=token,
                calendar_id=cal["id"],
                subject=subject,
                start_dt_iso=start_datetime,
                end_dt_iso=end_datetime,
                timezone_str=timezone,
                body_text=description,
                location=location,
                session_id=self._session_id,
                account_label=account_label,
                calendar_name=calendar_name,
            )
            latency = int((time.monotonic() - t0) * 1000)
            self._audit_tool("book_appointment", account_label, True, latency)
            return (
                f"Appointment booked!\n"
                f"Subject: {event['subject']}\n"
                f"Start:   {event['start']}\n"
                f"End:     {event['end']}\n"
                f"Link:    {event['webLink']}"
            )
        except Exception as exc:
            latency = int((time.monotonic() - t0) * 1000)
            self._audit_tool("book_appointment", account_label, False, latency)
            log.warning("book_appointment failed", extra={"error": str(exc)})
            return f"Error booking appointment: {exc}"
