"""The funnel, one function per step.

source -> score -> hand review -> enrich -> verify -> queue -> send

Every step is resumable and idempotent. Run any of them twice and the second
run does nothing new. That matters because these commands run on a cron and a
half finished run must never double send.
"""

from __future__ import annotations

import csv
import datetime as _dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from . import providers as provider_registry
from .compliance import assert_sendable, geo_allowed, message_problems
from .compose import render, steps_available
from .config import Role, Settings
from .db import TERMINAL_STAGES, Database
from .errors import ComplianceError, OutboundError, SafetyStop
from .profiles import normalize
from .score import route, score_profile, top_evidence
from .util import iso, now, norm_email, parse_iso, plural


@dataclass
class StepResult:
    step: str
    counts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def __str__(self) -> str:
        body = ", ".join(f"{k}={v}" for k, v in sorted(self.counts.items())) or "nothing to do"
        tail = ("\n  " + "\n  ".join(self.notes)) if self.notes else ""
        return f"{self.step}: {body}{tail}"


# ---------------------------------------------------------------- sourcing


def import_rows(
    db: Database,
    settings: Settings,
    role: Role,
    rows: Iterable[dict[str, Any]],
    source: str,
    search_name: str = "",
) -> StepResult:
    result = StepResult(step=f"import[{role.key}]")
    for raw in rows:
        try:
            profile = normalize(raw, source=source, source_search=search_name or str(raw.get("_search") or ""))
        except TypeError:
            result.bump("malformed")
            continue
        if not profile.get("full_name"):
            result.bump("skipped_no_name")
            continue
        note = str(raw.get("personal_note") or "").strip()
        candidate_id, created = db.upsert_candidate(role.key, profile)
        if note:
            db.execute(
                "UPDATE candidates SET personal_note = ? WHERE id = ?", (note, candidate_id)
            )
        result.bump("created" if created else "updated")
    return result


def read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rows.append(json.loads(line))
    return rows


def read_any(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".jsonl", ".ndjson"}:
        return read_jsonl(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for key in ("results", "items", "data", "profiles", "people"):
                if isinstance(data.get(key), list):
                    return data[key]
            return [data]
        return list(data)
    return read_csv(path)


def run_search(
    db: Database,
    settings: Settings,
    role: Role,
    only: list[str] | None = None,
    limit: int | None = None,
) -> StepResult:
    name = str(settings.get("providers.search", "dryrun"))
    provider = provider_registry.build("search", name, settings)
    result = StepResult(step=f"search[{role.key}]")
    cap = limit or int(settings.get("limits.max_profiles_per_search", 1000))
    from .search import provider_spec

    for spec in role.searches:
        if only and spec.name not in only:
            continue
        payloads = provider.search(provider_spec(role, spec, settings), min(cap, spec.target))
        sub = import_rows(db, settings, role, payloads, source=name, search_name=spec.name)
        for key, value in sub.counts.items():
            result.bump(key, value)
        result.notes.append(f"{spec.name}: {len(payloads)} profiles")
    return result


# ---------------------------------------------------------------- scoring


def score_all(
    db: Database, settings: Settings, role: Role, restage: bool = False
) -> StepResult:
    result = StepResult(step=f"score[{role.key}]")
    stages = None if restage else ["sourced"]
    allow = {str(c).upper() for c in settings.get("compliance.allow_countries", []) or []}
    block = {str(c).upper() for c in settings.get("compliance.block_countries", []) or []}
    scoring = settings.section("scoring")

    for row in db.candidates(role.key, stages=stages, order="id ASC"):
        if not restage and row["stage"] not in ("sourced",):
            continue
        profile = dict(row)
        try:
            profile["raw"] = json.loads(row.get("profile_json") or "{}")
        except json.JSONDecodeError:
            profile["raw"] = {}
        outcome = score_profile(
            role,
            profile,
            is_suppressed=lambda kind, value: bool(db.is_suppressed(kind, value)),
            blocked_countries=block,
            allowed_countries=allow or None,
        )
        target = route(outcome, scoring)
        # Re-scoring must not undo a person's decision. `--restage` re-ranks
        # after an ICP change, and a candidate who is already approved or
        # further has had a human or the funnel act on them; moving them back
        # to review or rejected would wipe that work and could walk a booked or
        # sent person backwards. So the stage only changes while the person is
        # still in a pre-decision stage; otherwise the score updates for
        # reference and the stage is left where it is.
        RESTAGEABLE = {"sourced", "scored", "review", "rejected"}
        # A hand-rejection is a decision, exactly like a hand-approval, and a
        # re-score must not resurrect it. A person is rejected by hand for
        # reasons the score cannot see (a bad reference, a known non-fit), and
        # review_state records that. Auto-rejects (review_state 'pending') stay
        # restageable so broadening the ICP can reconsider them.
        hand_rejected = (row["stage"] == "rejected"
                         and str(row.get("review_state") or "") == "rejected")
        if restage and (row["stage"] not in RESTAGEABLE or hand_rejected):
            db.execute(
                "UPDATE candidates SET score = ?, score_json = ?, updated_at = ? WHERE id = ?",
                (outcome.score, outcome.to_json(), iso(), row["id"]),
            )
            db.log_event(
                int(row["id"]), "rescored",
                f"{outcome.score:.3f} — stage {row['stage']} kept, decision already made",
            )
            result.bump(f"rescored:{row['stage']}")
            continue
        db.execute(
            "UPDATE candidates SET score = ?, score_json = ?, stage = ?, updated_at = ? WHERE id = ?",
            (outcome.score, outcome.to_json(), target, iso(), row["id"]),
        )
        # Log it, so `outbound show` can say why a person ended where they did.
        reason = (
            f"disqualified by {outcome.disqualifier}: {outcome.reason}"
            if outcome.disqualified
            else ", ".join(outcome.top_reasons(3)) or "no signal fired"
        )
        db.log_event(int(row["id"]), f"scored:{target}", f"{outcome.score:.3f} — {reason}")
        result.bump(target)
        if outcome.disqualified:
            result.bump(f"dq:{outcome.disqualifier}")
    return result


def evaluate_candidates(
    db: Database,
    settings: Settings,
    role: Role,
    stages: list[str] | None = None,
    limit: int | None = None,
    commit: bool = True,
) -> StepResult:
    """The AI screen. A richer second pass after scoring.

    It reads each profile against the role the way a person would, records a
    fit verdict with reasons, and drafts the personal note the first email
    needs. What it does with that verdict depends on `evaluation.mode`:

      assist  the default. It drafts the note and logs the verdict, but leaves
              everyone in review. A person still decides; the note is done for
              them, which is most of the work.
      auto    it approves a strong fit (with its drafted note), rejects a weak
              one, and sends a maybe to review. This is what lets the list move
              at volume without a person writing a note for each one.

    `commit=False` is a dry run: it calls the evaluator and reports what it
    would do, but writes nothing.
    """
    from .evaluate import build_brief, route_verdict
    from .score import top_evidence

    section = settings.section("evaluation")
    provider_name = str(section.get("provider", "dryrun"))
    mode = str(section.get("mode", "assist")).lower()
    approve_at = float(section.get("auto_approve_at", 0.75))
    reject_below = float(section.get("auto_reject_below", 0.40))
    stages = stages or [str(s) for s in section.get("stages", ["review"])]

    result = StepResult(step=f"evaluate[{role.key}]")
    provider = provider_registry.build("evaluate", provider_name, settings)
    if provider is None:
        result.notes.append("evaluation provider is 'none'. Nothing to do.")
        return result

    brief = build_brief(role)
    for row in db.candidates(role.key, stages=stages, limit=limit):
        profile = dict(row)
        try:
            profile["raw"] = json.loads(row.get("profile_json") or "{}")
        except json.JSONDecodeError:
            profile["raw"] = {}
        profile["_evidence"] = top_evidence(role, profile)
        try:
            verdict = provider.evaluate(brief, profile)
        except Exception as exc:  # noqa: BLE001  one bad profile must not stop the run
            result.notes.append(f"id {row['id']}: evaluate failed: {exc}")
            result.bump("error")
            continue

        fit = float(verdict.get("fit") or 0.0)
        decision = route_verdict(
            fit, str(verdict.get("verdict") or ""), bool(verdict.get("disqualify")),
            approve_at, reject_below,
        )
        note = str(verdict.get("personal_note") or "").strip()
        reasons = "; ".join(str(r) for r in (verdict.get("reasons") or [])[:3])
        detail = f"{fit:.2f} {verdict.get('verdict','?')} ({mode}->{decision}) {reasons}".strip()

        result.bump(f"verdict:{verdict.get('verdict','?')}")
        if not commit:
            result.bump(f"would:{decision}")
            continue

        db.log_event(int(row["id"]), "ai_evaluate", detail)
        # A note a person wrote wins over the model's draft. The effective note
        # is the human one if it exists, else the drafted one. The draft is
        # stored only when there is no human note to keep.
        existing = str(row.get("personal_note") or "").strip()
        effective_note = existing or note
        if note and not existing:
            db.execute(
                "UPDATE candidates SET personal_note = ? WHERE id = ?", (note, row["id"])
            )

        if mode == "auto" and decision == "approve":
            if not effective_note:
                # No note, no email is the rule. Without a specific detail an
                # auto-approve cannot send, so it goes to review instead.
                result.bump("approve_without_note_to_review")
                continue
            set_review(db, role, int(row["id"]), "approve", effective_note)
            result.bump("approved")
        elif mode == "auto" and decision == "reject":
            reason = str(verdict.get("disqualify_reason") or "") or f"AI screen: fit {fit:.2f}"
            set_review(db, role, int(row["id"]), "reject", reason)
            result.bump("rejected")
        else:
            result.bump("left_for_review")
    return result


def export_review(db: Database, role: Role, path: Path, limit: int | None = None) -> int:
    """Write the review queue to a CSV a person can work through offline.

    Reviewing 300 profiles one command at a time is the real bottleneck. Open
    the CSV, click the profile links, fill in `decision` and `personal_note`,
    then import it back.
    """
    rows = db.candidates(role.key, stages=["review"], limit=limit)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id", "decision", "personal_note", "score", "full_name", "title",
        "company", "company_headcount", "location", "linkedin_url",
        "evidence", "top_signals", "review_note",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            try:
                detail = json.loads(row.get("score_json") or "{}")
                top = sorted(detail.get("signals", []), key=lambda s: -s["contribution"])[:3]
                signals = ", ".join(f"{s['key']} {s['contribution']:+.2f}" for s in top)
            except json.JSONDecodeError:
                signals = ""
            profile = dict(row)
            try:
                profile["raw"] = json.loads(row.get("profile_json") or "{}")
            except json.JSONDecodeError:
                profile["raw"] = {}
            evidence = " || ".join(top_evidence(role, profile))
            writer.writerow(
                {
                    "id": row["id"],
                    "evidence": evidence,
                    "decision": "",
                    "personal_note": row.get("personal_note") or "",
                    "score": f"{row.get('score') or 0:.2f}",
                    "full_name": row.get("full_name"),
                    "title": row.get("title"),
                    "company": row.get("company"),
                    "company_headcount": row.get("company_headcount"),
                    "location": row.get("location"),
                    "linkedin_url": row.get("linkedin_url"),
                    "top_signals": signals,
                    "review_note": "",
                }
            )
    return len(rows)


def import_review(db: Database, role: Role, path: Path) -> StepResult:
    """Read a filled in review CSV back. Blank decisions are left alone."""
    result = StepResult(step=f"review:import[{role.key}]")
    for row in read_csv(path):
        raw_id = str(row.get("id") or "").strip()
        decision = str(row.get("decision") or "").strip().lower()
        if not raw_id or not decision:
            result.bump("skipped_blank")
            continue
        try:
            candidate_id = int(raw_id)
        except ValueError:
            result.bump("bad_id")
            continue
        note = str(row.get("personal_note") or "").strip()
        review_note = str(row.get("review_note") or "").strip()
        try:
            outcome = set_review(
                db, role, candidate_id, decision,
                note if decision.startswith(("a", "y")) else review_note,
            )
        except OutboundError as exc:
            result.bump("refused")
            result.notes.append(f"id {candidate_id}: {exc}")
            continue
        result.bump(outcome)
    return result


def set_review(
    db: Database, role: Role, candidate_id: int, decision: str, note: str = ""
) -> str:
    """Approve or reject one candidate by hand. This is the gate that matters."""
    row = db.candidate(candidate_id)
    if not row:
        raise OutboundError(f"no candidate with id {candidate_id}")
    if row["role_key"] != role.key:
        raise OutboundError(
            f"candidate {candidate_id} belongs to role {row['role_key']}, not {role.key}"
        )
    decision = decision.lower()
    if decision in ("approve", "approved", "yes", "y"):
        if not str(row.get("personal_note") or "").strip() and not note:
            raise OutboundError(
                "approving needs a personal note: the one specific detail from "
                "the profile that goes in line one of the email. No detail, no email."
            )
        if note:
            db.execute(
                "UPDATE candidates SET personal_note = ? WHERE id = ?", (note, candidate_id)
            )
        db.execute(
            "UPDATE candidates SET review_state = 'approved' WHERE id = ?", (candidate_id,)
        )
        db.set_stage(candidate_id, "approved", "approved by hand")
        return "approved"
    db.execute(
        "UPDATE candidates SET review_state = 'rejected', review_note = ? WHERE id = ?",
        (note, candidate_id),
    )
    db.set_stage(candidate_id, "rejected", note or "rejected by hand")
    return "rejected"


# ---------------------------------------------------------------- enrichment


def _enrich_chain(settings: Settings) -> list[Any]:
    waterfall = list(settings.get("providers.enrich_waterfall", []) or [])
    if not waterfall:
        waterfall = [str(settings.get("providers.enrich", "dryrun"))]
    return [provider_registry.build("enrich", name, settings) for name in waterfall if name]


def enrich(db: Database, settings: Settings, role: Role, limit: int | None = None) -> StepResult:
    result = StepResult(step=f"enrich[{role.key}]")
    chain = _enrich_chain(settings)
    if not chain:
        raise OutboundError("no enrichment provider configured")
    cap = limit or int(settings.get("limits.max_enrich_per_run", 250))
    never_rejected = bool(settings.get("limits.never_enrich_rejected", True))
    max_attempts = int(settings.get("limits.enrich_attempts", 2))

    for row in db.candidates(role.key, stages=["approved"], limit=cap):
        if never_rejected and row["stage"] == "rejected":
            continue
        attempts = int(
            db.scalar(
                "SELECT COUNT(*) FROM events WHERE candidate_id = ? AND kind = 'enrich:miss'",
                (row["id"],),
            )
            or 0
        )
        if attempts >= max_attempts:
            # Every provider has been asked twice. Retrying forever burns credits
            # and makes the report say there is work waiting when there is not.
            db.set_stage(row["id"], "stopped", f"no address after {attempts} attempts")
            result.bump("no_email_exhausted")
            continue
        if db.primary_email(row["id"]):
            db.set_stage(row["id"], "enriched", "already had an address")
            result.bump("already_had_email")
            continue
        found = []
        for provider in chain:
            try:
                found = provider.find_email(dict(row)) or []
            except Exception as exc:  # a dead vendor must not kill the run
                result.notes.append(f"{provider.name} failed for id {row['id']}: {exc}")
                continue
            if found:
                break
        if not found:
            result.bump("no_email_found")
            db.log_event(row["id"], "enrich:miss", "no address from any provider")
            continue
        for index, hit in enumerate(found):
            db.add_email(
                row["id"],
                hit.get("address", ""),
                provider=hit.get("source", ""),
                confidence=hit.get("confidence"),
                primary=(index == 0),
            )
        db.set_stage(row["id"], "enriched", f"{len(found)} address(es)")
        result.bump("enriched")
    return result


def verify_emails(
    db: Database,
    settings: Settings,
    role: Role,
    limit: int | None = None,
    accept_risky: bool = False,
) -> StepResult:
    result = StepResult(step=f"verify[{role.key}]")
    name = str(settings.get("providers.verify", "dryrun"))
    provider = provider_registry.build("verify", name, settings) if name != "none" else None
    cap = limit or int(settings.get("limits.max_enrich_per_run", 250))

    for row in db.candidates(role.key, stages=["enriched"], limit=cap):
        email = db.primary_email(row["id"])
        if not email:
            result.bump("no_address")
            continue
        if provider is None:
            db.set_stage(row["id"], "verified", "verification disabled")
            result.bump("skipped_verification")
            continue
        if db.is_suppressed("email", email["address"]):
            db.set_stage(row["id"], "unsubscribed", "address on the suppression list")
            result.bump("suppressed")
            continue
        if email.get("verified_at"):
            # Already checked. Either promote it on request, or leave it alone.
            status = str(email.get("verify_status") or "unknown")
            if accept_risky and status in ("risky", "catch_all", "unknown"):
                db.set_stage(row["id"], "verified", f"{status} address accepted by hand")
                result.bump(f"accepted_{status}")
            else:
                result.bump(f"already_{status}")
            continue
        try:
            status = provider.verify(email["address"])
        except Exception as exc:
            result.notes.append(f"{name} failed for {email['address']}: {exc}")
            result.bump("provider_error")
            continue
        db.set_verify(int(email["id"]), status, name)
        result.bump(status)
        if status == "valid":
            db.set_stage(row["id"], "verified", "address verified")
        elif status in ("invalid",):
            db.set_stage(row["id"], "bounced", "address failed verification")
            db.suppress("email", email["address"], "failed verification")
        # risky and catch_all stay at enriched. A person decides.
    return result


# ---------------------------------------------------------------- sending


def _tz(settings: Settings) -> ZoneInfo:
    try:
        return ZoneInfo(str(settings.get("sending.timezone", "UTC")))
    except Exception:
        return ZoneInfo("UTC")


def sending_day(settings: Settings, at: _dt.datetime | None = None) -> str:
    """The day send caps are counted against, in the sending timezone.

    The report and the sender must agree on this. They did not, and a send at
    02:00 UTC was logged against the New York day before while the report
    looked for the UTC day. The result read "nothing sent today" right after
    sending seven emails.
    """
    return (at or now()).astimezone(_tz(settings)).strftime("%Y-%m-%d")


def can_send_now(settings: Settings, at: _dt.datetime | None = None) -> tuple[bool, str]:
    zone = _tz(settings)
    local = (at or now()).astimezone(zone)
    skip = {int(d) for d in settings.get("sending.skip_weekdays", []) or []}
    if local.weekday() in skip:
        return False, f"{local:%A} is a skip day"
    window = settings.get("sending.send_window", ["00:00", "23:59"]) or ["00:00", "23:59"]
    try:
        start_h, start_m = (int(x) for x in str(window[0]).split(":"))
        end_h, end_m = (int(x) for x in str(window[1]).split(":"))
    except (ValueError, IndexError):
        return True, ""
    start = local.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
    end = local.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    if not (start <= local <= end):
        return False, f"local time {local:%H:%M} is outside the send window {window[0]} to {window[1]}"
    return True, ""


def warmup_cap(settings: Settings, db: Database) -> tuple[int, str]:
    """Today's ceiling while the domain is warming up.

    A new domain that sends its full volume on day one gets filtered, and the
    filtering is silent. The ramp is counted in days the domain has actually
    sent on, not calendar days, so a weekend or a pause does not fast forward
    it.

    Returns (cap, note). A cap of -1 means warm up is finished.
    """
    ramp = settings.get("warmup.ramp", []) or []
    if not ramp:
        return -1, ""
    # Freeze the tier for the whole calendar day: count only days before today.
    used = db.sending_days_used(before=sending_day(settings))
    elapsed = 0
    for entry in ramp:
        try:
            days, per_day = int(entry[0]), int(entry[1])
        except (TypeError, ValueError, IndexError):
            continue
        if days <= 0:
            return -1, ""
        if used < elapsed + days:
            remaining = elapsed + days - used
            return per_day, (
                f"warm up day {used + 1}: {per_day} a day, "
                f"{remaining} more day(s) at this level"
            )
        elapsed += days
    return -1, ""


def bounce_guard(settings: Settings, db: Database) -> str:
    """Empty string when the bounce rate is fine, otherwise the reason to stop.

    A bounce rate above about three percent damages a young sending domain,
    and this one has no reputation to spend. Stopping is cheap; a filtered
    domain is not.
    """
    threshold = float(settings.get("limits.max_bounce_rate", 0.03))
    minimum = int(settings.get("limits.bounce_rate_min_sends", 40))
    window = int(settings.get("limits.bounce_rate_window", 200))
    rate, bounced, sent = db.bounce_rate(window)
    if sent < minimum:
        return ""
    if rate > threshold:
        return (
            f"bounce rate is {rate:.1%} ({bounced} of the last {sent} sends), "
            f"over the {threshold:.0%} ceiling. Stop and fix the list or the "
            f"verifier before sending more. Raise limits.max_bounce_rate only "
            f"if you know why the rate is high."
        )
    return ""


def domain_cap(settings: Settings) -> int:
    """How many emails may leave the sending domain today, across all roles.

    The mailboxes are shared. Three live roles at 18 a day each would push 54
    emails through two mailboxes, which is 27 per mailbox and well past what a
    warmed mailbox should carry. The domain cap binds first.
    """
    per_box = int(settings.get("sending.per_mailbox_per_day", 18))
    boxes = max(1, int(settings.get("sending.mailboxes", 1)))
    return per_box * boxes


def daily_cap(settings: Settings, role: Role) -> int:
    """The per role cap. The domain cap in `domain_cap` binds on top of it."""
    return min(role.daily_cap, domain_cap(settings))


def queue_next(
    db: Database, settings: Settings, role: Role, limit: int | None = None
) -> StepResult:
    """Render and queue the next due message for every eligible candidate."""
    result = StepResult(step=f"queue[{role.key}]")
    steps = steps_available(role)
    if not steps:
        raise OutboundError(f"no templates in templates/{role.template_dir}/")
    # sending.max_steps caps the sequence length without deleting templates.
    # Set it to 1 for the one-email flow (intro, JD link, screener link, no
    # follow-ups); 0 or unset uses every template the role has.
    max_steps = int(settings.get("sending.max_steps", 0) or 0)
    if max_steps > 0:
        steps = steps[:max_steps]
    gaps = [int(g) for g in settings.get("sending.step_gap_days", [0, 4, 8]) or [0]]
    cap = limit or int(settings.get("limits.max_sends_per_run", 60)) * 3
    one_role_only = bool(settings.get("limits.one_role_per_person", True))

    # Step 1 for people who have never been written to.
    for row in db.candidates(role.key, stages=["verified"], limit=cap):
        email = db.primary_email(row["id"])
        if not email:
            result.bump("no_address")
            continue
        ok, why = geo_allowed(settings, row.get("country"))
        if not ok:
            db.set_stage(row["id"], "rejected", f"geo: {why}")
            result.bump("geo_blocked")
            continue
        if db.is_suppressed("email", email["address"]):
            db.set_stage(row["id"], "unsubscribed", "suppression list")
            result.bump("suppressed")
            continue
        if one_role_only:
            other = db.contacted_for_another_role(row["linkedin_key"], role.key)
            if other:
                db.set_stage(
                    row["id"], "stopped",
                    f"already written to for role {other['role_key']}",
                )
                result.bump("already_contacted_for_another_role")
                continue
        try:
            rendered = render(settings, role, dict(row), email["address"], steps[0])
        except OutboundError as exc:
            result.notes.append(f"id {row['id']}: {exc}")
            result.bump("render_failed")
            continue
        problems = message_problems(settings, rendered.body)
        if problems:
            result.notes.append(f"id {row['id']}: " + "; ".join(p.message for p in problems))
            result.bump("compliance_failed")
            continue
        db.queue_message(
            row["id"], role.key, steps[0], email["address"],
            rendered.subject, rendered.body, iso(), variant=rendered.variant,
        )
        db.set_stage(row["id"], "queued", f"step {steps[0]} queued")
        result.bump("queued_step1")

    # Follow ups for people already written to who have not replied or booked.
    for row in db.candidates(role.key, stages=["sent"], limit=cap):
        sent = db.query(
            "SELECT step, sent_at FROM messages WHERE candidate_id = ? AND status = 'sent' "
            "ORDER BY step DESC",
            (row["id"],),
        )
        if not sent:
            continue
        last_step = int(sent[0]["step"])
        following = [s for s in steps if s > last_step]
        if not following:
            continue
        next_step = following[0]
        if db.one(
            "SELECT id FROM messages WHERE candidate_id = ? AND step = ?",
            (row["id"], next_step),
        ):
            continue
        first_sent = parse_iso(sent[-1]["sent_at"]) or now()
        gap_index = min(steps.index(next_step), len(gaps) - 1)
        due = first_sent + _dt.timedelta(days=gaps[gap_index])
        email = db.primary_email(row["id"])
        if not email:
            continue
        # Belt and braces. send_due checks this again, but an address can be
        # suppressed by a bulk unsubscribe import while the stage is still
        # 'sent', and there is no reason to queue a message we will not send.
        if db.is_suppressed("email", email["address"]):
            db.set_stage(row["id"], "unsubscribed", "suppressed before follow up")
            result.bump("suppressed")
            continue
        try:
            rendered = render(settings, role, dict(row), email["address"], next_step)
        except OutboundError as exc:
            result.notes.append(f"id {row['id']} step {next_step}: {exc}")
            result.bump("render_failed")
            continue
        # Same gate as step 1. A follow-up carries the unsubscribe line and
        # postal address too, and a config drift that drops them must stop
        # the queue here, not surface at send time or slip out.
        problems = message_problems(settings, rendered.body)
        if problems:
            result.notes.append(
                f"id {row['id']} step {next_step}: "
                + "; ".join(p.message for p in problems)
            )
            result.bump("compliance_failed")
            continue
        db.queue_message(
            row["id"], role.key, next_step, email["address"],
            rendered.subject, rendered.body, iso(due), variant=rendered.variant,
        )
        result.bump(f"queued_step{next_step}")
    return result


def send_test(
    db: Database,
    settings: Settings,
    role: Role,
    to_address: str,
    step: int = 1,
    candidate_id: int | None = None,
    variant: str | None = None,
    live: bool = False,
) -> StepResult:
    """Send one real email to an address you control.

    Do this before the first candidate send, every time the copy changes, and
    after any DNS change. Reading the raw headers of a message that actually
    arrived is the only way to know SPF, DKIM and DMARC pass; a DNS check says
    the records exist, not that the mail is signed with them.

    It bypasses the queue entirely: nothing is recorded against a candidate,
    nothing counts toward the daily cap, and no suppression is written.
    """
    result = StepResult(step=f"send-test[{role.key}]")
    if not to_address:
        raise OutboundError("give an address to send the test to")

    if candidate_id:
        candidate = db.candidate(int(candidate_id))
        if not candidate:
            raise OutboundError(f"no candidate with id {candidate_id}")
        candidate = dict(candidate)
    else:
        candidate = {
            "id": 0,
            "first_name": "Sample",
            "last_name": "Person",
            "full_name": "Sample Person",
            "title": "Head of Operations",
            "company": "Example Company",
            "location": "Austin, TX",
            "personal_note": (
                "THIS IS A TEST SEND. In a real email this line is the one "
                "specific thing you noticed about the person."
            ),
        }
    if not str(candidate.get("personal_note") or "").strip():
        candidate["personal_note"] = "THIS IS A TEST SEND."

    rendered = render(settings, role, candidate, to_address, step, variant=variant)
    problems = message_problems(settings, rendered.body)
    for problem in problems:
        result.notes.append(f"compliance: {problem.message}")

    identity = settings.section("identity")
    name = str(settings.get("providers.send", "dryrun")) if live else "dryrun"
    provider = provider_registry.build("send", name, settings)
    provider_id = provider.send({
        "to": to_address,
        "from": f"{identity.get('from_name','')} <{identity.get('from_email','')}>",
        "reply_to": identity.get("reply_to") or identity.get("from_email"),
        "subject": rendered.subject,
        "body": rendered.body,
        "step": step,
        "role_key": role.key,
        "candidate_id": None,
        "variant": rendered.variant,
    })
    result.bump("sent")
    result.notes.append(f"variant {rendered.variant}, subject: {rendered.subject}")
    result.notes.append(f"provider id: {provider_id}")
    db.log_run("send-test", f"{role.key} step {step} to {to_address}", str(provider_id), not live)
    if live:
        result.notes.append(
            "Open it and read the RAW headers. All three of SPF, DKIM and DMARC "
            "must say pass. Then check it did not land in spam or promotions."
        )
    else:
        result.notes.append("DRY RUN. It went to the outbox. Pass --live to actually send it.")
    return result


def send_due(
    db: Database,
    settings: Settings,
    role: Role,
    live: bool = False,
    limit: int | None = None,
    attest_warmup: bool = False,
    ignore_window: bool = False,
    commit: bool | None = None,
) -> StepResult:
    """Send every queued message that is due, up to the daily cap.

    `live` is the safety switch. Without it the send goes through the dry run
    provider and lands in the outbox, whatever `providers.send` says.

    `commit` decides whether the run changes state. When it does not commit, it
    is a true preview: messages are rendered to the outbox so you can read
    them, but nothing is marked sent, no candidate stage moves, and no cap is
    spent. A live send always commits. `commit` defaults to `live`, so
    `outbound send` without --live previews and changes nothing, which is what
    the operator expects. The demo and tests pass commit=True to walk the
    funnel offline.
    """
    if commit is None:
        commit = live
    result = StepResult(step=f"send[{role.key}]")
    if live:
        assert_sendable(settings, role, attest_warmup=attest_warmup)
        ok, why = can_send_now(settings)
        if not ok and not ignore_window:
            raise SafetyStop(f"not sending: {why}. Use --ignore-window to override.")

    name = str(settings.get("providers.send", "dryrun")) if live else "dryrun"
    provider = provider_registry.build("send", name, settings)
    # A preview always renders through the dryrun provider, whatever
    # providers.send is, so nothing can leave the machine.
    preview_provider = (
        provider if name == "dryrun"
        else provider_registry.build("send", "dryrun", settings)
    )

    day = sending_day(settings)
    requeued = db.requeue_failed(role.key, max_attempts=int(settings.get("limits.send_attempts", 3)))
    if requeued:
        result.notes.append(f"put {requeued} previously failed message(s) back in the queue")

    stop = bounce_guard(settings, db)
    if stop:
        raise SafetyStop(stop)

    already_role = db.sends_today(role.key, day)
    already_domain = db.sends_today_all_roles(day)
    role_room = max(0, daily_cap(settings, role) - already_role)
    domain_room = max(0, domain_cap(settings) - already_domain)
    room = min(role_room, domain_room)

    warm_cap, warm_note = warmup_cap(settings, db)
    if warm_cap >= 0:
        room = min(room, max(0, warm_cap - already_domain))
        result.notes.append(warm_note)
    if limit is not None:
        room = min(room, limit)
    room = min(room, int(settings.get("limits.max_sends_per_run", 60)))
    if room <= 0:
        if warm_cap >= 0 and already_domain >= warm_cap:
            result.notes.append(
                f"warm up cap reached: {already_domain}/{warm_cap} sent today. "
                f"{warm_note}"
            )
        elif domain_room <= 0:
            result.notes.append(
                f"domain cap reached: {already_domain}/{domain_cap(settings)} sent from "
                f"the sending domain today, across all roles"
            )
        else:
            result.notes.append(
                f"role cap reached: {already_role}/{daily_cap(settings, role)} sent for "
                f"{role.key} today"
            )
        return result

    due = db.query(
        "SELECT * FROM messages WHERE role_key = ? AND status = 'queued' "
        "AND (send_after IS NULL OR send_after <= ?) ORDER BY send_after ASC, id ASC LIMIT ?",
        (role.key, iso(), room),
    )
    identity = settings.section("identity")
    # sending.stop_on names the stages that halt a sequence. Anything terminal
    # halts it too, whether or not it is listed.
    stop_stages = {
        str(x) for x in (settings.get("sending.stop_on", []) or [])
    } | TERMINAL_STAGES | {"confirmed", "screened"}
    for message in due:
        candidate = db.candidate(int(message["candidate_id"]))
        if candidate and candidate["stage"] in stop_stages:
            db.execute("UPDATE messages SET status = 'skipped' WHERE id = ?", (message["id"],))
            result.bump("skipped_stage")
            continue
        if db.is_suppressed("email", message["to_address"]):
            db.execute("UPDATE messages SET status = 'skipped' WHERE id = ?", (message["id"],))
            result.bump("skipped_suppressed")
            continue
        payload = {
            "to": message["to_address"],
            "from": f"{identity.get('from_name','')} <{identity.get('from_email','')}>",
            "reply_to": identity.get("reply_to") or identity.get("from_email"),
            "subject": message["subject"],
            "body": message["body"],
            "step": message["step"],
            "role_key": role.key,
            "candidate_id": message["candidate_id"],
            "variant": message.get("variant", "a"),
        }
        if not commit:
            # Preview: render to the outbox so it can be read, but record
            # nothing and leave the message queued.
            preview_provider.send(payload)
            result.bump("previewed")
            continue
        try:
            provider_id = provider.send(payload)
        except Exception as exc:
            db.mark_failed(int(message["id"]), str(exc))
            result.bump("failed")
            result.notes.append(f"message {message['id']}: {exc}")
            continue
        db.mark_sent(int(message["id"]), name, str(provider_id))
        db.record_send(role.key, day)
        if candidate:
            db.set_stage(int(candidate["id"]), "sent", f"step {message['step']} sent")
        result.bump("sent")
    if not commit:
        result.notes.append(
            "PREVIEW. Messages were written to the outbox to read; nothing was "
            "sent, no stage moved, no cap spent. Pass --live to send."
        )
    elif not live:
        result.notes.append(
            "DRY RUN (committed). Messages went to the outbox and the funnel "
            "advanced, but nothing left this machine. Pass --live to send for real."
        )
    return result
