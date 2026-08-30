"""Cal.com. Read bookings and cancel them.

Endpoints verified against cal.com/docs/api-reference/v2 on 2026-08-30.

THE VERSION HEADER IS PER ENDPOINT. `cal-api-version` is not one value for the
whole API: listing bookings wants 2026-05-01 and cancelling one wants
2026-02-25. Sending the wrong one is a 400, so the versions live next to the
calls that need them rather than in a single setting.

    [providers.calcom]
    event_type_id = 0            # optional filter, the screener event type
"""

from __future__ import annotations

from typing import Any

from .. import httpjson
from ..config import secret
from ..util import norm_email
from . import register

BASE = "https://api.cal.com/v2"

# Per endpoint, from the docs. Do not collapse these into one value.
VERSION_LIST_BOOKINGS = "2026-05-01"
VERSION_CANCEL_BOOKING = "2026-02-25"
VERSION_CREATE_BOOKING = "2026-02-25"

# Fields Cal.com puts in the responses block that are not screener answers.
NOT_AN_ANSWER = {
    "name", "email", "guests", "location", "attendeePhoneNumber",
    "smsReminderNumber", "rescheduleReason", "title", "notes",
}


class CalComBooking:
    name = "calcom"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.calcom", {}) or {}) if hasattr(settings, "get") else {}
        self.event_type_id = cfg.get("event_type_id")

    def _headers(self, version: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {secret('CALCOM_API_KEY', required=True)}",
            "cal-api-version": version,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _attendee(booking: dict[str, Any]) -> tuple[str, str]:
        attendees = booking.get("attendees") or []
        if attendees and isinstance(attendees[0], dict):
            return (
                str(attendees[0].get("name") or ""),
                norm_email(attendees[0].get("email") or ""),
            )
        return str(booking.get("title") or ""), ""

    @staticmethod
    def _answers(booking: dict[str, Any]) -> dict[str, str]:
        responses = booking.get("bookingFieldsResponses") or booking.get("responses") or {}
        if not isinstance(responses, dict):
            return {}
        out = {}
        for key, value in responses.items():
            if key in NOT_AN_ANSWER:
                continue
            out[key] = value if isinstance(value, str) else str(value)
        return out

    def list_bookings(self, since: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"status": "upcoming", "take": 100, "sortStart": "asc"}
        if self.event_type_id:
            params["eventTypeId"] = self.event_type_id
        if since:
            params["afterStart"] = since

        out: list[dict[str, Any]] = []
        cursor = None
        for _page in range(20):
            if cursor:
                params["cursor"] = cursor
            payload = httpjson.get(
                f"{BASE}/bookings",
                headers=self._headers(VERSION_LIST_BOOKINGS),
                params=params,
            )
            if not isinstance(payload, dict):
                break
            rows = payload.get("data")
            if isinstance(rows, dict):
                rows = rows.get("bookings") or []
            for booking in rows or []:
                if not isinstance(booking, dict):
                    continue
                name, email = self._attendee(booking)
                out.append({
                    "provider_id": str(booking.get("uid") or booking.get("id") or ""),
                    "attendee_name": name,
                    "attendee_email": email,
                    "start_at": booking.get("start") or booking.get("startTime"),
                    "end_at": booking.get("end") or booking.get("endTime"),
                    "answers": self._answers(booking),
                })
            pagination = payload.get("pagination") or {}
            if not pagination.get("hasMore"):
                break
            cursor = pagination.get("cursor") or pagination.get("nextCursor")
            if not cursor:
                break
        return out

    def cancel(self, provider_id: str, reason: str) -> bool:
        # POST, not DELETE. The v1 DELETE form went away with v1.
        httpjson.post(
            f"{BASE}/bookings/{provider_id}/cancel",
            headers=self._headers(VERSION_CANCEL_BOOKING),
            body={"cancellationReason": reason},
        )
        return True


register("booking", "calcom")(CalComBooking)
