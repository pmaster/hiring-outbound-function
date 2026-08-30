"""Findymail. LinkedIn URL to a verified work email.

Findymail only bills for addresses it verifies, which makes it a good first
step in the waterfall.
"""

from __future__ import annotations

from typing import Any

from ..config import secret
from ..httpjson import post
from ..util import norm_email
from . import register

BASE = "https://app.findymail.com/api"


class FindymailEnrich:
    name = "findymail"

    def __init__(self, settings: Any):
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {secret('FINDYMAIL_API_KEY', required=True)}",
            "Content-Type": "application/json",
        }

    def find_email(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        if candidate.get("linkedin_url"):
            data = post(
                f"{BASE}/search/linkedin",
                headers=self._headers(),
                body={"linkedin_url": candidate["linkedin_url"]},
            )
        elif candidate.get("full_name") and candidate.get("company_domain"):
            data = post(
                f"{BASE}/search/name",
                headers=self._headers(),
                body={"name": candidate["full_name"], "domain": candidate["company_domain"]},
            )
        else:
            return []
        contact = (data or {}).get("contact") or {}
        address = norm_email(contact.get("email") or "")
        if not address:
            return []
        return [{"address": address, "confidence": 0.9, "source": "findymail"}]


register("enrich", "findymail")(FindymailEnrich)
