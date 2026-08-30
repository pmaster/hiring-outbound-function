"""`outbound demo` runs the whole funnel offline against the sample data.

No API keys, no network, nothing sent. It exists so that the pipeline can be
proved end to end before a single real address is touched, and so a new person
can see what the machine does in one command.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from . import bookings as bookings_mod
from . import pipeline, report
from .config import REPO_ROOT, load_all
from .db import open_db

DEMO_SETTINGS = REPO_ROOT / "sample" / "settings.demo.toml"

NOTES = {
    # id order is stable because the sample file is ordered.
    "Dana Reyes": "You stood up the ops function at Kestrel from nothing, and the 40% error rate drop is the part I want to ask about.",
    "Marcus Oyelaran": "You were the first operations hire at Brightline and built the error log the company still runs on.",
    "Priya Raghunathan": "You launched two regions from scratch at Wexford, and your profile says you follow betting markets.",
    "Jonah Feldt": "You were the founding chief of staff at Arclight and built the task system, which is the exact thing missing here.",
    "Alicia Mbeki": "You built the dispatch playbook at Northgate and cut cycle time 25% on a $30m P&L.",
    "Sasha Lindqvist": "You were employee three at Tessellate and built the admin panel the operations team lives in.",
    "Rob Castellanos": "You built Halyard's back office system end to end and own the ETL behind the ops dashboards.",
    "Nina Abramov": "You built Ledgerline's revenue automation and CRM integrations with two other people.",
    "Terrence Ople": "You own the warehouse and every integration into it at Ravenna, built from scratch.",
    "Bianca Ferreira": "You wrote Copperline's first SOP library and took processing errors down 35%.",
    "Devon Marsh": "You built Tideline's ticketing tiers from nothing and cut first response time 60%.",
    "Yusuf Karim": "You built the chargeback playbook at Northwind and cut false positives 30%.",
    "Hannah Delacroix": "You set up Foxglove's knowledge base and weekly KPI review, and documented every recurring process.",
    "Owen Brady": "You built the daily cash report at Sablefish, and your profile mentions poker.",
    "Sofia Marchetti": "You built Lantern's client health scoring model and took churn down 18%.",
}

STEP = "-" * 68


def _banner(text: str) -> None:
    print()
    print(STEP)
    print(text)
    print(STEP)


def run_demo(reset: bool = True) -> int:
    settings, roles = load_all(DEMO_SETTINGS)
    if reset:
        for directory in (settings.db_path.parent, settings.outbox_dir):
            if directory.exists() and "demo" in str(directory):
                shutil.rmtree(directory)
    db = open_db(settings.db_path)

    live_roles = [r for r in roles.values() if r.is_live]

    _banner("1. SOURCE. Pull profiles from the search provider (dryrun reads sample/profiles.jsonl).")
    for role in live_roles:
        print(pipeline.run_search(db, settings, role))

    _banner("2. SCORE. Every profile against that role's ICP.")
    for role in live_roles:
        print(pipeline.score_all(db, settings, role))

    _banner("3. HAND REVIEW. A person reads the profile and writes the one specific detail.")
    approved = 0
    for role in live_roles:
        for row in db.candidates(role.key, stages=["review"]):
            note = NOTES.get(str(row.get("full_name") or ""))
            if not note:
                pipeline.set_review(db, role, int(row["id"]), "reject",
                                    "no specific detail worth writing about")
                continue
            pipeline.set_review(db, role, int(row["id"]), "approve", note)
            approved += 1
    print(f"approved {approved} by hand, rejected the rest for want of a specific detail")

    _banner("4. ENRICH. Find a work address for everyone approved.")
    for role in live_roles:
        print(pipeline.enrich(db, settings, role))

    _banner("5. VERIFY. Check the addresses before writing to them.")
    for role in live_roles:
        print(pipeline.verify_emails(db, settings, role))

    _banner("6. QUEUE. Render step one for everyone verified.")
    for role in live_roles:
        print(pipeline.queue_next(db, settings, role))

    _banner("7. SEND. Dry run, so the emails land in the outbox instead of a mailbox.")
    for role in live_roles:
        print(pipeline.send_due(db, settings, role, live=False))

    _banner("8. BOOKINGS. Pull them in, then re-check each person against the ICP.")
    print(bookings_mod.sync(db, settings, roles))
    for item in bookings_mod.recheck(db, settings, roles):
        booking = item["booking"]
        score = item["score"]
        print(
            f"  [{booking['id']}] {booking.get('attendee_name'):22} "
            f"score={'n/a' if score is None else f'{score:.2f}'}  suggest={item['suggest']}"
        )
    print()
    print(bookings_mod.triage(db, settings, roles, auto=True, live=False))

    _banner("9. REPORT.")
    print(report.summary(db, settings, roles))

    outbox = settings.outbox_dir
    files = sorted(outbox.glob("*.eml")) if outbox.exists() else []
    _banner(f"OUTBOX: {len(files)} message(s) written to {outbox}")
    if files:
        print(files[0].read_text(encoding="utf-8"))
    print()
    print("Nothing was sent. Nothing left this machine.")
    print("Next: `python3 -m outbound init`, fill in config/settings.toml, then `outbound doctor`.")
    db.close()
    return 0
