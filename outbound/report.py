"""What the funnel is doing, and what to do next."""

from __future__ import annotations

from typing import Any

from .config import Role, Settings
from .db import STAGES, Database
from .pipeline import bounce_guard, domain_cap, sending_day, warmup_cap
from .util import now


def _rate(top: int, bottom: int) -> str:
    return f"{100.0 * top / bottom:.1f}%" if bottom else "n/a"


def funnel_table(db: Database, role_key: str | None = None) -> str:
    counts = db.funnel(role_key)
    total = sum(counts.values())
    lines = [f"{'stage':14} {'n':>6}  {'of all':>7}"]
    lines.append("-" * 31)
    for stage in STAGES:
        n = counts.get(stage, 0)
        if not n:
            continue
        lines.append(f"{stage:14} {n:6d}  {_rate(n, total):>7}")
    lines.append("-" * 31)
    lines.append(f"{'total':14} {total:6d}")
    return "\n".join(lines)


def conversions(db: Database, role_key: str | None = None) -> str:
    where = "WHERE role_key = ?" if role_key else ""
    params = (role_key,) if role_key else ()
    sourced = db.scalar(f"SELECT COUNT(*) FROM candidates {where}", params) or 0
    approved = db.scalar(
        f"SELECT COUNT(*) FROM candidates {where}{' AND' if where else 'WHERE'} "
        f"review_state = 'approved'",
        params,
    ) or 0
    with_email = db.scalar(
        "SELECT COUNT(DISTINCT c.id) FROM candidates c JOIN emails e ON e.candidate_id = c.id"
        + (" WHERE c.role_key = ?" if role_key else ""),
        params,
    ) or 0
    sent = db.scalar(
        "SELECT COUNT(DISTINCT candidate_id) FROM messages WHERE status = 'sent'"
        + (" AND role_key = ?" if role_key else ""),
        params,
    ) or 0
    replied = db.scalar(
        f"SELECT COUNT(*) FROM candidates {where}{' AND' if where else 'WHERE'} "
        f"stage IN ('replied','booked','confirmed','screened','hired')",
        params,
    ) or 0
    booked = db.scalar(
        f"SELECT COUNT(*) FROM candidates {where}{' AND' if where else 'WHERE'} "
        f"stage IN ('booked','confirmed','screened','hired')",
        params,
    ) or 0

    rows = [
        ("sourced", sourced, ""),
        ("approved by hand", approved, _rate(approved, sourced) + " of sourced"),
        ("has an address", with_email, _rate(with_email, approved) + " of approved"),
        ("written to", sent, _rate(sent, with_email) + " of addressable"),
        ("replied", replied, _rate(replied, sent) + " of written to"),
        ("booked", booked, _rate(booked, sent) + " of written to"),
    ]
    width = max(len(r[0]) for r in rows)
    lines = [f"{label:<{width}}  {value:>6}  {note}" for label, value, note in rows]
    lines.append("")
    lines.append(
        "The SOP's expectation on a hand built founder sent list: 8 to 15% reply, "
        "3 to 6% positive, 5 to 12 real conversations per 300 people."
    )
    return "\n".join(lines)


def variants(
    db: Database, settings: Settings, roles: dict[str, Role], role_key: str | None = None
) -> str:
    """Reply and booking rate per copy variant, for the first email.

    Only shown when a role actually has two versions. A split with almost no
    sends means nothing, so the read is labelled until there is enough of it.
    """
    from .compose import variants_available

    lines: list[str] = []
    for key, role in sorted(roles.items()):
        if role_key and key != role_key:
            continue
        if len(variants_available(role, 1)) < 2:
            continue
        rows = [r for r in db.variant_stats(key, step=1) if int(r["sent"] or 0)]
        if not rows:
            continue
        lines.append(f"{role.title} ({key}), first email:")
        for row in rows:
            sent = int(row["sent"] or 0)
            replied = int(row["replied"] or 0)
            booked = int(row["booked"] or 0)
            enough = "" if sent >= 50 else "   too few to read yet"
            lines.append(
                f"  {row['variant']}: {sent:4d} sent, {replied:3d} replied "
                f"({_rate(replied, sent)}), {booked:3d} booked "
                f"({_rate(booked, sent)}){enough}"
            )
        lines.append("")
    if lines:
        lines.append(
            "A difference under about 50 sends per arm is noise. Kill the loser "
            "when one arm is clearly ahead, then write a new challenger."
        )
    return "\n".join(lines)


def next_actions(db: Database, settings: Settings, roles: dict[str, Role]) -> str:
    """One line per thing a person should do now. Ordered by what unblocks most."""
    lines: list[str] = []
    for key, role in sorted(roles.items()):
        if not role.is_live:
            continue
        counts = db.funnel(key)
        pending_review = counts.get("review", 0)
        approved = counts.get("approved", 0)
        enriched = counts.get("enriched", 0)
        verified = counts.get("verified", 0)
        queued = counts.get("queued", 0)
        if pending_review:
            lines.append(
                f"{key}: {pending_review} waiting on hand review. "
                f"`outbound review {key}`"
            )
        if approved:
            lines.append(f"{key}: {approved} approved and not enriched. `outbound enrich {key}`")
        if enriched:
            unchecked = db.scalar(
                "SELECT COUNT(DISTINCT c.id) FROM candidates c JOIN emails e ON e.candidate_id = c.id "
                "WHERE c.role_key = ? AND c.stage = 'enriched' AND e.verified_at IS NULL",
                (key,),
            ) or 0
            risky = enriched - unchecked
            if unchecked:
                lines.append(f"{key}: {unchecked} enriched and not verified. `outbound verify {key}`")
            if risky:
                lines.append(
                    f"{key}: {risky} address(es) came back risky or catch all. Decide: "
                    f"`outbound verify {key} --accept-risky`, or leave them out."
                )
        if verified:
            lines.append(f"{key}: {verified} ready to write to. `outbound queue {key}`")
        if queued:
            lines.append(f"{key}: {queued} queued. `outbound send {key} --live`")
        if not any((pending_review, approved, enriched, verified, queued)):
            total = sum(counts.values())
            if total < role.target_list_size:
                lines.append(
                    f"{key}: list is {total} of {role.target_list_size}. "
                    f"`outbound search {key}` and build more list."
                )
    booked = db.scalar("SELECT COUNT(*) FROM bookings WHERE status = 'booked'") or 0
    if booked:
        lines.append(f"bookings: {booked} booked and not re-checked. `outbound bookings triage`")
    waiting = db.scalar("SELECT COUNT(*) FROM inbound WHERE handled = 0") or 0
    if waiting:
        replied = db.scalar(
            "SELECT COUNT(*) FROM inbound WHERE handled = 0 AND kind = 'replied'"
        ) or 0
        lines.append(
            f"inbox: {waiting} message(s) waiting, {replied} of them real replies. "
            f"`outbound inbox`"
        )
    return "\n".join(f"  - {line}" for line in lines) or "  - nothing waiting."


def summary(db: Database, settings: Settings, roles: dict[str, Role], role_key: str | None = None) -> str:
    parts = [f"# Outbound report  {now():%Y-%m-%d %H:%M} UTC", ""]
    scope = role_key or "all roles"
    parts.append(f"## Funnel ({scope})")
    parts.append("")
    parts.append(funnel_table(db, role_key))
    parts.append("")
    parts.append(f"## Conversion ({scope})")
    parts.append("")
    parts.append(conversions(db, role_key))
    parts.append("")
    parts.append("## Sending today")
    parts.append("")
    day = sending_day(settings)
    rows = db.query("SELECT role_key, mailbox, count FROM send_log WHERE day = ?", (day,))
    total_today = sum(int(r["count"]) for r in rows)
    if rows:
        for row in rows:
            parts.append(f"  {row['role_key']} via {row['mailbox']}: {row['count']}")
    else:
        parts.append("  nothing sent today.")
    parts.append("")

    warm_cap, warm_note = warmup_cap(settings, db)
    ceiling = warm_cap if warm_cap >= 0 else domain_cap(settings)
    label = "warm up cap" if warm_cap >= 0 else "domain cap"
    parts.append(f"  {total_today}/{ceiling} against the {label} across all roles.")
    if warm_note:
        parts.append(f"  {warm_note}")

    rate, bounced, sent = db.bounce_rate()
    if sent:
        threshold = float(settings.get("limits.max_bounce_rate", 0.03))
        mark = "OVER THE CEILING" if rate > threshold else "fine"
        parts.append(
            f"  bounce rate {rate:.1%} ({bounced} of the last {sent}), "
            f"ceiling {threshold:.0%}: {mark}"
        )
    stop = bounce_guard(settings, db)
    if stop:
        parts.append("")
        parts.append(f"  SENDING IS HALTED: {stop}")
    parts.append("")
    variant_block = variants(db, settings, roles, role_key)
    if variant_block:
        parts.append("## Copy variants")
        parts.append("")
        parts.append(variant_block)
        parts.append("")

    parts.append("## Do next")
    parts.append("")
    parts.append(next_actions(db, settings, roles))
    return "\n".join(parts)
