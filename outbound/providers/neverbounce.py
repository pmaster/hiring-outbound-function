"""NeverBounce. Single address verification."""

from __future__ import annotations

from typing import Any

from ..config import secret
from .. import httpjson
from . import register

BASE = "https://api.neverbounce.com/v4"

RESULT_MAP = {
    "valid": "valid",
    "invalid": "invalid",
    "disposable": "invalid",
    "catchall": "catch_all",
    "accept_all": "catch_all",
    "unknown": "unknown",
}


class NeverBounceVerify:
    name = "neverbounce"

    def __init__(self, settings: Any):
        self.settings = settings

    def verify(self, address: str) -> str:
        data = httpjson.get(
            f"{BASE}/single/check",
            params={
                "key": secret("NEVERBOUNCE_API_KEY", required=True),
                "email": address,
                "address_info": 0,
                "credits_info": 0,
                "timeout": 20,
            },
        )
        if not isinstance(data, dict):
            return "unknown"
        return RESULT_MAP.get(str(data.get("result") or "").lower(), "unknown")


register("verify", "neverbounce")(NeverBounceVerify)
