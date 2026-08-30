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

    def test_daily_cap_is_enforced(self):
        day = pipeline.sending_day(self.settings)
        cap = pipeline.daily_cap(self.settings, self.role)
        self.db.record_send(self.role.key, day, n=cap)
        result = pipeline.send_due(self.db, self.settings, self.role, live=False)
        self.assertEqual(result.counts.get("sent", 0), 0)
        self.assertTrue(any("daily cap" in n for n in result.notes))

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
