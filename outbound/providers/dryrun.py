"""The offline provider. Implements every stage with deterministic fake data.

This exists so the pipeline is testable and demonstrable without a single API
key, and so a mistake in configuration shows up as a wrong local result rather
than as an email to a real person.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ..config import REPO_ROOT
from ..util import iso, name_parts, norm_email, now
from . import register

SAMPLE_PROFILES = REPO_ROOT / "sample" / "profiles.jsonl"


def _stable_float(seed: str) -> float:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


class DryRunSearch:
    name = "dryrun"

    def __init__(self, settings: Any = None):
        self.settings = settings

    def search(self, spec: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        if not SAMPLE_PROFILES.exists():
            return []
        rows: list[dict[str, Any]] = []
        wanted = str(spec.get("name") or "")
        for line in SAMPLE_PROFILES.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            row = json.loads(line)
            if wanted and row.get("_search") and row["_search"] != wanted:
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
        return rows


class DryRunEnrich:
    name = "dryrun"

    def __init__(self, settings: Any = None):
        self.settings = settings

    def find_email(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        first, last = name_parts(candidate.get("full_name"))
        if not first:
            return []
        domain = (candidate.get("company_domain") or "").strip().lower()
        if not domain:
            company = (candidate.get("company") or "example").lower()
            slug = "".join(ch for ch in company if ch.isalnum()) or "example"
            domain = f"{slug}.example"
        seed = f"{first}{last}{domain}"
        # Deterministic miss rate, so a dry run shows the enrichment gap too.
        if _stable_float(seed) < 0.18:
            return []
        address = norm_email(f"{first}.{last}@{domain}" if last else f"{first}@{domain}")
        return [{"address": address, "confidence": round(0.6 + 0.35 * _stable_float(seed + "c"), 2), "source": "dryrun"}]


class DryRunVerify:
    name = "dryrun"

    def __init__(self, settings: Any = None):
        self.settings = settings

    def verify(self, address: str) -> str:
        value = _stable_float("verify:" + norm_email(address))
        if value < 0.08:
            return "invalid"
        if value < 0.16:
            return "risky"
        if value < 0.22:
            return "catch_all"
        return "valid"


class DryRunSend:
    name = "dryrun"

    def __init__(self, settings: Any = None):
        self.settings = settings
        self.outbox = Path(getattr(settings, "outbox_dir", REPO_ROOT / "data/outbox"))

    def send(self, message: dict[str, Any]) -> str:
        """Writes the email to the outbox instead of sending it."""
        self.outbox.mkdir(parents=True, exist_ok=True)
        stamp = now().strftime("%Y%m%dT%H%M%S")
        safe = norm_email(message.get("to", "unknown")).replace("@", "_at_")
        path = self.outbox / f"{stamp}-{message.get('step', 0)}-{safe}.eml"
        path.write_text(
            f"To: {message.get('to')}\n"
            f"From: {message.get('from')}\n"
            f"Reply-To: {message.get('reply_to')}\n"
            f"Subject: {message.get('subject')}\n"
            f"X-Outbound-Role: {message.get('role_key')}\n"
            f"X-Outbound-Step: {message.get('step')}\n"
            f"Date: {iso()}\n\n"
            f"{message.get('body')}\n",
            encoding="utf-8",
        )
        return f"dryrun:{path.name}"


class DryRunBooking:
    name = "dryrun"

    def __init__(self, settings: Any = None):
        self.settings = settings

    def list_bookings(self, since: str | None = None) -> list[dict[str, Any]]:
        path = REPO_ROOT / "sample" / "bookings.jsonl"
        if not path.exists():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(json.loads(line))
        return out

    def cancel(self, provider_id: str, reason: str) -> bool:
        return True


register("search", "dryrun")(DryRunSearch)
register("enrich", "dryrun")(DryRunEnrich)
register("verify", "dryrun")(DryRunVerify)
register("send", "dryrun")(DryRunSend)
register("booking", "dryrun")(DryRunBooking)
