"""Tests. Standard library unittest, no runner to install.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from outbound import pipeline  # noqa: E402
from outbound import bookings as bookings_mod  # noqa: E402
from outbound.compliance import geo_allowed, message_problems, preflight  # noqa: E402
from outbound.compose import lint, render, steps_available  # noqa: E402
from outbound.config import ConfigError, Settings, load_all, load_roles  # noqa: E402
from outbound.db import open_db  # noqa: E402
from outbound.errors import ComplianceError, OutboundError, SafetyStop  # noqa: E402
from outbound.profiles import derive_history, guess_country, normalize  # noqa: E402
from outbound.score import matches_any, route, score_profile  # noqa: E402
from outbound.util import norm_linkedin, name_parts, token_for  # noqa: E402

DEMO_SETTINGS = ROOT / "sample" / "settings.demo.toml"

# Everything a candidate reads before the NDA is T1. It may say "a small
# trading firm in alternative assets, around fifty people" and nothing that
# names the domain, the client model or the fund flow.
# See projects/sunbird/employee-pitch.md, Version 1.
# Only unambiguous tells belong here. Ordinary words that happen to appear in
# gambling ("bonus", "trading") are not tells, and firing on them would make
# the check useless.
T1_BANNED = [
    "casino", "sportsbook", "bookmaker", "gambling", "betting", "wager",
    "advantage play", "funded account", "promotional offer",
    "under our direction",
]


def _settings_and_roles():
    return load_all(DEMO_SETTINGS)


class TestUtil(unittest.TestCase):
    def test_linkedin_dedupe_key(self):
        variants = [
            "https://www.linkedin.com/in/Jane-Doe-1a2/",
            "http://uk.linkedin.com/in/jane-doe-1a2",
            "linkedin.com/in/jane-doe-1a2/?trk=public",
            "https://LINKEDIN.com/in/jane-doe-1a2#about",
        ]
        keys = {norm_linkedin(v) for v in variants}
        self.assertEqual(keys, {"linkedin.com/in/jane-doe-1a2"})

    def test_name_parts_strips_suffixes(self):
        self.assertEqual(name_parts("Jane Q. Doe, PhD"), ("Jane", "Doe"))
        self.assertEqual(name_parts("Cher"), ("Cher", ""))
        self.assertEqual(name_parts(""), ("", ""))

    def test_unsubscribe_token_is_stable_and_per_domain(self):
        self.assertEqual(token_for("a@b.com", "x"), token_for("a@b.com", "x"))
        self.assertNotEqual(token_for("a@b.com", "x"), token_for("a@b.com", "y"))


class TestProfiles(unittest.TestCase):
    def test_country_from_location(self):
        self.assertEqual(guess_country("Austin, TX"), "US")
        self.assertEqual(guess_country("Warsaw, Poland"), "PL")
        self.assertEqual(guess_country("London, England"), "GB")
        self.assertEqual(guess_country("Remote"), "")

    def test_unknown_country_is_not_guessed_as_us(self):
        self.assertEqual(guess_country("Anywhere"), "")

    def test_history_derivation(self):
        today = _dt.date(2026, 8, 30)
        out = derive_history(
            {
                "positions": [
                    {"title": "A", "startDate": "2024-01", "endDate": None},
                    {"title": "B", "startDate": "2018-01", "endDate": "2023-12"},
                ]
            },
            today=today,
        )
        self.assertAlmostEqual(out["longest_tenure_years"], 5.92, places=1)
        self.assertEqual(out["jobs_last_3_years"], 1)
        self.assertAlmostEqual(out["months_in_current_role"], 31.0, places=0)

    def test_normalize_maps_aliases(self):
        out = normalize({"fullName": "A B", "profileUrl": "https://linkedin.com/in/ab",
                         "companySize": "51-200", "headline": "Head of Ops at X"})
        self.assertEqual(out["first_name"], "A")
        self.assertEqual(out["company_headcount"], 125)
        self.assertEqual(out["title"], "Head of Ops")


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = _settings_and_roles()

    def test_word_boundary_matching(self):
        self.assertEqual(matches_any("Operations Coordinator", ["coo"]), [])
        self.assertEqual(matches_any("COO, Acme", ["coo"]), ["coo"])

    def test_excluded_title_is_a_hard_reject(self):
        role = self.roles["head-of-operations"]
        profile = normalize({"fullName": "X Y", "headline": "Operations Coordinator at Z",
                             "profileUrl": "https://linkedin.com/in/xy", "location": "Austin, TX"})
        result = score_profile(role, profile, allowed_countries={"US"})
        self.assertTrue(result.disqualified)
        self.assertEqual(result.disqualifier, "icp_title_excluded")

    def test_blocked_country_is_a_hard_reject(self):
        role = self.roles["head-of-operations"]
        profile = normalize({"fullName": "A N", "headline": "Director of Operations at Z",
                             "profileUrl": "https://linkedin.com/in/an", "location": "Warsaw, Poland"})
        result = score_profile(role, profile, blocked_countries={"PL"}, allowed_countries={"US"})
        self.assertTrue(result.disqualified)
        self.assertEqual(result.disqualifier, "blocked_geo")

    def test_unknown_country_is_rejected_not_assumed(self):
        role = self.roles["head-of-operations"]
        profile = normalize({"fullName": "A N", "headline": "Director of Operations at Z",
                             "profileUrl": "https://linkedin.com/in/an2", "location": "Remote"})
        result = score_profile(role, profile, blocked_countries=set(), allowed_countries={"US"})
        self.assertTrue(result.disqualified)

    def test_strong_profile_outscores_weak_one(self):
        role = self.roles["head-of-operations"]
        strong = normalize({"fullName": "S T", "headline": "Head of Operations at Kestrel",
                            "profileUrl": "https://linkedin.com/in/st", "location": "Austin, TX",
                            "companySize": "51-200",
                            "summary": "Built the ops function from scratch, owned P&L, led 22 people.",
                            "positions": [{"title": "Head of Operations", "startDate": "2022-03"},
                                          {"title": "Ops Manager", "startDate": "2016-01", "endDate": "2022-02"}]})
        weak = normalize({"fullName": "W K", "headline": "Head of Operations at Tiny",
                          "profileUrl": "https://linkedin.com/in/wk", "location": "Austin, TX",
                          "companySize": "10001+", "summary": "Day to day scheduling.",
                          "positions": [{"title": "Head of Operations", "startDate": "2025-06"}]})
        a = score_profile(role, strong, allowed_countries={"US"}).score
        b = score_profile(role, weak, allowed_countries={"US"}).score
        self.assertGreater(a, b + 0.2)

    def test_routing_thresholds(self):
        scoring = {"auto_reject_below": 0.45, "auto_approve_above": 0.8, "require_hand_review": True}
        from outbound.score import ScoreResult

        self.assertEqual(route(ScoreResult(score=0.2), scoring), "rejected")
        self.assertEqual(route(ScoreResult(score=0.6), scoring), "review")
        self.assertEqual(route(ScoreResult(score=0.9), scoring), "review")
        scoring["require_hand_review"] = False
        self.assertEqual(route(ScoreResult(score=0.9), scoring), "approved")


class TestDatabase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.db = open_db(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def test_upsert_dedupes_on_normalised_url(self):
        a, created_a = self.db.upsert_candidate("r", {"linkedin_url": "https://uk.linkedin.com/in/Jane/", "full_name": "Jane"})
        b, created_b = self.db.upsert_candidate("r", {"linkedin_url": "linkedin.com/in/jane", "full_name": "Jane"})
        self.assertTrue(created_a)
        self.assertFalse(created_b)
        self.assertEqual(a, b)

    def test_two_namesakes_without_a_profile_url_stay_separate(self):
        a, _ = self.db.upsert_candidate(
            "r", {"full_name": "Chris Taylor", "company": "Acme", "location": "Austin, TX"}
        )
        b, _ = self.db.upsert_candidate(
            "r", {"full_name": "Chris Taylor", "company": "Beta", "location": "Denver, CO"}
        )
        self.assertNotEqual(a, b)

    def test_same_person_two_roles_is_two_rows(self):
        a, _ = self.db.upsert_candidate("r1", {"linkedin_url": "linkedin.com/in/jane", "full_name": "Jane"})
        b, _ = self.db.upsert_candidate("r2", {"linkedin_url": "linkedin.com/in/jane", "full_name": "Jane"})
        self.assertNotEqual(a, b)

    def test_domain_suppression_covers_addresses(self):
        self.db.suppress("domain", "Example.COM", "test")
        self.assertTrue(self.db.is_suppressed("email", "someone@example.com"))
        self.assertFalse(self.db.is_suppressed("email", "someone@other.com"))

    def test_primary_email_prefers_valid(self):
        cid, _ = self.db.upsert_candidate("r", {"linkedin_url": "linkedin.com/in/x", "full_name": "X"})
        self.db.add_email(cid, "guess@x.com", confidence=0.9, primary=True)
        second = self.db.add_email(cid, "real@x.com", confidence=0.5, primary=False)
        self.db.set_verify(int(second), "valid", "test")
        self.assertEqual(self.db.primary_email(cid)["address"], "real@x.com")

    def test_send_log_accumulates(self):
        self.db.record_send("r", "2026-08-30")
        self.db.record_send("r", "2026-08-30", n=3)
        self.assertEqual(self.db.sends_today("r", "2026-08-30"), 4)


class TestCompliance(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = _settings_and_roles()

    def test_geo_gate(self):
        self.assertTrue(geo_allowed(self.settings, "US")[0])
        self.assertFalse(geo_allowed(self.settings, "CA")[0])
        self.assertFalse(geo_allowed(self.settings, "")[0])

    def test_message_needs_unsubscribe_and_postal(self):
        problems = message_problems(self.settings, "hello there")
        codes = {p.code for p in problems}
        self.assertIn("no_unsubscribe", codes)
        self.assertIn("no_postal", codes)

    def test_doctor_catches_a_broken_template(self):
        role = self.roles["engineer"]
        original = role.template_dir
        role.template_dir = "does-not-exist"
        try:
            codes = {p.code for p in preflight(self.settings, role)}
        finally:
            role.template_dir = original
        self.assertIn("no_templates", codes)

    def test_doctor_passes_every_live_role_as_shipped(self):
        for role in self.roles.values():
            if not role.is_live:
                continue
            fatal = [p for p in preflight(self.settings, role) if p.fatal]
            self.assertEqual(fatal, [], f"{role.key}: {[str(p) for p in fatal]}")

    def test_preflight_blocks_a_live_brand_domain(self):
        raw = json.loads(json.dumps(self.settings.raw))
        raw["identity"]["from_email"] = "jobs@viewlineventures.com"
        problems = preflight(Settings(raw=raw), None)
        self.assertIn("forbidden_domain", {p.code for p in problems})

    def test_preflight_blocks_unset_comp_when_comp_goes_in_the_email(self):
        _settings, roles = load_all(DEMO_SETTINGS)
        role = roles["head-of-operations"]
        role.comp = "NEEDS_PETER"
        problems = preflight(self.settings, role)
        self.assertIn("no_comp", {p.code for p in problems})


class TestCompose(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = _settings_and_roles()
        self.candidate = {
            "id": 1, "first_name": "Dana", "last_name": "Reyes", "full_name": "Dana Reyes",
            "title": "Head of Operations", "company": "Kestrel",
            "personal_note": "You stood up the ops function at Kestrel from nothing.",
        }

    def test_every_live_template_renders_and_passes_the_linter(self):
        for role in self.roles.values():
            for step in steps_available(role):
                out = render(self.settings, role, self.candidate, "d@x.com", step, strict=True)
                self.assertTrue(out.subject)
                self.assertIn("unsubscribe", out.body.lower())
                self.assertIn(self.settings.get("identity.postal_address"), out.body)

    def test_no_template_leaks_above_the_nda_line(self):
        for role in self.roles.values():
            for step in steps_available(role):
                out = render(self.settings, role, self.candidate, "d@x.com", step)
                low = f"{out.subject}\n{out.body}".lower()
                for word in T1_BANNED:
                    self.assertNotIn(
                        word, low,
                        f"{role.key} step {step} leaks {word!r} above the NDA line",
                    )

    def test_step_one_refuses_without_a_personal_note(self):
        candidate = dict(self.candidate, personal_note="")
        with self.assertRaises(OutboundError):
            render(self.settings, self.roles["head-of-operations"], candidate, "d@x.com", 1)

    def test_linter_catches_em_dash_and_ai_tells(self):
        problems = lint("Hi", "I hope this email finds you well — really.")
        self.assertTrue(any("em or en dash" in p for p in problems))
        self.assertTrue(any("banned phrase" in p for p in problems))

    def test_unknown_token_is_an_error(self):
        from outbound.compose import render_text

        with self.assertRaises(ConfigError):
            render_text("hello {{nope}}", {"first_name": "A"}, "test")


class TestPipeline(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = _settings_and_roles()
        self.dir = tempfile.TemporaryDirectory()
        self.db = open_db(Path(self.dir.name) / "t.db")
        self.role = self.roles["head-of-operations"]

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def _seed(self):
        pipeline.run_search(self.db, self.settings, self.role)
        pipeline.score_all(self.db, self.settings, self.role)

    def test_search_score_and_route(self):
        self._seed()
        counts = self.db.funnel(self.role.key)
        self.assertGreater(counts["review"], 0)
        self.assertGreater(counts["rejected"], 0)

    def test_import_is_idempotent(self):
        rows = pipeline.read_any(ROOT / "sample" / "profiles.jsonl")
        first = pipeline.import_rows(self.db, self.settings, self.role, rows, "test")
        second = pipeline.import_rows(self.db, self.settings, self.role, rows, "test")
        self.assertEqual(first.counts.get("created"), len(rows))
        self.assertEqual(second.counts.get("created", 0), 0)
        self.assertEqual(second.counts.get("updated"), len(rows))

    def test_review_csv_round_trip(self):
        import csv as _csv

        self._seed()
        out = Path(self.dir.name) / "review.csv"
        count = pipeline.export_review(self.db, self.role, out)
        self.assertGreater(count, 0)
        with out.open(encoding="utf-8") as handle:
            rows = list(_csv.DictReader(handle))
        self.assertEqual(len(rows), count)
        for index, row in enumerate(rows):
            row["decision"] = "approve" if index == 0 else "reject"
            row["personal_note"] = "A specific detail." if index == 0 else ""
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = _csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        result = pipeline.import_review(self.db, self.role, out)
        self.assertEqual(result.counts.get("approved"), 1)
        self.assertEqual(result.counts.get("rejected"), len(rows) - 1)

    def test_review_import_refuses_approve_without_a_note(self):
        import csv as _csv

        self._seed()
        out = Path(self.dir.name) / "review.csv"
        pipeline.export_review(self.db, self.role, out)
        with out.open(encoding="utf-8") as handle:
            rows = list(_csv.DictReader(handle))
        rows[0]["decision"] = "approve"
        rows[0]["personal_note"] = ""
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = _csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows[:1])
        result = pipeline.import_review(self.db, self.role, out)
        self.assertEqual(result.counts.get("refused"), 1)

    def test_approving_without_a_note_is_refused(self):
        self._seed()
        row = self.db.candidates(self.role.key, stages=["review"])[0]
        with self.assertRaises(OutboundError):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve")

    def test_full_run_to_outbox_and_no_double_send(self):
        self._seed()
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a specific detail")
        pipeline.enrich(self.db, self.settings, self.role)
        pipeline.verify_emails(self.db, self.settings, self.role)
        pipeline.queue_next(self.db, self.settings, self.role)
        first = pipeline.send_due(self.db, self.settings, self.role, live=False)
        self.assertGreater(first.counts.get("sent", 0), 0)
        second = pipeline.send_due(self.db, self.settings, self.role, live=False)
        self.assertEqual(second.counts.get("sent", 0), 0)

    def test_role_cap_is_enforced(self):
        day = pipeline.sending_day(self.settings)
        cap = pipeline.daily_cap(self.settings, self.role)
        self.db.record_send(self.role.key, day, n=cap)
        result = pipeline.send_due(self.db, self.settings, self.role, live=False)
        self.assertEqual(result.counts.get("sent", 0), 0)
        self.assertTrue(any("role cap" in n for n in result.notes), result.notes)

    def test_another_role_eats_the_shared_domain_cap(self):
        """The mailboxes are shared, so one role's sends limit another's."""
        day = pipeline.sending_day(self.settings)
        self.db.record_send("some-other-role", day, n=pipeline.domain_cap(self.settings))
        result = pipeline.send_due(self.db, self.settings, self.role, live=False)
        self.assertEqual(result.counts.get("sent", 0), 0)
        self.assertTrue(any("domain cap" in n for n in result.notes), result.notes)

    def test_a_failed_send_is_retried_then_given_up_on(self):
        self._seed()
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a detail")
        pipeline.enrich(self.db, self.settings, self.role)
        pipeline.verify_emails(self.db, self.settings, self.role)
        pipeline.queue_next(self.db, self.settings, self.role)
        queued = self.db.query(
            "SELECT * FROM messages WHERE role_key = ? AND status = 'queued'", (self.role.key,)
        )
        self.assertTrue(queued)
        message_id = int(queued[0]["id"])
        for expected in (1, 2, 3):
            self.db.mark_failed(message_id, "provider down")
            row = self.db.one("SELECT * FROM messages WHERE id = ?", (message_id,))
            self.assertEqual(row["attempts"], expected)
            self.assertEqual(row["status"], "failed")
            requeued = self.db.requeue_failed(self.role.key, max_attempts=3)
            row = self.db.one("SELECT * FROM messages WHERE id = ?", (message_id,))
            if expected < 3:
                self.assertEqual(row["status"], "queued", "should still be retried")
            else:
                self.assertEqual(row["status"], "failed", "should be given up on")
                self.assertEqual(requeued, 0)

    def test_schema_migration_adds_the_attempts_column(self):
        """A database made by version 1 must gain the column, not break."""
        import sqlite3

        legacy = Path(self.dir.name) / "legacy.db"
        conn = sqlite3.connect(legacy)
        conn.executescript(
            "CREATE TABLE messages (id INTEGER PRIMARY KEY, candidate_id INTEGER, "
            "role_key TEXT, step INTEGER, to_address TEXT, subject TEXT, body TEXT, "
            "rendered_at TEXT, send_after TEXT, sent_at TEXT, provider TEXT, "
            "provider_id TEXT, status TEXT, error TEXT);"
        )
        conn.execute(
            "INSERT INTO messages (role_key, step, to_address, subject, body, status) "
            "VALUES ('r', 1, 'a@b.com', 's', 'b', 'failed')"
        )
        conn.commit()
        conn.close()
        upgraded = open_db(legacy)
        columns = {row["name"] for row in upgraded.query("PRAGMA table_info(messages)")}
        self.assertIn("attempts", columns)
        self.assertEqual(upgraded.requeue_failed("r"), 1)
        upgraded.close()

    def test_live_send_refuses_on_placeholder_settings(self):
        raw = json.loads(json.dumps(self.settings.raw))
        raw["identity"]["from_email"] = "CHANGEME@CHANGEME.example"
        broken = Settings(raw=raw)
        with self.assertRaises(ComplianceError):
            pipeline.send_due(self.db, broken, self.role, live=True, attest_warmup=True)

    def test_live_send_refuses_a_draft_role(self):
        with self.assertRaises(ComplianceError):
            pipeline.send_due(self.db, self.settings, self.roles["controller"], live=True, attest_warmup=True)

    def test_suppressed_address_is_never_written_to(self):
        self._seed()
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a specific detail")
        pipeline.enrich(self.db, self.settings, self.role)
        pipeline.verify_emails(self.db, self.settings, self.role)
        target = self.db.candidates(self.role.key, stages=["verified"])[0]
        address = self.db.primary_email(target["id"])["address"]
        self.db.suppress("email", address, "test")
        pipeline.queue_next(self.db, self.settings, self.role)
        queued = self.db.query(
            "SELECT * FROM messages WHERE to_address = ?", (address,)
        )
        self.assertEqual(queued, [])

    def test_send_window_blocks_out_of_hours_live_send(self):
        raw = json.loads(json.dumps(self.settings.raw))
        raw["sending"]["send_window"] = ["03:00", "03:01"]
        raw["sending"]["skip_weekdays"] = []
        tight = Settings(raw=raw)
        ok, why = pipeline.can_send_now(tight)
        if not ok:
            with self.assertRaises((SafetyStop, ComplianceError)):
                pipeline.send_due(self.db, tight, self.role, live=True, attest_warmup=True)


class TestBookings(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = _settings_and_roles()
        self.dir = tempfile.TemporaryDirectory()
        self.db = open_db(Path(self.dir.name) / "t.db")

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def test_sync_is_idempotent(self):
        bookings_mod.sync(self.db, self.settings, self.roles)
        first = self.db.scalar("SELECT COUNT(*) FROM bookings")
        bookings_mod.sync(self.db, self.settings, self.roles)
        self.assertEqual(self.db.scalar("SELECT COUNT(*) FROM bookings"), first)

    def test_cancel_sends_the_apology(self):
        bookings_mod.sync(self.db, self.settings, self.roles)
        booking = self.db.query("SELECT * FROM bookings ORDER BY id LIMIT 1")[0]
        result = bookings_mod.decide(
            self.db, self.settings, self.roles, int(booking["id"]), "cancel",
            reason="not a fit", live=False,
        )
        self.assertEqual(result.counts.get("apology_sent"), 1)
        row = self.db.one("SELECT * FROM bookings WHERE id = ?", (booking["id"],))
        self.assertEqual(row["status"], "cancelled")

    def test_cancel_without_an_email_is_refused(self):
        self.db.execute(
            "INSERT INTO bookings (provider, provider_id, attendee_name, status, created_at) "
            "VALUES ('dryrun', 'x1', 'No Email', 'booked', '2026-08-30T00:00:00+00:00')"
        )
        booking = self.db.one("SELECT * FROM bookings WHERE provider_id = 'x1'")
        with self.assertRaises(OutboundError):
            bookings_mod.decide(self.db, self.settings, self.roles, int(booking["id"]), "cancel")


class TestPages(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = _settings_and_roles()
        self.dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.dir.cleanup()

    def test_markdown_subset(self):
        from outbound.pages import markdown_to_html

        title, body = markdown_to_html(
            "# Title\n\nA lede.\n\n## Section\n\n- one\n- two\n\nTail with **bold**."
        )
        self.assertEqual(title, "Title")
        self.assertIn('<p class="lede">A lede.</p>', body)
        self.assertIn("<h2>Section</h2>", body)
        self.assertEqual(body.count("<li>"), 2)
        self.assertIn("<strong>bold</strong>", body)

    def test_markdown_escapes_html(self):
        from outbound.pages import markdown_to_html

        _title, body = markdown_to_html("# A\n\n<script>alert(1)</script>")
        self.assertNotIn("<script>", body)
        self.assertIn("&lt;script&gt;", body)

    def test_build_all_writes_every_live_role(self):
        from outbound.pages import build_all

        out = Path(self.dir.name)
        written = build_all(self.settings, self.roles, out)
        names = {p.name for p in written}
        self.assertIn("index.html", names)
        self.assertIn("unsubscribe.html", names)
        for role in self.roles.values():
            if role.is_live:
                self.assertIn(f"{role.key}.html", names)
            else:
                self.assertNotIn(f"{role.key}.html", names)

    def test_pages_carry_no_unrendered_tokens_and_no_em_dash(self):
        from outbound.pages import build_all

        out = Path(self.dir.name)
        for path in build_all(self.settings, self.roles, out):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("{{", text, f"{path.name} has an unrendered token")
            body = text.split("<body>", 1)[1]
            self.assertNotIn("\u2014", body, f"{path.name} has an em dash")

    def test_pages_keep_the_t1_line(self):
        """No page may name the client model, a casino, or the fund flow."""
        from outbound.pages import build_all

        # Only terms that give away the model. Ordinary words that happen to
        # appear in gambling ("bonus", "trading") are not tells and firing on
        # them makes the test useless.
        for path in build_all(self.settings, self.roles, Path(self.dir.name)):
            low = path.read_text(encoding="utf-8").lower()
            for word in T1_BANNED:
                self.assertNotIn(word, low, f"{path.name} leaks {word!r} above the NDA line")


class TestConfig(unittest.TestCase):
    def test_all_shipped_roles_load(self):
        roles = load_roles()
        self.assertGreaterEqual(len(roles), 3)
        for role in roles.values():
            self.assertTrue(role.signals)
            self.assertTrue(role.booking_questions)

    def test_role_overrides_apply(self):
        _settings, roles = load_all(DEMO_SETTINGS)
        self.assertNotIn("NEEDS_PETER", roles["head-of-operations"].comp)

    def test_unknown_override_field_is_rejected(self):
        from outbound.config import apply_overrides

        _settings, roles = load_all(DEMO_SETTINGS)
        bad = Settings(raw={"role_overrides": {"engineer": {"secrets": "x"}}})
        with self.assertRaises(ConfigError):
            apply_overrides(roles, bad)


if __name__ == "__main__":
    unittest.main()
