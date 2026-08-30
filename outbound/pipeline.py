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
from .db import Database
from .errors import ComplianceError, OutboundError, SafetyStop
from .profiles import normalize
from .score import route, score_profile
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
        db.execute(
            "UPDATE candidates SET score = ?, score_json = ?, stage = ?, updated_at = ? WHERE id = ?",
            (outcome.score, outcome.to_json(), target, iso(), row["id"]),
        )
        result.bump(target)
        if outcome.disqualified:
            result.bump(f"dq:{outcome.disqualifier}")
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


def daily_cap(settings: Settings, role: Role) -> int:
    per_box = int(settings.get("sending.per_mailbox_per_day", 18))
    boxes = max(1, int(settings.get("sending.mailboxes", 1)))
    return min(role.daily_cap, per_box * boxes)


def queue_next(
    db: Database, settings: Settings, role: Role, limit: int | None = None
) -> StepResult:
    """Render and queue the next due message for every eligible candidate."""
    result = StepResult(step=f"queue[{role.key}]")
    steps = steps_available(role)
    if not steps:
        raise OutboundError(f"no templates in templates/{role.template_dir}/")
    gaps = [int(g) for g in settings.get("sending.step_gap_days", [0, 4, 8]) or [0]]
    cap = limit or int(settings.get("limits.max_sends_per_run", 60)) * 3

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
            rendered.subject, rendered.body, iso(),
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
        try:
            rendered = render(settings, role, dict(row), email["address"], next_step)
        except OutboundError as exc:
            result.notes.append(f"id {row['id']} step {next_step}: {exc}")
            result.bump("render_failed")
            continue
        db.queue_message(
            row["id"], role.key, next_step, email["address"],
            rendered.subject, rendered.body, iso(due),
        )
        result.bump(f"queued_step{next_step}")
    return result


def send_due(
    db: Database,
    settings: Settings,
    role: Role,
    live: bool = False,
    limit: int | None = None,
    attest_warmup: bool = False,
    ignore_window: bool = False,
) -> StepResult:
    """Send every queued message that is due, up to the daily cap.

    `live` is the safety switch. Without it the send goes through the dry run
    provider and lands in the outbox, whatever `providers.send` says.
    """
    result = StepResult(step=f"send[{role.key}]")
    if live:
        assert_sendable(settings, role, attest_warmup=attest_warmup)
        ok, why = can_send_now(settings)
        if not ok and not ignore_window:
            raise SafetyStop(f"not sending: {why}. Use --ignore-window to override.")

    name = str(settings.get("providers.send", "dryrun")) if live else "dryrun"
    provider = provider_registry.build("send", name, settings)

    day = sending_day(settings)
    already = db.sends_today(role.key, day)
    cap = daily_cap(settings, role)
    room = max(0, cap - already)
    if limit is not None:
        room = min(room, limit)
    room = min(room, int(settings.get("limits.max_sends_per_run", 60)))
    if room <= 0:
        result.notes.append(f"daily cap reached: {already}/{cap} already sent today")
        return result

    due = db.query(
        "SELECT * FROM messages WHERE role_key = ? AND status = 'queued' "
        "AND (send_after IS NULL OR send_after <= ?) ORDER BY send_after ASC, id ASC LIMIT ?",
        (role.key, iso(), room),
    )
    identity = settings.section("identity")
    for message in due:
        candidate = db.candidate(int(message["candidate_id"]))
        if candidate and candidate["stage"] in ("unsubscribed", "bounced", "replied", "booked", "stopped", "rejected"):
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
        }
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
    if not live:
        result.notes.append("DRY RUN. Nothing left this machine. Pass --live to send.")
    return result
