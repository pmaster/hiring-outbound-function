"""Instantly. Cold email sequencer, API v2.

Instantly owns the sending, the warm up and the reply detection. This adapter
pushes a lead with the rendered copy as custom variables; the campaign in
Instantly holds the sequence that references them.

Configure:

    [providers.instantly]
    campaign_id = "..."          # one campaign per role is cleanest
    [providers.instantly.campaign_by_role]
    head-of-operations = "..."
    engineer = "..."
"""

from __future__ import annotations

from typing import Any

from ..config import secret
from ..errors import ConfigError
from .. import httpjson
from . import register

BASE = "https://api.instantly.ai/api/v2"


class InstantlySend:
    name = "instantly"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.instantly", {}) or {}) if hasattr(settings, "get") else {}
        self.default_campaign = str(cfg.get("campaign_id") or "")
        self.by_role = dict(cfg.get("campaign_by_role") or {})
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

    def send(self, message: dict[str, Any]) -> str:
        body = {
            "campaign": self._campaign(str(message.get("role_key") or "")),
            "email": message["to"],
            "personalization": message["body"],
            "custom_variables": {
                "outbound_subject": message["subject"],
                "outbound_body": message["body"],
                "outbound_step": message.get("step"),
                "outbound_role": message.get("role_key"),
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
