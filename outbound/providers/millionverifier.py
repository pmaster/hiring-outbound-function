"""MillionVerifier. Single address verification."""

from __future__ import annotations

from typing import Any

from ..config import secret
from ..httpjson import get
from . import register

BASE = "https://api.millionverifier.com/api/v3/"

RESULT_MAP = {
    "ok": "valid",
    "good": "valid",
    "catch_all": "catch_all",
    "catchall": "catch_all",
    "unknown": "unknown",
    "invalid": "invalid",
    "bad": "invalid",
    "disposable": "invalid",
    "error": "unknown",
}


class MillionVerifierVerify:
    name = "millionverifier"

    def __init__(self, settings: Any):
        self.settings = settings

    def verify(self, address: str) -> str:
        data = get(
            BASE,
            params={
                "api": secret("MILLIONVERIFIER_API_KEY", required=True),
                "email": address,
                "timeout": 20,
            },
        )
        if not isinstance(data, dict):
            return "unknown"
        raw = str(data.get("result") or data.get("resultcode") or "").lower()
        return RESULT_MAP.get(raw, "unknown")


register("verify", "millionverifier")(MillionVerifierVerify)
