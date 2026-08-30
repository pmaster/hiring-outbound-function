"""Findymail. LinkedIn URL to a verified work email.

Endpoints verified against Findymail's OpenAPI spec on 2026-08-30.

The path is `/api/search/business-profile`, not `/api/search/linkedin`. The
first version of this adapter had the wrong one and would have 404'd on every
call.

Findymail charges one finder credit only when it finds a verified email, which
makes it a good first step in the waterfall.
"""

from __future__ import annotations

from typing import Any

from .. import httpjson
from ..config import secret
from ..util import norm_email
from . import register

BASE = "https://app.findymail.com"
# The business-profile endpoint is capped at 30 concurrent requests. Everything
# in this pipeline is sequential, so that is headroom rather than a constraint.
CONCURRENCY_LIMIT = 30


class FindymailEnrich:
    name = "findymail"

    def __init__(self, settings: Any):
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {secret('FINDYMAIL_API_KEY', required=True)}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def find_email(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        if candidate.get("linkedin_url"):
            data = httpjson.post(
                f"{BASE}/api/search/business-profile",
                headers=self._headers(),
                body={"linkedin_url": candidate["linkedin_url"]},
            )
        elif candidate.get("full_name") and (
            candidate.get("company_domain") or candidate.get("company")
        ):
            # The domain field takes a company name as a documented fallback.
            data = httpjson.post(
                f"{BASE}/api/search/name",
                headers=self._headers(),
                body={
                    "name": candidate["full_name"],
                    "domain": candidate.get("company_domain") or candidate["company"],
                },
            )
        else:
            return []

        if not isinstance(data, dict):
            return []
        # Sync returns {"contact": {...}}. With a webhook_url it returns
        # {"payload": {"contact": {...}}} instead, so read through both.
        contact = data.get("contact") or (data.get("payload") or {}).get("contact") or {}
        address = norm_email(contact.get("email") or "")
        if not address:
            return []
        # Findymail only bills for verified addresses, so a returned address is
        # already checked. The verify step will still see it as unknown.
        return [{"address": address, "confidence": 0.92, "source": "findymail"}]

    def credits(self) -> dict[str, Any]:
        return httpjson.get(f"{BASE}/api/credits", headers=self._headers()) or {}


register("enrich", "findymail")(FindymailEnrich)
