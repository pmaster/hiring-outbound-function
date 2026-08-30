"""NeverBounce. Single address verification.

Verified against api.neverbounce.com on 2026-08-30. The current version is
v4.2, not v4.

VOLUME WARNING. NeverBounce's own terms say the single-check endpoint is not
for bulk verification; lists go through the jobs API. At this pipeline's volume
(a few hundred addresses per role, checked one at a time as people are
approved) single checks are the intended use. If you ever verify a whole list
at once, use the jobs API or a different vendor.
"""

from __future__ import annotations

from typing import Any

from .. import httpjson
from ..config import secret
from . import register

BASE = "https://api.neverbounce.com/v4.2"

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
        if str(data.get("status") or "success") != "success":
            return "unknown"
        return RESULT_MAP.get(str(data.get("result") or "").lower(), "unknown")

    def credits(self) -> Any:
        return httpjson.get(
            f"{BASE}/account/info",
            params={"key": secret("NEVERBOUNCE_API_KEY", required=True)},
        )


register("verify", "neverbounce")(NeverBounceVerify)
