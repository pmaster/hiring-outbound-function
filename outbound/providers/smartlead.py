"""Smartlead. Cold email sequencer.

Same shape as the Instantly adapter: push the lead into a campaign that holds
the sequence.

    [providers.smartlead]
    campaign_id = "12345"
    [providers.smartlead.campaign_by_role]
    engineer = "12346"
"""

from __future__ import annotations

from typing import Any

from ..config import secret
from ..errors import ConfigError
from ..httpjson import post
from . import register

BASE = "https://server.smartlead.ai/api/v1"


class SmartleadSend:
    name = "smartlead"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.smartlead", {}) or {}) if hasattr(settings, "get") else {}
        self.default_campaign = str(cfg.get("campaign_id") or "")
        self.by_role = dict(cfg.get("campaign_by_role") or {})
        if not self.default_campaign and not self.by_role:
            raise ConfigError(
                "providers.smartlead needs campaign_id, or a campaign_by_role table."
            )

    def _campaign(self, role_key: str) -> str:
        campaign = self.by_role.get(role_key) or self.default_campaign
        if not campaign:
            raise ConfigError(f"no Smartlead campaign configured for role {role_key!r}")
        return str(campaign)

    def send(self, message: dict[str, Any]) -> str:
        campaign = self._campaign(str(message.get("role_key") or ""))
        first, _, last = str(message.get("to", "")).split("@")[0].partition(".")
        body = {
            "lead_list": [
                {
                    "email": message["to"],
                    "first_name": first,
                    "last_name": last,
                    "custom_fields": {
                        "outbound_subject": message["subject"],
                        "outbound_body": message["body"],
                        "outbound_step": str(message.get("step")),
                    },
                }
            ],
            "settings": {"ignore_global_block_list": False, "ignore_duplicate_leads_in_other_campaign": False},
        }
        data = post(
            f"{BASE}/campaigns/{campaign}/leads",
            params={"api_key": secret("SMARTLEAD_API_KEY", required=True)},
            body=body,
        )
        if isinstance(data, dict):
            return str(data.get("id") or "smartlead:queued")
        return "smartlead:queued"


register("send", "smartlead")(SmartleadSend)
