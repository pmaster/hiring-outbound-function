"""Command line. One verb per funnel step, plus `doctor` and `demo`.

    python3 -m outbound doctor
    python3 -m outbound search head-of-operations
    python3 -m outbound import head-of-operations list.csv
    python3 -m outbound score head-of-operations
    python3 -m outbound review head-of-operations
    python3 -m outbound enrich head-of-operations
    python3 -m outbound verify head-of-operations
    python3 -m outbound queue head-of-operations
    python3 -m outbound send head-of-operations --live
    python3 -m outbound bookings triage
    python3 -m outbound report
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from . import bookings as bookings_mod
from . import pipeline, report
from .compliance import preflight
from .config import CONFIG_DIR, REPO_ROOT, Role, Settings, get_role, load_all
from .db import Database, open_db
from .errors import OutboundError
from .search import render_plan
from .util import iso, truncate

DEMO_SETTINGS = REPO_ROOT / "sample" / "settings.demo.toml"


def _bootstrap(args: argparse.Namespace) -> tuple[Settings, dict[str, Role], Database]:
    settings_path = Path(args.config) if args.config else None
    settings, roles = load_all(settings_path)
    db = open_db(settings.db_path)
    return settings, roles, db


def _print(result: Any) -> None:
    print(result)


# ------------------------------------------------------------------ verbs


def cmd_init(args: argparse.Namespace) -> int:
    target = CONFIG_DIR / "settings.toml"
    example = CONFIG_DIR / "settings.example.toml"
    if target.exists():
        print(f"{target} already exists, leaving it alone.")
    else:
        shutil.copy(example, target)
        print(f"created {target}. Edit it: identity, booking.screener_url, and comp.")
    env = REPO_ROOT / ".env"
    if not env.exists() and (REPO_ROOT / ".env.example").exists():
        shutil.copy(REPO_ROOT / ".env.example", env)
        print(f"created {env}. Put API keys there. It is gitignored.")
    settings, roles = load_all(Path(args.config) if args.config else None)
    db = open_db(settings.db_path)
    print(f"database ready at {settings.db_path}")
    print(f"{len(roles)} roles loaded: {', '.join(sorted(roles))}")
    db.close()
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    settings, roles = load_all(Path(args.config) if args.config else None)
    role = get_role(roles, args.role) if args.role else None
    problems = preflight(settings, role)
    if not problems:
        print("all checks passed. You can send.")
        return 0
    fatal = [p for p in problems if p.fatal]
    for problem in problems:
        print(problem)
    print()
    print(f"{len(fatal)} blocking, {len(problems) - len(fatal)} to confirm.")
    return 1 if fatal else 0


def cmd_roles(args: argparse.Namespace) -> int:
    _settings, roles = load_all(Path(args.config) if args.config else None)
    width = max(len(k) for k in roles)
    print(f"{'key':<{width}}  {'status':8} {'seats':>5}  {'sender':10} comp")
    for key in sorted(roles):
        role = roles[key]
        print(
            f"{key:<{width}}  {role.status:8} {role.seats:5d}  {role.sender:10} {role.comp}"
        )
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    settings, roles, db = _bootstrap(args)
    role = get_role(roles, args.role)
    if args.run:
        _print(pipeline.run_search(db, settings, role, only=args.only, limit=args.limit))
    else:
        print(render_plan(role, settings))
    db.close()
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    settings, roles, db = _bootstrap(args)
    role = get_role(roles, args.role)
    path = Path(args.file)
    if not path.exists():
        raise OutboundError(f"no such file: {path}")
    rows = pipeline.read_any(path)
    _print(pipeline.import_rows(db, settings, role, rows, source=f"file:{path.name}"))
    db.close()
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    settings, roles, db = _bootstrap(args)
    role = get_role(roles, args.role)
    _print(pipeline.score_all(db, settings, role, restage=args.restage))
    db.close()
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    settings, roles, db = _bootstrap(args)
    role = get_role(roles, args.role)
    if args.export:
        path = Path(args.export)
        count = pipeline.export_review(db, role, path, limit=args.limit)
        print(f"wrote {count} candidate(s) to {path}")
        print("Fill in `decision` (approve or reject) and `personal_note`, then:")
        print(f"  python3 -m outbound review {role.key} --import-file {path}")
        db.close()
        return 0
    if args.import_file:
        path = Path(args.import_file)
        if not path.exists():
            raise OutboundError(f"no such file: {path}")
        _print(pipeline.import_review(db, role, path))
        db.close()
        return 0
    if args.approve or args.reject:
        target = args.approve or args.reject
        decision = "approve" if args.approve else "reject"
        outcome = pipeline.set_review(db, role, int(target), decision, args.note or "")
        print(f"candidate {target}: {outcome}")
        db.close()
        return 0
    rows = db.candidates(role.key, stages=["review"], limit=args.limit)
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        db.close()
        return 0
    if not rows:
        print(f"nothing waiting for review on {role.key}.")
        db.close()
        return 0
    print(f"{len(rows)} waiting on {role.key}. Read the profile before you approve.\n")
    for row in rows:
        score = row.get("score") or 0.0
        print(f"[{row['id']:>5}] {score:.2f}  {row.get('full_name') or '?'}")
        print(f"        {truncate(str(row.get('title') or ''), 60)} at {truncate(str(row.get('company') or ''), 40)}")
        print(f"        {row.get('location') or 'location unknown'}  |  {row.get('linkedin_url') or 'no profile url'}")
        try:
            detail = json.loads(row.get("score_json") or "{}")
            top = sorted(detail.get("signals", []), key=lambda s: -s["contribution"])[:3]
            print("        " + ", ".join(f"{s['key']} {s['contribution']:+.2f}" for s in top))
        except json.JSONDecodeError:
            pass
        if row.get("personal_note"):
            print(f"        note: {truncate(row['personal_note'], 90)}")
        print()
    print("Approve with a note, which becomes line one of the email:")
    print(f"  python3 -m outbound review {role.key} --approve <id> --note \"...\"")
    print(f"  python3 -m outbound review {role.key} --reject <id> --note \"why\"")
    db.close()
    return 0


def cmd_questions(args: argparse.Namespace) -> int:
    """Print the screener booking form questions, ready to paste."""
    _settings, roles = load_all(Path(args.config) if args.config else None)
    role = get_role(roles, args.role)
    if not role.booking_questions:
        print(f"{role.key} has no booking questions. Add them under [booking] in {role.path}.")
        return 1
    print(f"Booking form questions for {role.title}. All four required.\n")
    for index, question in enumerate(role.booking_questions, start=1):
        print(f"{index}. {question}")
    print()
    print(
        "Put these on the screener booking page as required questions. Reviewing "
        "the answers each morning is cheaper than cancelling a booked call."
    )
    return 0


def cmd_enrich(args: argparse.Namespace) -> int:
    settings, roles, db = _bootstrap(args)
    role = get_role(roles, args.role)
    _print(pipeline.enrich(db, settings, role, limit=args.limit))
    db.close()
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    settings, roles, db = _bootstrap(args)
    role = get_role(roles, args.role)
    _print(pipeline.verify_emails(db, settings, role, limit=args.limit, accept_risky=args.accept_risky))
    db.close()
    return 0


def cmd_queue(args: argparse.Namespace) -> int:
    settings, roles, db = _bootstrap(args)
    role = get_role(roles, args.role)
    _print(pipeline.queue_next(db, settings, role, limit=args.limit))
    db.close()
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    settings, roles, db = _bootstrap(args)
    role = get_role(roles, args.role)
    _print(
        pipeline.send_due(
            db, settings, role,
            live=args.live, limit=args.limit,
            attest_warmup=args.attest_warmup, ignore_window=args.ignore_window,
        )
    )
    db.close()
    return 0


def cmd_bookings(args: argparse.Namespace) -> int:
    settings, roles, db = _bootstrap(args)
    if args.action == "sync":
        _print(bookings_mod.sync(db, settings, roles))
    elif args.action == "list":
        rows = db.query("SELECT * FROM bookings ORDER BY start_at ASC")
        if not rows:
            print("no bookings.")
        for row in rows:
            print(
                f"[{row['id']:>4}] {row['status']:10} {row.get('start_at') or '?':25} "
                f"{row.get('attendee_name') or '?':24} {row.get('attendee_email') or ''}"
            )
    elif args.action == "triage":
        items = bookings_mod.recheck(db, settings, roles)
        if not items:
            print("no bookings waiting.")
        for item in items:
            booking = item["booking"]
            score = item["score"]
            print(
                f"[{booking['id']:>4}] {booking.get('start_at') or '?':25} "
                f"{booking.get('attendee_name') or '?':22} "
                f"score={'n/a' if score is None else f'{score:.2f}'}  "
                f"suggest={item['suggest']}"
            )
            if item["linkedin"]:
                print(f"       {item['linkedin']}")
            for question, answer in (item["answers"] or {}).items():
                print(f"       Q: {truncate(str(question), 70)}")
                print(f"       A: {truncate(str(answer), 70)}")
            print()
        if args.auto:
            _print(bookings_mod.triage(db, settings, roles, auto=True, live=args.live))
        else:
            print("Decide one at a time:")
            print("  python3 -m outbound bookings decide <id> confirm")
            print("  python3 -m outbound bookings decide <id> cancel --reason \"...\" --live")
            print("Or act on every suggestion at once with --auto.")
    elif args.action == "decide":
        if args.booking_id is None or not args.decision:
            raise OutboundError("decide needs a booking id and confirm or cancel")
        _print(
            bookings_mod.decide(
                db, settings, roles, int(args.booking_id), args.decision,
                reason=args.reason or "", live=args.live,
            )
        )
    else:
        raise OutboundError(f"unknown bookings action {args.action!r}")
    db.close()
    return 0


def cmd_replies(args: argparse.Namespace) -> int:
    from . import replies as replies_mod

    settings, _roles, db = _bootstrap(args)
    if args.action == "sync":
        _print(replies_mod.sync(db, settings, since=args.since))
    elif args.action == "mark":
        if not args.address:
            raise OutboundError("mark needs an address")
        kind = args.kind or "replied"
        if replies_mod.apply(db, kind, args.address, note=args.note or "marked by hand"):
            print(f"{args.address} marked {kind}")
        else:
            print(f"no candidate found on {args.address}")
    else:
        raise OutboundError(f"unknown replies action {args.action!r}")
    db.close()
    return 0


def cmd_suppress(args: argparse.Namespace) -> int:
    settings, _roles, db = _bootstrap(args)
    if args.from_file:
        path = Path(args.from_file)
        if not path.exists():
            raise OutboundError(f"no such file: {path}")
        added = 0
        for row in pipeline.read_any(path):
            value = ""
            if isinstance(row, dict):
                for key in ("email", "address", "email_address", "value", "Email"):
                    if row.get(key):
                        value = str(row[key])
                        break
                if not value:
                    # A one column export with an unknown header.
                    values = [v for v in row.values() if isinstance(v, str) and "@" in v]
                    value = values[0] if values else ""
            else:
                value = str(row)
            if not value:
                continue
            db.suppress(args.kind, value, args.reason or f"imported from {path.name}")
            added += 1
        print(f"suppressed {added} {args.kind} value(s) from {path}")
        db.close()
        return 0
    if not args.value:
        raise OutboundError("give a value, or --from-file")
    db.suppress(args.kind, args.value, args.reason or "added by hand")
    print(f"suppressed {args.kind} {args.value}")
    db.close()
    return 0


def cmd_pages(args: argparse.Namespace) -> int:
    """Build the careers page, the job descriptions and the unsubscribe page."""
    from .pages import build_all

    settings, roles = load_all(Path(args.config) if args.config else None)
    written = build_all(settings, roles, Path(args.out) if args.out else None)
    for path in written:
        print(f"wrote {path}")
    print()
    print("Upload this directory to the recruiting domain. Not to a live brand")
    print("domain, and do not redirect it to one. See docs/OPSEC.md.")
    print("Then point the unsubscribe form action at something that records the")
    print("address, and set each role's jd_url in config/settings.toml.")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    settings, roles, db = _bootstrap(args)
    role_key = get_role(roles, args.role).key if args.role else None
    print(report.summary(db, settings, roles, role_key))
    db.close()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Run the whole funnel offline against the sample data."""
    from .demo import run_demo

    return run_demo(reset=not args.keep)


# ------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="outbound", description="Outbound recruiting pipeline."
    )
    parser.add_argument("--config", help="path to a settings TOML file")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create settings.toml and the database").set_defaults(func=cmd_init)

    doctor = sub.add_parser("doctor", help="check everything that must be true before a send")
    doctor.add_argument("role", nargs="?")
    doctor.set_defaults(func=cmd_doctor)

    sub.add_parser("roles", help="list the roles").set_defaults(func=cmd_roles)

    search = sub.add_parser("search", help="print the sourcing plan, or run the provider")
    search.add_argument("role")
    search.add_argument("--run", action="store_true", help="run providers.search instead of printing")
    search.add_argument("--only", nargs="*", help="only these named searches")
    search.add_argument("--limit", type=int)
    search.set_defaults(func=cmd_search)

    imp = sub.add_parser("import", help="import profiles from CSV, JSON or JSONL")
    imp.add_argument("role")
    imp.add_argument("file")
    imp.set_defaults(func=cmd_import)

    score = sub.add_parser("score", help="score sourced candidates against the ICP")
    score.add_argument("role")
    score.add_argument("--restage", action="store_true", help="re-score everyone, not just new")
    score.set_defaults(func=cmd_score)

    review = sub.add_parser("review", help="the hand review queue")
    review.add_argument("role")
    review.add_argument("--limit", type=int, default=25)
    review.add_argument("--json", action="store_true")
    review.add_argument("--approve", type=int, metavar="ID")
    review.add_argument("--reject", type=int, metavar="ID")
    review.add_argument("--note")
    review.add_argument("--export", metavar="FILE", help="write the queue to a CSV to work through offline")
    review.add_argument("--import-file", dest="import_file", metavar="FILE", help="read a filled in review CSV back")
    review.set_defaults(func=cmd_review)

    questions = sub.add_parser("questions", help="print the screener booking form questions")
    questions.add_argument("role")
    questions.set_defaults(func=cmd_questions)

    enrich = sub.add_parser("enrich", help="find work emails for approved candidates")
    enrich.add_argument("role")
    enrich.add_argument("--limit", type=int)
    enrich.set_defaults(func=cmd_enrich)

    verify = sub.add_parser("verify", help="verify the addresses")
    verify.add_argument("role")
    verify.add_argument("--limit", type=int)
    verify.add_argument(
        "--accept-risky", action="store_true",
        help="promote addresses already checked as risky, catch_all or unknown",
    )
    verify.set_defaults(func=cmd_verify)

    queue = sub.add_parser("queue", help="render and queue the next due message")
    queue.add_argument("role")
    queue.add_argument("--limit", type=int)
    queue.set_defaults(func=cmd_queue)

    send = sub.add_parser("send", help="send what is due, up to the daily cap")
    send.add_argument("role")
    send.add_argument("--live", action="store_true", help="actually send. Without this it is a dry run.")
    send.add_argument("--limit", type=int)
    send.add_argument("--attest-warmup", action="store_true", help="confirm mailbox warm up is done")
    send.add_argument("--ignore-window", action="store_true")
    send.set_defaults(func=cmd_send)

    book = sub.add_parser("bookings", help="sync, re-check, confirm or cancel bookings")
    book.add_argument("action", choices=["sync", "list", "triage", "decide"])
    book.add_argument("booking_id", nargs="?", type=int)
    book.add_argument("decision", nargs="?", choices=["confirm", "cancel"])
    book.add_argument("--reason")
    book.add_argument("--auto", action="store_true", help="act on every suggestion")
    book.add_argument("--live", action="store_true")
    book.set_defaults(func=cmd_bookings)

    replies = sub.add_parser("replies", help="detect replies and bounces, and stop their follow ups")
    replies.add_argument("action", choices=["sync", "mark"])
    replies.add_argument("address", nargs="?")
    replies.add_argument("--kind", choices=["replied", "bounced", "unsubscribed", "stopped"])
    replies.add_argument("--since", help="ISO timestamp. Default: the first send.")
    replies.add_argument("--note")
    replies.set_defaults(func=cmd_replies)

    suppress = sub.add_parser("suppress", help="never contact this address, domain or profile")
    suppress.add_argument("value", nargs="?")
    suppress.add_argument("--from-file", help="CSV, JSON or JSONL of unsubscribes to import")
    suppress.add_argument("--kind", choices=["email", "domain", "linkedin"], default="email")
    suppress.add_argument("--reason")
    suppress.set_defaults(func=cmd_suppress)

    pages = sub.add_parser("pages", help="build the careers page and the job descriptions")
    pages.add_argument("--out", help="output directory (default: site/)")
    pages.set_defaults(func=cmd_pages)

    rep = sub.add_parser("report", help="funnel, conversion and what to do next")
    rep.add_argument("role", nargs="?")
    rep.set_defaults(func=cmd_report)

    demo = sub.add_parser("demo", help="run the whole funnel offline on sample data")
    demo.add_argument("--keep", action="store_true", help="do not reset the demo database")
    demo.set_defaults(func=cmd_demo)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except OutboundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
