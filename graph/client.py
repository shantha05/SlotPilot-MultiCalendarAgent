"""Microsoft Graph API client for SlotPilot.

All functions accept an access_token as their first argument and make
authenticated REST calls to https://graph.microsoft.com/v1.0.

Logging
-------
Every function logs at DEBUG level: HTTP method, URL, response status and
latency (ms).  create_event also writes an APPOINTMENT_BOOKED audit record.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import requests

from observability import audit
from observability.logger import get_logger

log = get_logger(__name__)

_BASE = "https://graph.microsoft.com/v1.0"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _headers(token: str, extra: Optional[dict] = None) -> dict:
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if extra:
        h.update(extra)
    return h


def _get(token: str, path: str, params: Optional[dict] = None, extra_headers: Optional[dict] = None) -> Any:
    url = f"{_BASE}{path}"
    t0 = time.monotonic()
    resp = requests.get(url, headers=_headers(token, extra_headers), params=params, timeout=30)
    latency = int((time.monotonic() - t0) * 1000)
    log.debug(
        "Graph GET",
        extra={"url": url, "status": resp.status_code, "latency_ms": latency},
    )
    resp.raise_for_status()
    return resp.json()


def _post(token: str, path: str, body: dict, extra_headers: Optional[dict] = None) -> Any:
    url = f"{_BASE}{path}"
    t0 = time.monotonic()
    resp = requests.post(url, headers=_headers(token, extra_headers), json=body, timeout=30)
    latency = int((time.monotonic() - t0) * 1000)
    log.debug(
        "Graph POST",
        extra={"url": url, "status": resp.status_code, "latency_ms": latency},
    )
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def list_calendars(access_token: str) -> list[dict]:
    """Return all calendars for the signed-in user.

    Returns a list of dicts with keys: id, name, canEdit.
    """
    data = _get(access_token, "/me/calendars", params={"$select": "id,name,canEdit"})
    return [
        {"id": c["id"], "name": c["name"], "canEdit": c.get("canEdit", False)}
        for c in data.get("value", [])
    ]


def list_events(
    access_token: str,
    calendar_id: str,
    start_dt_iso: str,
    end_dt_iso: str,
    timezone_str: str,
) -> list[dict]:
    """Return calendar events in the given time window.

    Uses calendarView so recurring events are expanded into individual
    occurrences.

    Args:
        access_token:  Bearer token.
        calendar_id:   Calendar ID from list_calendars().
        start_dt_iso:  ISO 8601 start (e.g. "2026-04-05T00:00:00").
        end_dt_iso:    ISO 8601 end.
        timezone_str:  IANA timezone name (e.g. "America/New_York").

    Returns:
        List of dicts with keys: subject, start, end, location.
    """
    path = f"/me/calendars/{calendar_id}/calendarView"
    params = {
        "startDateTime": start_dt_iso,
        "endDateTime": end_dt_iso,
        "$select": "subject,start,end,location",
        "$orderby": "start/dateTime",
        "$top": "100",
    }
    headers = {"Prefer": f'outlook.timezone="{timezone_str}"'}
    data = _get(access_token, path, params=params, extra_headers=headers)
    events = []
    for ev in data.get("value", []):
        events.append(
            {
                "subject": ev.get("subject", "(No subject)"),
                "start": ev.get("start", {}).get("dateTime", ""),
                "end": ev.get("end", {}).get("dateTime", ""),
                "location": ev.get("location", {}).get("displayName", ""),
            }
        )
    return events


def get_free_busy(
    access_token: str,
    email: str,
    start_dt_iso: str,
    end_dt_iso: str,
    timezone_str: str,
    interval_minutes: int = 30,
) -> dict:
    """Return free/busy information for the given email address.

    Works for work/school accounts only.  Raises requests.HTTPError for
    personal accounts (caller should fall back to list_events).

    Returns:
        Dict with keys: availabilityView (compact string), scheduleItems
        (list of busy blocks), workingHours.
    """
    body = {
        "schedules": [email],
        "startTime": {"dateTime": start_dt_iso, "timeZone": timezone_str},
        "endTime": {"dateTime": end_dt_iso, "timeZone": timezone_str},
        "availabilityViewInterval": interval_minutes,
    }
    data = _post(access_token, "/me/calendar/getSchedule", body)
    schedules = data.get("value", [])
    if not schedules:
        return {"availabilityView": "", "scheduleItems": [], "workingHours": {}}
    s = schedules[0]
    return {
        "availabilityView": s.get("availabilityView", ""),
        "scheduleItems": s.get("scheduleItems", []),
        "workingHours": s.get("workingHours", {}),
    }


def create_event(
    access_token: str,
    calendar_id: str,
    subject: str,
    start_dt_iso: str,
    end_dt_iso: str,
    timezone_str: str,
    body_text: str = "",
    location: str = "",
    session_id: str = "",
    account_label: str = "",
    calendar_name: str = "",
) -> dict:
    """Create a personal appointment in the specified calendar.

    No attendees are added (personal appointment only).

    Returns:
        Dict with keys: id, subject, start, end, webLink.
    """
    payload: dict[str, Any] = {
        "subject": subject,
        "start": {"dateTime": start_dt_iso, "timeZone": timezone_str},
        "end": {"dateTime": end_dt_iso, "timeZone": timezone_str},
        "body": {"contentType": "Text", "content": body_text},
    }
    if location:
        payload["location"] = {"displayName": location}

    data = _post(access_token, f"/me/calendars/{calendar_id}/events", payload)

    event_result = {
        "id": data.get("id", ""),
        "subject": data.get("subject", subject),
        "start": data.get("start", {}).get("dateTime", start_dt_iso),
        "end": data.get("end", {}).get("dateTime", end_dt_iso),
        "webLink": data.get("webLink", ""),
    }

    # Audit record
    audit.write_audit(
        audit.APPOINTMENT_BOOKED,
        {
            "account_label": account_label,
            "calendar_name": calendar_name,
            "subject": subject,
            "start_datetime": start_dt_iso,
            "end_datetime": end_dt_iso,
            "timezone": timezone_str,
            "event_id": event_result["id"],
        },
        session_id=session_id,
    )
    log.info(
        "Appointment booked",
        extra={
            "subject": subject,
            "start": start_dt_iso,
            "end": end_dt_iso,
            "timezone": timezone_str,
            "event_id": event_result["id"],
        },
    )
    return event_result
