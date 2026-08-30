"""ZeroBounce. Single address verification.

Verified against api.zerobounce.net on 2026-08-30. The research pass rated
this the best fit of the three verifiers for this pipeline's shape.

Regional endpoints exist for data residency (api-us, api-eu) with identical
paths. Set `region` if you need one.

    [providers.zerobounce]
    region = ""        # "", "us" or "eu"
"""

from __future__ import annotations

from typing import Any

from .. import httpjson
from ..config import secret
from . import register

RESULT_MAP = {
    "valid": "valid",
    "invalid": "invalid",
    "catch-all": "catch_all",
    "catch_all": "catch_all",
    "unknown": "unknown",
    "spamtrap": "invalid",
    "abuse": "invalid",
    "do_not_mail": "invalid",
}


class ZeroBounceVerify:
    name = "zerobounce"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.zerobounce", {}) or {}) if hasattr(settings, "get") else {}
        region = str(cfg.get("region") or "").strip().lower()
        host = f"api-{region}.zerobounce.net" if region in ("us", "eu") else "api.zerobounce.net"
        self.base = f"https://{host}/v2"

    def verify(self, address: str) -> str:
        data = httpjson.get(
            f"{self.base}/validate",
            params={
                "api_key": secret("ZEROBOUNCE_API_KEY", required=True),
                "email": address,
                "ip_address": "",
            },
        )
        if not isinstance(data, dict):
            return "unknown"
        return RESULT_MAP.get(str(data.get("status") or "").lower(), "unknown")

    def credits(self) -> Any:
        return httpjson.get(
            f"{self.base}/getcredits",
            params={"api_key": secret("ZEROBOUNCE_API_KEY", required=True)},
        )


register("verify", "zerobounce")(ZeroBounceVerify)
