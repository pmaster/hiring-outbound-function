"""Calendly. Read scheduled events and their invitee answers, and cancel.

    [providers.calendly]
    organization = "https://api.calendly.com/organizations/XXXX"
    user         = "https://api.calendly.com/users/XXXX"
"""

from __future__ import annotations

from typing import Any

from ..config import secret
from ..errors import ConfigError
from .. import httpjson
from ..util import norm_email
from . import register

BASE = "https://api.calendly.com"


class CalendlyBooking:
    name = "calendly"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.calendly", {}) or {}) if hasattr(settings, "get") else {}
        self.organization = str(cfg.get("organization") or "")
        self.user = str(cfg.get("user") or "")
        if not self.organization and not self.user:
            raise ConfigError(
                "providers.calendly needs an organization or user URI. "
                "Get it from GET https://api.calendly.com/users/me."
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {secret('CALENDLY_TOKEN', required=True)}",
            "Content-Type": "application/json",
        }

    def list_bookings(self, since: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"status": "active", "count": 100}
        if self.organization:
            params["organization"] = self.organization
        if self.user:
            params["user"] = self.user
        if since:
            params["min_start_time"] = since
        data = httpjson.get(f"{BASE}/scheduled_events", headers=self._headers(), params=params)
        out: list[dict[str, Any]] = []
        for event in (data or {}).get("collection", []):
            uri = str(event.get("uri") or "")
            uuid = uri.rstrip("/").split("/")[-1]
            invitees = httpjson.get(
                f"{BASE}/scheduled_events/{uuid}/invitees",
                headers=self._headers(),
                params={"count": 10},
            )
            for invitee in (invitees or {}).get("collection", []):
                answers = {
                    str(q.get("question")): str(q.get("answer"))
                    for q in invitee.get("questions_and_answers", [])
                    if isinstance(q, dict)
                }
                out.append(
                    {
                        "provider_id": uuid,
                        "attendee_name": invitee.get("name"),
                        "attendee_email": norm_email(invitee.get("email") or ""),
                        "start_at": event.get("start_time"),
                        "end_at": event.get("end_time"),
                        "answers": answers,
                    }
                )
        return out

    def cancel(self, provider_id: str, reason: str) -> bool:
        httpjson.post(
            f"{BASE}/scheduled_events/{provider_id}/cancellation",
            headers=self._headers(),
            body={"reason": reason},
        )
        return True


register("booking", "calendly")(CalendlyBooking)
