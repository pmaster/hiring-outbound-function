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

    # The sample profiles only cover three roles. Nine are configured; running
    # all of them here would print six empty results and teach nothing.
    demo_keys = ("head-of-operations", "engineer", "ops-generalist")
    live_roles = [roles[k] for k in demo_keys if k in roles and roles[k].is_live]
    other = [r.key for r in roles.values() if r.is_live and r.key not in demo_keys]
    if other:
        print(f"Nine roles are configured. This demo uses the three with sample data:")
        print(f"  {', '.join(r.key for r in live_roles)}")
        print(f"Also live, with no sample list: {', '.join(sorted(other))}")

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

    _banner("8. REPLIES. Someone answers. Two of these need different handling.")
    from unittest import mock

    from . import replies as replies_mod

    written = sorted(replies_mod.written_addresses(db))
    if len(written) >= 3:
        inbound = [
            replies_mod.Inbound(
                written[0], "Re: the seat",
                "Interesting. I am not looking right now, but what is the comp?",
                "2026-09-01",
            ),
            replies_mod.Inbound(
                written[1], "Re: your note", "Please take me off this list.", "2026-09-01"
            ),
            replies_mod.Inbound(
                "mailer-daemon@example.com", "Undelivered Mail Returned to Sender",
                f"550 5.1.1 <{written[2]}>: Recipient address rejected: User unknown",
                "2026-09-01",
            ),
        ]
        with mock.patch.object(replies_mod, "fetch", lambda settings, since=None: inbound):
            print(replies_mod.sync(db, settings))
        print()
        for row in db.inbox():
            body = " ".join(str(row.get("body") or "").split())
            print(f"  [{row['id']}] {row['kind']:12} {row.get('full_name') or row['from_address']}")
            print(f"      {body[:76]}")
        print()
        print("  The reply is now out of the sequence, the opt out is suppressed, and")
        print("  the bounced address is suppressed too. Nobody gets a follow up they")
        print("  should not.")

    _banner("9. BOOKINGS. Pull them in, then re-check each person against the ICP.")
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

    _banner("10. AUDIT. Is this list ready to commit to?")
    from .audit import audit_role

    print(audit_role(db, settings, live_roles[0]))

    _banner("11. EXPORT. Hand the good ones to the applicant tracking system.")
    from .export import export

    export_path = settings.export_dir / "demo-ats.csv"
    count = export(db, settings, None, export_path, fmt="ats")
    print(f"wrote {count} candidate(s) to {export_path}")
    if count:
        print()
        print(export_path.read_text(encoding="utf-8").split("\n")[0])
        print(export_path.read_text(encoding="utf-8").split("\n")[1][:150])

    _banner("12. REPORT.")
    print(report.summary(db, settings, roles))

    outbox = settings.outbox_dir
    files = sorted(outbox.glob("*.eml")) if outbox.exists() else []
    _banner(f"OUTBOX: {len(files)} message(s) written to {outbox}")
    if files:
        print(files[0].read_text(encoding="utf-8"))
    print()
    print("Nothing was sent. Nothing left this machine.")
    print()
    print("Things this demo did not show, because they need the real world:")
    print("  outbound dns viewlineventures.com   checks SPF, DKIM, DMARC and MX")
    print("  outbound pages                      builds the careers site into site/")
    print("  outbound show <id>                  everything about one person")
    print("  outbound search <role>              the LinkedIn queries to run")
    print()
    print("Next: `python3 -m outbound init`, fill in config/settings.toml,")
    print("then `outbound doctor` will tell you exactly what is still missing.")
    db.close()
    return 0
