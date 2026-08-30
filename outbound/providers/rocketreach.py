"""RocketReach. LinkedIn URL to work email.

Endpoints verified against RocketReach's API reference on 2026-08-30.

A lookup often comes back before the search behind it has finished. The
terminal states are "complete" and "failed"; everything else means keep
waiting. Poll with `/person/checkStatus`, not by repeating the lookup, because
repeating the lookup can bill again.
"""

from __future__ import annotations

import time
from typing import Any

from .. import httpjson
from ..config import secret
from ..util import norm_email
from . import register

BASE = "https://api.rocketreach.co/api/v2"
# The docs disagree with themselves across two pages, so take the union.
TERMINAL_OK = {"complete"}
TERMINAL_BAD = {"failed"}
IN_FLIGHT = {"progress", "searching", "waiting", "not queued", "queued"}

GRADE_CONFIDENCE = {"A": 0.95, "B": 0.85, "C": 0.7, "D": 0.5, "F": 0.3}


class RocketReachEnrich:
    name = "rocketreach"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.rocketreach", {}) or {}) if hasattr(settings, "get") else {}
        self.max_polls = int(cfg.get("max_polls", 6))
        self.poll_seconds = float(cfg.get("poll_seconds", 5))

    def _headers(self) -> dict[str, str]:
        return {"Api-Key": secret("ROCKETREACH_API_KEY", required=True)}

    @staticmethod
    def _addresses(profile: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for entry in profile.get("emails") or []:
            if isinstance(entry, dict):
                address = norm_email(entry.get("email"))
                kind = str(entry.get("type") or "").lower()
                grade = str(entry.get("grade") or "").upper()
            else:
                address, kind, grade = norm_email(entry), "", ""
            if not address or kind == "personal":
                continue  # work addresses only
            out.append({
                "address": address,
                "confidence": GRADE_CONFIDENCE.get(grade, 0.6),
                "source": "rocketreach",
            })
        out.sort(key=lambda e: -e["confidence"])
        return out

    def find_email(self, candidate: dict[str, Any], sleep=time.sleep) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"return_cached_emails": "true"}
        if candidate.get("linkedin_url"):
            params["linkedin_url"] = candidate["linkedin_url"]
        elif candidate.get("full_name") and candidate.get("company"):
            # Both are required together for the fuzzy fallback.
            params["name"] = candidate["full_name"]
            params["current_employer"] = candidate["company"]
        else:
            return []

        profile = httpjson.get(f"{BASE}/person/lookup", headers=self._headers(), params=params)
        if not isinstance(profile, dict):
            return []

        status = str(profile.get("status") or "complete").lower()
        person_id = profile.get("id")
        polls = 0
        while status in IN_FLIGHT and person_id and polls < self.max_polls:
            sleep(self.poll_seconds)
            polls += 1
            checked = httpjson.get(
                f"{BASE}/person/checkStatus",
                headers=self._headers(),
                params={"ids": person_id},
            )
            # checkStatus returns an ARRAY of profiles.
            if isinstance(checked, list) and checked:
                profile = checked[0]
            elif isinstance(checked, dict):
                profile = checked
            else:
                break
            status = str(profile.get("status") or status).lower()

        if status in TERMINAL_BAD:
            return []
        return self._addresses(profile)

    def account(self) -> dict[str, Any]:
        return httpjson.get(f"{BASE}/account/", headers=self._headers()) or {}


register("enrich", "rocketreach")(RocketReachEnrich)
