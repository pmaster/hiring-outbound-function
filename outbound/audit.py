"""Check a role's list before committing to send it.

Everything here is cheap to fix now and expensive to fix after the first
hundred emails have gone out. It answers three questions:

1. Is the list big enough, and how long will it take to work through?
2. Is anything in it that should not be written to?
3. Is the ICP doing what someone meant it to do?
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .compliance import geo_allowed
from .config import Role, Settings
from .db import Database
from .pipeline import daily_cap, domain_cap, warmup_cap


@dataclass
class Note:
    level: str  # "block", "warn" or "info"
    text: str

    def __str__(self) -> str:
        mark = {"block": "BLOCK", "warn": "WARN ", "info": "     "}[self.level]
        return f"{mark} {self.text}"


@dataclass
class Audit:
    role_key: str
    notes: list[Note] = field(default_factory=list)

    def add(self, level: str, text: str) -> None:
        self.notes.append(Note(level, text))

    @property
    def blocking(self) -> list[Note]:
        return [n for n in self.notes if n.level == "block"]

    def __str__(self) -> str:
        head = f"Audit: {self.role_key}"
        body = "\n".join(f"  {n}" for n in self.notes)
        return f"{head}\n{body}"


def audit_role(db: Database, settings: Settings, role: Role) -> Audit:
    out = Audit(role_key=role.key)
    counts = db.funnel(role.key)
    total = sum(counts.values())
    live_pool = sum(
        counts.get(stage, 0)
        for stage in ("sourced", "scored", "review", "approved", "enriched",
                      "verified", "queued", "sent")
    )

    # --- size and pace -------------------------------------------------
    out.add("info", f"{total} people on the list, {live_pool} of them still in play.")
    if total == 0:
        out.add("block", "the list is empty. `outbound search` then `outbound import`.")
        return out
    if total < role.target_list_size:
        out.add(
            "warn",
            f"list is {total} of a target {role.target_list_size}. "
            f"Under-building the list is the most common way this fails.",
        )

    warm_cap, warm_note = warmup_cap(settings, db)
    per_day = min(daily_cap(settings, role), domain_cap(settings))
    if warm_cap >= 0:
        out.add("info", f"warm up is active: {warm_note}")
    sendable = sum(counts.get(s, 0) for s in ("verified", "queued"))
    if per_day > 0 and sendable:
        days = -(-sendable // per_day)
        out.add(
            "info",
            f"{sendable} ready to send at {per_day} a day is about "
            f"{days} working day(s), so roughly {days // 5 + 1} week(s).",
        )

    # --- things that should not be written to --------------------------
    rows = db.candidates(role.key, stages=["approved", "enriched", "verified", "queued"])
    no_note = [r for r in rows if not str(r.get("personal_note") or "").strip()]
    if no_note:
        out.add(
            "block",
            f"{len(no_note)} approved with no personal note. Step one will refuse "
            f"to render for them. Add notes in `outbound review`.",
        )

    bad_geo = [r for r in rows if not geo_allowed(settings, r.get("country"))[0]]
    if bad_geo:
        countries = sorted({str(r.get("country") or "unknown") for r in bad_geo})
        out.add(
            "block",
            f"{len(bad_geo)} approved in a country we do not send to "
            f"({', '.join(countries)}). They will be dropped at queue time.",
        )

    suppressed = 0
    dupes = 0
    for row in rows:
        email = db.primary_email(int(row["id"]))
        if email and db.is_suppressed("email", email["address"]):
            suppressed += 1
        if db.contacted_for_another_role(str(row.get("linkedin_key") or ""), role.key):
            dupes += 1
    if suppressed:
        out.add("warn", f"{suppressed} approved are on the suppression list and will be skipped.")
    if dupes:
        out.add(
            "warn",
            f"{dupes} approved have already been written to for another seat. "
            f"They will be stopped rather than emailed twice.",
        )

    no_address = [r for r in rows if r["stage"] == "approved" and not db.primary_email(int(r["id"]))]
    if no_address:
        out.add("info", f"{len(no_address)} approved still need an address. `outbound enrich {role.key}`.")

    # --- is the ICP doing what someone meant ---------------------------
    rejected = counts.get("rejected", 0)
    if total >= 20:
        share = rejected / total
        if share > 0.85:
            out.add(
                "warn",
                f"{share:.0%} of the list was rejected. Either the search is too "
                f"broad or a disqualifier is too aggressive. Check with "
                f"`outbound review {role.key} --json`.",
            )
        elif share < 0.15:
            out.add(
                "warn",
                f"only {share:.0%} was rejected. A filter that rejects almost "
                f"nothing is not filtering. Check the ICP.",
            )

    reasons: dict[str, int] = {}
    for row in db.candidates(role.key, stages=["rejected"], limit=500):
        try:
            detail = json.loads(row.get("score_json") or "{}")
        except json.JSONDecodeError:
            continue
        key = detail.get("disqualifier") or "below the score floor"
        reasons[key] = reasons.get(key, 0) + 1
    for key, count in sorted(reasons.items(), key=lambda kv: -kv[1])[:4]:
        out.add("info", f"rejected by {key}: {count}")

    thin = db.scalar(
        "SELECT COUNT(*) FROM candidates WHERE role_key = ? AND "
        "(profile_text IS NULL OR LENGTH(profile_text) < 120)",
        (role.key,),
    ) or 0
    if thin and total:
        share = thin / total
        if share > 0.3:
            out.add(
                "warn",
                f"{share:.0%} of profiles have almost no text. The regex signals "
                f"cannot fire on an empty profile, so those scores mean little. "
                f"Export a fuller profile from the source.",
            )
    return out
