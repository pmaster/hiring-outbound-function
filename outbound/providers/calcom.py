"""Cal.com. Read bookings and cancel them.

    [providers.calcom]
    api_version = "2024-08-13"
    event_type_id = 0            # optional filter
"""

from __future__ import annotations

from typing import Any

from ..config import secret
from ..httpjson import get, post
from ..util import norm_email
from . import register

BASE = "https://api.cal.com/v2"
DEFAULT_API_VERSION = "2024-08-13"


class CalComBooking:
    name = "calcom"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.calcom", {}) or {}) if hasattr(settings, "get") else {}
        self.api_version = str(cfg.get("api_version") or DEFAULT_API_VERSION)
        self.event_type_id = cfg.get("event_type_id")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {secret('CALCOM_API_KEY', required=True)}",
            "cal-api-version": self.api_version,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _attendee(booking: dict[str, Any]) -> tuple[str, str]:
        attendees = booking.get("attendees") or []
        if attendees and isinstance(attendees[0], dict):
            return str(attendees[0].get("name") or ""), norm_email(attendees[0].get("email") or "")
        return str(booking.get("title") or ""), ""

    def list_bookings(self, since: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"status": "upcoming", "take": 100}
        if self.event_type_id:
            params["eventTypeId"] = self.event_type_id
        if since:
            params["afterStart"] = since
        data = get(f"{BASE}/bookings", headers=self._headers(), params=params)
        rows = (data or {}).get("data") if isinstance(data, dict) else data
        if isinstance(rows, dict):
            rows = rows.get("bookings") or []
        out: list[dict[str, Any]] = []
        for booking in rows or []:
            if not isinstance(booking, dict):
                continue
            name, email = self._attendee(booking)
            answers = {}
            responses = booking.get("bookingFieldsResponses") or booking.get("responses") or {}
            if isinstance(responses, dict):
                for key, value in responses.items():
                    if key in ("name", "email", "guests", "location", "attendeePhoneNumber"):
                        continue
                    answers[key] = value if isinstance(value, str) else str(value)
            out.append(
                {
                    "provider_id": str(booking.get("uid") or booking.get("id") or ""),
                    "attendee_name": name,
                    "attendee_email": email,
                    "start_at": booking.get("start") or booking.get("startTime"),
                    "end_at": booking.get("end") or booking.get("endTime"),
                    "answers": answers,
                }
            )
        return out

    def cancel(self, provider_id: str, reason: str) -> bool:
        post(
            f"{BASE}/bookings/{provider_id}/cancel",
            headers=self._headers(),
            body={"cancellationReason": reason},
        )
        return True


register("booking", "calcom")(CalComBooking)
