"""Bookings: pull them in, re-check the person, confirm or cancel.

The screener is a ten minute call. Peter's plan is to let people book and then
re-check the profile before the call, cancelling the ones that are not a fit
and apologising by email. That is what this module does.

Two guard rails, because a cancelled call makes an angry person and angry
people write public complaints:

1. Cancelling is a decision a person makes, unless `--auto` is passed.
2. A cancellation always sends the apology, and always respects the
   `booking.cancel_lead_hours` notice period.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from typing import Any

from . import providers as provider_registry
from .compose import TEMPLATES_DIR, _read_template, build_context, lint, render_text
from .config import Role, Settings
from .db import Database
from .errors import OutboundError
from .pipeline import StepResult
from .score import score_profile
from .util import iso, norm_email, now, parse_iso


def sync(db: Database, settings: Settings, roles: dict[str, Role]) -> StepResult:
    """Pull bookings from the scheduler and match them to candidates."""
    result = StepResult(step="bookings:sync")
    name = str(settings.get("providers.booking", "dryrun"))
    provider = provider_registry.build("booking", name, settings)
    for raw in provider.list_bookings():
        provider_id = str(raw.get("provider_id") or raw.get("uid") or raw.get("id") or "")
        if not provider_id:
            result.bump("skipped_no_id")
            continue
        email = norm_email(raw.get("attendee_email") or raw.get("email") or "")
        match = None
        if email:
            match = db.one(
                "SELECT c.* FROM candidates c JOIN emails e ON e.candidate_id = c.id "
                "WHERE e.address = ? ORDER BY c.id DESC LIMIT 1",
                (email,),
            )
        role_key = (match or {}).get("role_key") or str(raw.get("role_key") or "")
        db.execute(
            "INSERT INTO bookings (candidate_id, role_key, provider, provider_id, "
            "attendee_name, attendee_email, start_at, end_at, answers_json, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'booked', ?) "
            "ON CONFLICT (provider, provider_id) DO UPDATE SET "
            "start_at = excluded.start_at, end_at = excluded.end_at, "
            "answers_json = excluded.answers_json, "
            "candidate_id = COALESCE(bookings.candidate_id, excluded.candidate_id), "
            "role_key = COALESCE(bookings.role_key, excluded.role_key)",
            (
                (match or {}).get("id"),
                role_key,
                name,
                provider_id,
                raw.get("attendee_name") or raw.get("name"),
                email,
                raw.get("start_at") or raw.get("startTime"),
                raw.get("end_at") or raw.get("endTime"),
                json.dumps(raw.get("answers") or {}, ensure_ascii=False),
                iso(),
            ),
        )
        if match:
            if match["stage"] not in ("hired", "screened", "cancelled"):
                db.set_stage(int(match["id"]), "booked", f"booked {provider_id}")
            result.bump("matched")
        else:
            result.bump("unmatched")
            result.notes.append(
                f"{provider_id} ({email or 'no email'}) did not match a candidate. "
                f"Someone booked from another channel, or the address differs."
            )
    return result


def recheck(
    db: Database, settings: Settings, roles: dict[str, Role], booking_id: int | None = None
) -> list[dict[str, Any]]:
    """Re-check every booked person against the role. Returns a worklist.

    This is the false-positive catch: someone the send got wrong books a call,
    and re-reading the profile against the role finds them before the call is
    wasted. The heuristic score always runs. When an AI evaluator is
    configured (`evaluation.provider` is not "none"), it also reads the profile
    and its verdict drives the suggestion, because it reads the whole profile
    the way a person re-checking a LinkedIn would.
    """
    allow = {str(c).upper() for c in settings.get("compliance.allow_countries", []) or []}
    block = {str(c).upper() for c in settings.get("compliance.block_countries", []) or []}
    threshold = float(settings.get("booking.recheck_min_score", 0.55))

    eval_name = str(settings.get("evaluation.provider", "none") or "none")
    evaluator = (
        provider_registry.build("evaluate", eval_name, settings)
        if eval_name not in ("none", "") else None
    )

    where = "WHERE status = 'booked'"
    params: list[Any] = []
    if booking_id:
        where += " AND id = ?"
        params.append(booking_id)
    out = []
    for booking in db.query(f"SELECT * FROM bookings {where} ORDER BY start_at ASC", params):
        candidate = (
            db.candidate(int(booking["candidate_id"])) if booking["candidate_id"] else None
        )
        role = roles.get(booking["role_key"] or "")
        score = None
        ai = None
        reason = None
        if candidate and role:
            profile = dict(candidate)
            try:
                profile["raw"] = json.loads(candidate.get("profile_json") or "{}")
            except json.JSONDecodeError:
                profile["raw"] = {}
            outcome = score_profile(
                role,
                profile,
                is_suppressed=lambda kind, value: bool(db.is_suppressed(kind, value)),
                blocked_countries=block,
                allowed_countries=allow or None,
            )
            score = outcome.score
            if evaluator is not None:
                from .evaluate import build_brief
                from .score import top_evidence

                profile["_evidence"] = top_evidence(role, profile)
                try:
                    ai = evaluator.evaluate(build_brief(role), profile)
                except Exception as exc:  # noqa: BLE001  a bad re-check must not stop the list
                    ai = None
                    reason = f"AI re-check failed: {exc}"
            db.execute(
                "UPDATE bookings SET recheck_score = ? WHERE id = ?", (score, booking["id"])
            )

        # The AI verdict decides when there is one; otherwise the score does.
        if ai is not None:
            if ai.get("disqualify") or ai.get("verdict") == "weak":
                suggest = "cancel"
                reason = (
                    ai.get("disqualify_reason")
                    or "; ".join(str(r) for r in (ai.get("reasons") or [])[:2])
                    or f"AI re-check: weak fit {ai.get('fit', 0):.2f}"
                )
            elif ai.get("verdict") == "strong":
                suggest = "confirm"
            else:
                suggest = "look"
        elif score is not None:
            suggest = "cancel" if score < threshold else "confirm"
            if suggest == "cancel":
                reason = f"re-check score {score:.2f} below {threshold:.2f}"
        else:
            suggest = "look"

        out.append(
            {
                "booking": booking,
                "candidate": candidate,
                "role": role,
                "score": score,
                "ai": ai,
                "suggest": suggest,
                "reason": reason,
                "linkedin": (candidate or {}).get("linkedin_url"),
                "answers": json.loads(booking.get("answers_json") or "{}"),
            }
        )
    return out


def _render_shared(
    settings: Settings, role: Role | None, candidate: dict[str, Any], template: str, to_address: str
) -> tuple[str, str]:
    path = TEMPLATES_DIR / "shared" / f"{template}.md"
    subject_raw, body_raw = _read_template(path)
    from .config import Role as RoleType

    stand_in = role or RoleType(
        key="unknown", title="the role", status="draft", seats=1, seniority="",
        employment="", comp="", comp_in_email=False, jd_url="", one_liner="",
        sender="", template_dir="shared", daily_cap=0, target_list_size=0,
    )
    context = build_context(settings, stand_in, candidate, to_address)
    subject = render_text(subject_raw, context, f"{path} subject")
    body = render_text(body_raw, context, f"{path} body")
    problems = lint(subject, body, strict=False)
    if problems:
        raise OutboundError(f"copy check failed for {path}: {'; '.join(problems)}")
    return subject, body


def decide(
    db: Database,
    settings: Settings,
    roles: dict[str, Role],
    booking_id: int,
    decision: str,
    reason: str = "",
    live: bool = False,
    force_late: bool = False,
) -> StepResult:
    """Confirm or cancel one booking. Cancelling always sends the apology."""
    result = StepResult(step=f"bookings:{decision}")
    booking = db.one("SELECT * FROM bookings WHERE id = ?", (booking_id,))
    if not booking:
        raise OutboundError(f"no booking with id {booking_id}")
    candidate = db.candidate(int(booking["candidate_id"])) if booking["candidate_id"] else None
    role = roles.get(booking["role_key"] or "")
    to_address = norm_email(booking.get("attendee_email") or "")
    stand_in = dict(candidate or {})
    if not stand_in.get("first_name"):
        from .util import name_parts

        first, last = name_parts(booking.get("attendee_name"))
        stand_in.setdefault("first_name", first or "there")
        stand_in.setdefault("last_name", last)
        stand_in.setdefault("full_name", booking.get("attendee_name") or "")

    if decision == "confirm":
        db.execute(
            "UPDATE bookings SET status = 'confirmed', recheck_verdict = 'confirm', "
            "recheck_note = ? WHERE id = ?",
            (reason, booking_id),
        )
        if candidate:
            db.set_stage(int(candidate["id"]), "confirmed", reason or "confirmed by hand")
        result.bump("confirmed")
        return result

    if decision != "cancel":
        raise OutboundError(f"decision must be confirm or cancel, not {decision!r}")

    start = parse_iso(booking.get("start_at"))
    lead = float(settings.get("booking.cancel_lead_hours", 12))
    if start and start - now() < _dt.timedelta(hours=lead) and not force_late:
        # Enforced, not advisory. A late cancellation makes an angry person,
        # and angry people write the public complaints that cause the platform
        # problems. Inside the notice period, keep the call. Pass force_late to
        # override deliberately.
        raise OutboundError(
            f"less than {lead:g} hours before the call. Cancelling this late is "
            f"worse than taking the ten minutes. Keep it, or pass --force-late "
            f"to cancel anyway."
        )

    if not to_address:
        raise OutboundError(f"booking {booking_id} has no attendee email, cannot apologise")

    subject, body = _render_shared(settings, role, stand_in, "cancel-apology", to_address)

    name = str(settings.get("providers.booking", "dryrun"))
    provider = provider_registry.build("booking", name, settings)
    if live:
        provider.cancel(str(booking["provider_id"]), reason or "not a fit for this seat")
        result.bump("cancelled_at_provider")
    else:
        result.notes.append("DRY RUN: the scheduler booking was left in place.")

    send_name = str(settings.get("providers.send", "dryrun")) if live else "dryrun"
    sender = provider_registry.build("send", send_name, settings)
    identity = settings.section("identity")
    sender.send(
        {
            "to": to_address,
            "from": f"{identity.get('from_name','')} <{identity.get('from_email','')}>",
            "reply_to": identity.get("reply_to") or identity.get("from_email"),
            "subject": subject,
            "body": body,
            "step": 0,
            "role_key": booking.get("role_key") or "",
            "candidate_id": booking.get("candidate_id"),
        }
    )
    result.bump("apology_sent")
    db.execute(
        "UPDATE bookings SET status = 'cancelled', recheck_verdict = 'cancel', "
        "recheck_note = ?, cancelled_at = ? WHERE id = ?",
        (reason, iso(), booking_id),
    )
    if candidate:
        db.set_stage(int(candidate["id"]), "cancelled", reason or "cancelled after re-check")
    return result


def triage(
    db: Database,
    settings: Settings,
    roles: dict[str, Role],
    auto: bool = False,
    live: bool = False,
    force_late: bool = False,
) -> StepResult:
    """Re-check every booking. With --auto, act on the suggestion."""
    result = StepResult(step="bookings:triage")
    for item in recheck(db, settings, roles):
        booking = item["booking"]
        result.bump(f"suggest_{item['suggest']}")
        if not auto:
            continue
        if item["suggest"] == "cancel":
            score = item.get("score")
            reason = item.get("reason") or (
                f"re-check score {score:.2f} below threshold"
                if score is not None else "re-check found a non-fit"
            )
            try:
                sub = decide(
                    db, settings, roles, int(booking["id"]), "cancel",
                    reason=reason, live=live, force_late=force_late,
                )
            except OutboundError as exc:
                result.notes.append(f"booking {booking['id']}: {exc}")
                result.bump("cancel_skipped_late")
                continue
        elif item["suggest"] == "confirm":
            sub = decide(db, settings, roles, int(booking["id"]), "confirm", live=live)
        else:
            result.notes.append(
                f"booking {booking['id']} has no matched candidate. Decide by hand."
            )
            continue
        for key, value in sub.counts.items():
            result.bump(key, value)
        result.notes.extend(sub.notes)
    return result
