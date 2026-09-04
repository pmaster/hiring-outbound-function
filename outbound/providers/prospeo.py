"""Prospeo person enrichment.

Endpoint and response fields checked against Prospeo's own API docs on
2026-09-04. A LinkedIn URL is enough to match a person. The fallback is a
name plus a company name or website.
"""

from __future__ import annotations

import json
from typing import Any

from .. import httpjson
from ..config import secret
from ..errors import ProviderError
from ..util import norm_email
from . import register

BASE = "https://api.prospeo.io"


class ProspeoEnrich:
    name = "prospeo"

    def __init__(self, settings: Any):
        self.settings = settings
        self.cfg = (
            (settings.get("providers.prospeo", {}) or {})
            if hasattr(settings, "get")
            else {}
        )

    def _headers(self) -> dict[str, str]:
        return {
            "X-KEY": secret("PROSPEO_API_KEY", required=True),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _match_data(candidate: dict[str, Any]) -> dict[str, str]:
        linkedin_url = str(candidate.get("linkedin_url") or "").strip()
        if linkedin_url:
            return {"linkedin_url": linkedin_url}

        full_name = str(candidate.get("full_name") or "").strip()
        company = str(candidate.get("company") or "").strip()
        company_domain = str(candidate.get("company_domain") or "").strip()
        if not full_name or not (company or company_domain):
            return {}

        out = {"full_name": full_name}
        if company:
            out["company_name"] = company
        if company_domain:
            out["company_website"] = company_domain
        return out

    def find_email(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        match_data = self._match_data(candidate)
        if not match_data:
            return []

        body = {
            # MillionVerifier remains the final gate. Keep this false so a
            # Prospeo match with no address is a clean miss, not a failed call.
            "only_verified_email": bool(self.cfg.get("only_verified_email", False)),
            "enrich_mobile": False,
            "data": match_data,
        }
        try:
            data = httpjson.post(
                f"{BASE}/enrich-person",
                headers=self._headers(),
                body=body,
            )
        except httpjson.HttpError as exc:
            # Prospeo uses HTTP 400 for a normal no-match result. Treat only
            # that code as a miss. Authentication, credit, and request errors
            # must stay visible.
            try:
                error = json.loads(exc.body or "{}")
            except json.JSONDecodeError:
                error = {}
            if exc.status == 400 and error.get("error_code") == "NO_MATCH":
                return []
            raise

        if not isinstance(data, dict):
            return []
        if data.get("error"):
            if data.get("error_code") == "NO_MATCH":
                return []
            raise ProviderError(
                f"Prospeo enrichment failed: {data.get('error_code') or 'unknown error'}"
            )

        person = data.get("person") or {}
        email = person.get("email") or {}
        if isinstance(email, str):
            raw_address = email
            status = ""
        else:
            raw_address = email.get("email") or ""
            status = str(email.get("status") or "").upper()

        address = norm_email(raw_address)
        if not address or "*" in address or "@" not in address:
            return []
        confidence = 0.95 if status == "VERIFIED" else 0.65
        return [{"address": address, "confidence": confidence, "source": "prospeo"}]


register("enrich", "prospeo")(ProspeoEnrich)
