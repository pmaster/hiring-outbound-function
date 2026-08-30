"""Apify. Runs a public actor that returns LinkedIn profile data.

ACCOUNT SAFETY. Some LinkedIn actors ask you to paste your own LinkedIn
session cookie. Do not use those. LinkedIn restricts accounts for it and this
operation cannot afford to lose LinkedIn access. Set `cookie_actor_ok = true`
in the provider config only if you have decided otherwise on purpose.

Configure in settings.toml:

    [providers.apify]
    actor = "apify/linkedin-profile-scraper"   # actor id or username/name
    cookie_actor_ok = false
    timeout_seconds = 300
"""

from __future__ import annotations

from typing import Any

from ..config import secret
from ..errors import ConfigError, ProviderError
from .. import httpjson
from . import register

BASE = "https://api.apify.com/v2"


class ApifySearch:
    name = "apify"

    def __init__(self, settings: Any):
        self.settings = settings
        self.token = secret("APIFY_TOKEN", required=True)
        cfg = (settings.get("providers.apify", {}) or {}) if hasattr(settings, "get") else {}
        self.actor = str(cfg.get("actor") or "").strip()
        self.timeout = int(cfg.get("timeout_seconds", 300))
        self.cookie_ok = bool(cfg.get("cookie_actor_ok", False))
        self.extra_input = dict(cfg.get("input") or {})
        if not self.actor:
            raise ConfigError(
                "providers.apify.actor is not set. Pick an actor from the Apify "
                "store that returns LinkedIn people search results, and put its "
                "id here. See docs/VENDORS.md."
            )
        if not self.cookie_ok and "cookie" in str(self.extra_input).lower():
            raise ConfigError(
                "the Apify actor input mentions a cookie. Actors that use your "
                "own LinkedIn session risk the account. Set "
                "providers.apify.cookie_actor_ok = true only on purpose."
            )

    def _actor_path(self) -> str:
        # Apify accepts either an actor id or `username~actor-name` in the path.
        return self.actor.replace("/", "~")

    def search(self, spec: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "searchQuery": spec.get("boolean") or " ".join(spec.get("titles", [])),
            "keywords": spec.get("boolean"),
            "location": ", ".join(spec.get("geo", [])),
            "maxItems": limit,
            "maxResults": limit,
        }
        payload.update(self.extra_input)
        url = f"{BASE}/acts/{self._actor_path()}/run-sync-get-dataset-items"
        data = httpjson.post(
            url,
            params={"token": self.token, "timeout": self.timeout, "limit": limit},
            body=payload,
            timeout=self.timeout + 30,
        )
        if isinstance(data, dict):
            for key in ("items", "results", "data"):
                if isinstance(data.get(key), list):
                    data = data[key]
                    break
        if not isinstance(data, list):
            raise ProviderError(f"apify returned {type(data).__name__}, expected a list")
        for row in data:
            if isinstance(row, dict):
                row.setdefault("_search", spec.get("name"))
        return [row for row in data if isinstance(row, dict)][:limit]


register("search", "apify")(ApifySearch)
