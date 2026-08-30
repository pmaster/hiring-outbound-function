"""Instantly. Cold email sequencer, API v2.

Endpoints verified against Instantly's OpenAPI spec on 2026-08-30.

READ THIS BEFORE USING IT. Instantly sends the copy that lives in the
Instantly campaign, not the copy this repo renders. If the campaign has its
own body text, that is what your candidates receive, and everything in
`templates/` is ignored. Nothing errors; the wrong email just goes out.

So the campaign body must be a passthrough. Set the campaign's email body to
exactly:

    {{outbound_body}}

and the subject line to:

    {{outbound_subject}}

This adapter pushes both as custom variables on the lead. On the first send it
reads the campaign back and refuses if the body is not a passthrough, because
finding that out from a candidate is expensive.

Configure:

    [providers.instantly]
    campaign_id      = "..."     # one campaign per role is cleanest
    verify_campaign  = true      # check the passthrough before the first send
    [providers.instantly.campaign_by_role]
    head-of-operations = "..."
    engineer = "..."
"""

from __future__ import annotations

import json
from typing import Any

from .. import httpjson
from ..config import secret
from ..errors import ConfigError, ProviderError
from . import register

BASE = "https://api.instantly.ai/api/v2"

# The variables the campaign body must reference for our copy to be the copy
# that is actually sent.
BODY_VARIABLE = "{{outbound_body}}"
SUBJECT_VARIABLE = "{{outbound_subject}}"


class InstantlySend:
    name = "instantly"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.instantly", {}) or {}) if hasattr(settings, "get") else {}
        self.default_campaign = str(cfg.get("campaign_id") or "")
        self.by_role = dict(cfg.get("campaign_by_role") or {})
        self.verify_campaign = bool(cfg.get("verify_campaign", True))
        self._checked: set[str] = set()
        if not self.default_campaign and not self.by_role:
            raise ConfigError(
                "providers.instantly needs campaign_id, or a campaign_by_role table."
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {secret('INSTANTLY_API_KEY', required=True)}",
            "Content-Type": "application/json",
        }

    def _campaign(self, role_key: str) -> str:
        campaign = self.by_role.get(role_key) or self.default_campaign
        if not campaign:
            raise ConfigError(f"no Instantly campaign configured for role {role_key!r}")
        return str(campaign)

    def _assert_passthrough(self, campaign_id: str) -> None:
        """Refuse to send if the campaign would send its own copy, not ours."""
        if not self.verify_campaign or campaign_id in self._checked:
            return
        self._checked.add(campaign_id)
        data = httpjson.get(f"{BASE}/campaigns/{campaign_id}", headers=self._headers())
        if not isinstance(data, dict):
            return
        text = json.dumps(data.get("sequences") or data.get("sequence") or [])
        if not text or text in ("[]", "null"):
            return  # nothing to check against; let the send proceed
        if BODY_VARIABLE not in text:
            raise ProviderError(
                f"Instantly campaign {campaign_id} does not use {BODY_VARIABLE} in its "
                f"body, so it would send its own copy and ignore everything in "
                f"templates/. Set the campaign body to exactly {BODY_VARIABLE} and the "
                f"subject to {SUBJECT_VARIABLE}, or set "
                f"providers.instantly.verify_campaign = false if you meant it."
            )

    def send(self, message: dict[str, Any]) -> str:
        campaign_id = self._campaign(str(message.get("role_key") or ""))
        self._assert_passthrough(campaign_id)
        body = {
            "campaign": campaign_id,
            "email": message["to"],
            "personalization": message["body"],
            "custom_variables": {
                "outbound_subject": message["subject"],
                "outbound_body": message["body"],
                "outbound_step": message.get("step"),
                "outbound_role": message.get("role_key"),
                "outbound_variant": message.get("variant", "a"),
            },
        }
        data = httpjson.post(f"{BASE}/leads", headers=self._headers(), body=body)
        if isinstance(data, dict):
            return str(data.get("id") or data.get("lead_id") or "instantly:queued")
        return "instantly:queued"


class InstantlyReplies:
    """Read inbound mail from the Instantly Unibox.

    Verified endpoint: GET /api/v2/emails. Use this instead of IMAP when
    Instantly owns the mailboxes, because that is where the replies land.
    """

    name = "instantly"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.instantly", {}) or {}) if hasattr(settings, "get") else {}
        self.default_campaign = str(cfg.get("campaign_id") or "")
        self.by_role = dict(cfg.get("campaign_by_role") or {})

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {secret('INSTANTLY_API_KEY', required=True)}",
            "Content-Type": "application/json",
        }

    def fetch_replies(self, since: str | None = None) -> list[dict[str, Any]]:
        campaigns = [c for c in ({self.default_campaign} | set(self.by_role.values())) if c]
        out: list[dict[str, Any]] = []
        for campaign in campaigns or [None]:
            params: dict[str, Any] = {"limit": 100, "email_type": "received"}
            if campaign:
                params["campaign_id"] = campaign
            if since:
                params["start_date"] = since
            starting_after = None
            for _page in range(20):
                if starting_after:
                    params["starting_after"] = starting_after
                data = httpjson.get(f"{BASE}/emails", headers=self._headers(), params=params)
                if not isinstance(data, dict):
                    break
                items = data.get("items") or data.get("data") or []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    out.append({
                        "from_address": (
                            item.get("from_address_email")
                            or item.get("from_address")
                            or item.get("lead")
                            or ""
                        ),
                        "subject": item.get("subject") or "",
                        "body": item.get("body_text")
                                or (item.get("body") or {}).get("text")
                                or item.get("content_preview") or "",
                        "date": item.get("timestamp_created") or item.get("date") or "",
                    })
                starting_after = data.get("next_starting_after")
                if not starting_after or not items:
                    break
        return out


register("send", "instantly")(InstantlySend)
register("replies", "instantly")(InstantlyReplies)
