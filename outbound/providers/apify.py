"""Apify. Runs an actor that returns LinkedIn profile data.

Endpoints verified against docs.apify.com on 2026-08-30. See
docs/VENDOR-APIS.md for the evidence.

ACCOUNT SAFETY. Some LinkedIn actors ask for your own LinkedIn session cookie.
Do not use those. LinkedIn restricts accounts for it and this operation cannot
afford to lose LinkedIn access. Set `cookie_actor_ok = true` only on purpose.

Configure in settings.toml:

    [providers.apify]
    actor            = "username/actor-name"   # a slash or a tilde, both fine
    max_charge_usd   = 25        # hard spend ceiling per run
    timeout_seconds  = 900       # actor run timeout
    poll_seconds     = 60        # long poll interval, 60 is the server maximum
    cookie_actor_ok  = false
    [providers.apify.input]      # merged into the actor input verbatim
    profileScraperMode = "Full"
"""

from __future__ import annotations

import time
from typing import Any

from .. import httpjson
from ..config import secret
from ..errors import ConfigError, ProviderError
from . import register

BASE = "https://api.apify.com/v2"
# From the docs: a run-sync call is cut off at 300 seconds with a 408. Any real
# sourcing run is longer than that, so this adapter always uses the async path.
SYNC_LIMIT_SECONDS = 300
TERMINAL = {"SUCCEEDED", "FAILED", "TIMED-OUT", "ABORTED"}


class ApifySearch:
    name = "apify"

    def __init__(self, settings: Any):
        self.settings = settings
        cfg = (settings.get("providers.apify", {}) or {}) if hasattr(settings, "get") else {}
        self.actor = str(cfg.get("actor") or "").strip()
        self.timeout = int(cfg.get("timeout_seconds", 900))
        self.poll_seconds = min(60, int(cfg.get("poll_seconds", 60)))
        self.max_charge_usd = cfg.get("max_charge_usd", 25)
        self.memory = cfg.get("memory")
        self.cookie_ok = bool(cfg.get("cookie_actor_ok", False))
        self.extra_input = dict(cfg.get("input") or {})
        if not self.actor:
            raise ConfigError(
                "providers.apify.actor is not set. Pick an actor from the Apify "
                "store that returns LinkedIn people search results without a "
                "session cookie, and put its id here. See docs/VENDORS.md."
            )
        if not self.cookie_ok and "cookie" in str(self.extra_input).lower():
            raise ConfigError(
                "the Apify actor input mentions a cookie. Actors that use your "
                "own LinkedIn session risk the account. Set "
                "providers.apify.cookie_actor_ok = true only on purpose."
            )

    def _headers(self) -> dict[str, str]:
        # The token also works as a query parameter, and the docs say not to:
        # URLs end up in browser history and server logs.
        return {
            "Authorization": f"Bearer {secret('APIFY_TOKEN', required=True)}",
            "Content-Type": "application/json",
        }

    def _actor_path(self) -> str:
        # The path wants `username~actor-name`. A hex actor id works too.
        return self.actor.replace("/", "~")

    def _build_input(self, spec: dict[str, Any], limit: int) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "searchQuery": spec.get("boolean") or " ".join(spec.get("titles", [])),
            "keywords": spec.get("boolean"),
            "currentJobTitles": list(spec.get("titles", [])),
            "locations": list(spec.get("geo", [])),
            "maxItems": limit,
            "maxResults": limit,
        }
        payload.update(self.extra_input)
        return payload

    def search(self, spec: dict[str, Any], limit: int, sleep=time.sleep) -> list[dict[str, Any]]:
        started = httpjson.post(
            f"{BASE}/actors/{self._actor_path()}/runs",
            headers=self._headers(),
            params={
                "maxItems": limit,
                "maxTotalChargeUsd": self.max_charge_usd,
                "timeout": self.timeout,
                "memory": self.memory,
            },
            body=self._build_input(spec, limit),
        )
        run = (started or {}).get("data") or {}
        run_id = run.get("id")
        if not run_id:
            raise ProviderError(f"apify did not return a run id: {started!r}")

        deadline = self.timeout + 120
        waited = 0
        status = str(run.get("status") or "READY")
        while status not in TERMINAL and waited < deadline:
            polled = httpjson.get(
                f"{BASE}/actor-runs/{run_id}",
                headers=self._headers(),
                params={"waitForFinish": self.poll_seconds},
            )
            run = (polled or {}).get("data") or {}
            status = str(run.get("status") or status)
            waited += self.poll_seconds
            if status not in TERMINAL:
                sleep(1)

        if status != "SUCCEEDED":
            raise ProviderError(
                f"apify run {run_id} ended as {status}. "
                f"{run.get('statusMessage') or ''}".strip()
            )

        rows: list[dict[str, Any]] = []
        offset = 0
        page = 1000
        while len(rows) < limit:
            # A bare JSON array, not wrapped in {"data": ...}.
            chunk = httpjson.get(
                f"{BASE}/actor-runs/{run_id}/dataset/items",
                headers=self._headers(),
                params={"format": "json", "clean": "true", "offset": offset, "limit": page},
            )
            if not isinstance(chunk, list) or not chunk:
                break
            rows.extend(r for r in chunk if isinstance(r, dict))
            offset += len(chunk)
            if len(chunk) < page:
                break
        for row in rows:
            row.setdefault("_search", spec.get("name"))
        return rows[:limit]

    def abort(self, run_id: str) -> None:
        """Kill switch for a runaway run."""
        httpjson.post(f"{BASE}/actor-runs/{run_id}/abort", headers=self._headers())


register("search", "apify")(ApifySearch)
