"""RocketReach. LinkedIn URL to work email."""

from __future__ import annotations

import time
from typing import Any

from ..config import secret
from .. import httpjson
from ..util import norm_email
from . import register

BASE = "https://api.rocketreach.co/api/v2"


class RocketReachEnrich:
    name = "rocketreach"

    def __init__(self, settings: Any):
        self.settings = settings
        self.max_polls = 6

    def _headers(self) -> dict[str, str]:
        return {"Api-Key": secret("ROCKETREACH_API_KEY", required=True)}

    def find_email(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if candidate.get("linkedin_url"):
            params["li_url"] = candidate["linkedin_url"]
        else:
            params["name"] = candidate.get("full_name")
            params["current_employer"] = candidate.get("company")
        data = httpjson.get(f"{BASE}/person/lookup", headers=self._headers(), params=params)

        # A lookup can come back still searching. Poll a few times, then give up.
        polls = 0
        while isinstance(data, dict) and data.get("status") == "searching" and polls < self.max_polls:
            time.sleep(3)
            polls += 1
            person_id = data.get("id")
            if not person_id:
                break
            data = httpjson.get(f"{BASE}/person/lookup", headers=self._headers(), params={"id": person_id})

        if not isinstance(data, dict):
            return []
        out: list[dict[str, Any]] = []
        for entry in data.get("emails") or []:
            address = norm_email(entry.get("email") if isinstance(entry, dict) else entry)
            if not address:
                continue
            grade = str((entry or {}).get("grade") or "").upper() if isinstance(entry, dict) else ""
            kind = str((entry or {}).get("type") or "").lower() if isinstance(entry, dict) else ""
            if kind == "personal":
                continue  # work addresses only
            confidence = {"A": 0.95, "B": 0.85, "C": 0.7, "D": 0.5, "F": 0.3}.get(grade, 0.6)
            out.append({"address": address, "confidence": confidence, "source": "rocketreach"})
        out.sort(key=lambda e: -e["confidence"])
        return out


register("enrich", "rocketreach")(RocketReachEnrich)
