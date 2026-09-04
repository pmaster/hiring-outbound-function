"""Tests. Standard library unittest, no runner to install.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os

import datetime as _dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

# No test may reach the network. An unmocked call fails immediately and says so.
os.environ.setdefault("OUTBOUND_OFFLINE", "1")

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
# Sources: docs/SOURCE-BRIEF.md section 4 items 1, 7 and 17, and
# projects/sunbird/employee-pitch.md Version 1.
T1_BANNED = [
    # The domain itself.
    "casino", "sportsbook", "bookmaker", "gambling", "betting", "wager",
    "sweepstake", "games of chance", "lottery", "advantage play",
    # The platforms and processors. Naming them invites the pattern matching
    # that already caused mass account bans.
    "draftkings", "fanduel", "betmgm", "caesars", "paypal", "varo", "sofi",
    # The model.
    "funded account", "promotional offer", "under our direction",
    "device commingling", "geolocation", "account separation",
    # Internal names that must not reach a candidate.
    "cornerstone gigs", "cornerstonegigs", "opsengine", "sunrun labs",
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

    def test_every_role_scores_the_intelligence_and_leadership_proxy(self):
        """DECISIONS.md #13: intelligence is necessary but not sufficient, and
        leadership roles proxy accountability. Every role must reward it, and
        the reward must be a nudge, not decisive."""
        for key, role in self.roles.items():
            with self.subTest(role=key):
                keys = [sig.key for sig in role.signals]
                self.assertIn("selectivity_or_leadership", keys)
                sig = next(s for s in role.signals if s.key == "selectivity_or_leadership")
                self.assertGreater(sig.weight, 0)
                self.assertLess(sig.weight, 0.12, "a proxy that decides a hire is too strong")

    def test_a_leadership_marker_lifts_a_score_but_does_not_decide_it(self):
        role = self.roles["chief-of-staff"]
        base = normalize({
            "fullName": "J D", "headline": "Chief of Staff at Acme",
            "profileUrl": "https://linkedin.com/in/jd", "location": "Austin, TX",
            "summary": "Chief of Staff. Ex-McKinsey associate.",
        })
        lifted = normalize({
            "fullName": "J D", "headline": "Chief of Staff at Acme",
            "profileUrl": "https://linkedin.com/in/jd", "location": "Austin, TX",
            "summary": "Chief of Staff. Ex-McKinsey associate. Team captain, summa cum laude.",
        })
        low = score_profile(role, base, allowed_countries={"US"}).score
        high = score_profile(role, lifted, allowed_countries={"US"}).score
        self.assertGreater(high, low)
        self.assertLess(high - low, 0.12, "the proxy must be a nudge, not the whole score")

    def test_evidence_quotes_the_profile_text_that_fired_a_signal(self):
        from outbound.score import evidence_for, top_evidence

        role = self.roles["head-of-operations"]
        profile = normalize({
            "fullName": "S T", "headline": "Head of Operations at Kestrel",
            "profileUrl": "https://linkedin.com/in/st", "location": "Austin, TX",
            "companySize": "51-200",
            "summary": "Built the ops function from scratch. Owned P&L and led 22 people.",
        })
        built = next(s for s in role.signals if s.key == "built_not_maintained")
        snippets = evidence_for(built, profile)
        self.assertTrue(snippets)
        self.assertTrue(any("from scratch" in s or "Built" in s for s in snippets))

        top = top_evidence(role, profile, limit=3)
        self.assertTrue(top)
        self.assertTrue(all(s.startswith("[") for s in top))
        # One per signal, not three of the same one.
        keys = [s.split("]")[0] for s in top]
        self.assertEqual(len(keys), len(set(keys)), top)

    def test_evidence_is_empty_for_a_thin_profile(self):
        from outbound.score import top_evidence

        role = self.roles["head-of-operations"]
        thin = normalize({"fullName": "A B", "profileUrl": "https://linkedin.com/in/ab"})
        self.assertEqual(top_evidence(role, thin), [])

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

    def test_a_thin_re_sighting_does_not_blank_the_rich_row(self):
        """Apollo search returns name + linkedin_url only. A second sighting of
        someone already sourced by a richer search must not wipe their data,
        or they silently drop out of the funnel and score --restage cannot
        recover them because profile_json is gone too."""
        from outbound.profiles import normalize

        rich = normalize({
            "fullName": "Dana Reyes", "headline": "Head of Operations at Kestrel",
            "profileUrl": "https://uk.linkedin.com/in/dana-reyes/",
            "location": "Austin, TX", "companyName": "Kestrel", "companySize": "51-200",
            "summary": "Built the ops function from scratch.",
        }, source="apify")
        cid, _ = self.db.upsert_candidate("r", rich)
        thin = normalize({
            "fullName": "Dana Reyes", "profileUrl": "https://linkedin.com/in/dana-reyes",
        }, source="apollo")
        cid2, created = self.db.upsert_candidate("r", thin)
        self.assertEqual(cid2, cid)
        self.assertFalse(created)
        row = self.db.candidate(cid)
        self.assertEqual(row["title"], "Head of Operations")
        self.assertEqual(row["company"], "Kestrel")
        self.assertEqual(row["country"], "US")
        self.assertTrue(row["profile_text"], "profile_text was blanked")
        self.assertEqual(row["source"], "apollo", "housekeeping fields still refresh")
        import json as _json
        self.assertTrue(_json.loads(row["profile_json"]), "profile_json was blanked")

    def test_a_richer_re_sighting_still_updates(self):
        from outbound.profiles import normalize

        cid, _ = self.db.upsert_candidate("r", normalize({
            "fullName": "Dana Reyes", "headline": "Head of Operations at Kestrel",
            "profileUrl": "https://linkedin.com/in/dana-reyes", "location": "Austin, TX",
        }))
        self.db.upsert_candidate("r", normalize({
            "fullName": "Dana Reyes", "headline": "VP Operations at Kestrel",
            "profileUrl": "https://linkedin.com/in/dana-reyes", "location": "Denver, CO",
            "companySize": "201-500",
        }))
        row = self.db.candidate(cid)
        self.assertEqual(row["title"], "VP Operations")
        self.assertEqual(row["location"], "Denver, CO")
        self.assertEqual(row["company_headcount"], 350)

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

    def test_preflight_blocks_the_client_and_internal_domains(self):
        """Both source doctrines agree these must never send FTE outreach."""
        for domain in ("cornerstonegigs.com", "sunrunlabs.com", "gmail.com"):
            raw = json.loads(json.dumps(self.settings.raw))
            raw["identity"]["from_email"] = f"jobs@{domain}"
            problems = preflight(Settings(raw=raw), None)
            fatal = {p.code for p in problems if p.fatal}
            self.assertIn("forbidden_domain", fatal, domain)

    def test_a_contested_domain_warns_until_the_decision_is_recorded(self):
        """viewlineventures.com is the designated FTE domain in one doc and a
        thing to protect in another. That is a decision, not a rule, so it
        warns until someone records having made it."""
        for domain in ("viewlineventures.com", "sunbirdsystems.com"):
            raw = json.loads(json.dumps(self.settings.raw))
            raw["identity"]["from_email"] = f"jobs@{domain}"
            raw["identity"].pop("sending_domain_decided_on", None)
            problems = preflight(Settings(raw=raw), None)
            self.assertIn("contested_domain", {p.code for p in problems}, domain)
            self.assertNotIn(
                "forbidden_domain", {p.code for p in problems if p.fatal}, domain
            )
            raw["identity"]["sending_domain_decided_on"] = "2026-08-30"
            after = preflight(Settings(raw=raw), None)
            self.assertNotIn("contested_domain", {p.code for p in after}, domain)

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

    def test_variants_are_discovered_and_assigned_stably(self):
        from outbound.compose import pick_variant, variants_available

        role = self.roles["head-of-operations"]
        options = variants_available(role, 1)
        self.assertIn("a", options)
        self.assertGreaterEqual(len(options), 2, "expected a second first-email variant")
        # Stable: the same person always gets the same version.
        for candidate_id in range(20):
            first = pick_variant(role, 1, candidate_id)
            self.assertEqual(first, pick_variant(role, 1, candidate_id))
            self.assertIn(first, options)
        # And the split is even across ids.
        assigned = [pick_variant(role, 1, i) for i in range(100)]
        for option in options:
            self.assertGreater(assigned.count(option), 30, option)

    def test_a_role_with_one_variant_always_returns_a(self):
        from outbound.compose import pick_variant, variants_available

        role = self.roles["controller"]
        self.assertEqual(variants_available(role, 1), ["a"])
        self.assertEqual(pick_variant(role, 1, 7), "a")

    def test_each_variant_renders_and_passes_the_linter(self):
        from outbound.compose import variants_available

        role = self.roles["head-of-operations"]
        subjects = set()
        for variant in variants_available(role, 1):
            out = render(self.settings, role, self.candidate, "d@x.com", 1, variant=variant)
            self.assertEqual(out.variant, variant)
            subjects.add(out.subject)
        self.assertEqual(len(subjects), len(variants_available(role, 1)),
                         "variants should differ in subject, or there is no experiment")

    def test_a_per_search_comp_band_wins_over_the_role_band(self):
        """Quoting a candidate the wrong city's band is a real error."""
        role = self.roles["fulfillment-specialist"]
        bands = {s.name: s.comp for s in role.searches if s.comp}
        self.assertGreaterEqual(len(bands), 2, "expected per city bands")
        for name, band in bands.items():
            self.assertEqual(role.comp_for(name), band)
            out = render(
                self.settings, role,
                dict(self.candidate, source_search=name), "d@x.com", 1,
            )
            self.assertIn(band, out.body)
        # No search named, so the role band is used.
        self.assertEqual(role.comp_for(None), role.comp)
        self.assertEqual(role.comp_for("no-such-search"), role.comp)

    def test_step_one_refuses_without_a_personal_note(self):
        candidate = dict(self.candidate, personal_note="")
        with self.assertRaises(OutboundError):
            render(self.settings, self.roles["head-of-operations"], candidate, "d@x.com", 1)

    def test_linter_catches_unfinished_copy(self):
        for marker in ("DRAFT. Not live yet.", "TODO: write this",
                       "TBD", "lorem ipsum dolor", "[insert name]"):
            problems = lint("A subject", f"Some text. {marker} More text.")
            self.assertTrue(
                any("unfinished copy marker" in p for p in problems),
                f"{marker!r} was not caught",
            )

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
        self.assertIn("evidence", rows[0], "the reviewer needs the profile quotes")
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

    def test_restage_does_not_undo_a_decision_or_walk_a_person_backwards(self):
        """Re-scoring after an ICP change must not reset a hand approval or
        move a booked/sent person back to review or rejected."""
        self._seed()
        review = self.db.candidates(self.role.key, stages=["review"])
        self.assertGreaterEqual(len(review), 2)
        approved_id = int(review[0]["id"])
        self.db.set_stage(approved_id, "approved")
        booked_id = int(review[1]["id"])
        self.db.set_stage(booked_id, "booked")
        result = pipeline.score_all(self.db, self.settings, self.role, restage=True)
        self.assertEqual(self.db.candidate(approved_id)["stage"], "approved")
        self.assertEqual(self.db.candidate(booked_id)["stage"], "booked")
        # but the score was still refreshed for reference
        self.assertIsNotNone(self.db.candidate(approved_id)["score"])
        self.assertGreaterEqual(result.counts.get("rescored:approved", 0), 1)
        self.assertGreaterEqual(result.counts.get("rescored:booked", 0), 1)

    def test_restage_still_reranks_people_still_in_review(self):
        self._seed()
        review_before = {int(r["id"]) for r in self.db.candidates(self.role.key, stages=["review"])}
        self.assertTrue(review_before)
        pipeline.score_all(self.db, self.settings, self.role, restage=True)
        # A review candidate can move to rejected or approved on a re-score,
        # but only from review, never from a later stage.
        for cid in review_before:
            self.assertIn(self.db.candidate(cid)["stage"], ("review", "rejected", "approved"))

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
        first = pipeline.send_due(self.db, self.settings, self.role, live=False, commit=True)
        self.assertGreater(first.counts.get("sent", 0), 0)
        second = pipeline.send_due(self.db, self.settings, self.role, live=False, commit=True)
        self.assertEqual(second.counts.get("sent", 0), 0)

    def _ramped(self, ramp):
        raw = json.loads(json.dumps(self.settings.raw))
        raw["warmup"]["ramp"] = ramp
        return Settings(raw=raw)

    def test_warmup_ramp_counts_sending_days_not_calendar_days(self):
        ramped = self._ramped([[3, 5], [3, 10], [0, 0]])
        # Nothing sent yet: day one of the ramp.
        cap, note = pipeline.warmup_cap(ramped, self.db)
        self.assertEqual(cap, 5)
        self.assertIn("day 1", note)
        # Three days of sending, whenever they happened.
        for day in ("2026-08-01", "2026-08-05", "2026-08-20"):
            self.db.record_send(self.role.key, day, n=5)
        cap, _note = pipeline.warmup_cap(ramped, self.db)
        self.assertEqual(cap, 10)
        for day in ("2026-08-21", "2026-08-24", "2026-08-25"):
            self.db.record_send(self.role.key, day, n=10)
        cap, _note = pipeline.warmup_cap(ramped, self.db)
        self.assertEqual(cap, -1, "ramp should be finished")

    def test_an_empty_ramp_means_no_warm_up_limit(self):
        cap, note = pipeline.warmup_cap(self._ramped([]), self.db)
        self.assertEqual(cap, -1)
        self.assertEqual(note, "")

    def test_the_warmup_cap_actually_limits_a_send(self):
        ramped = self._ramped([[3, 2], [0, 0]])
        self._seed()
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a detail")
        pipeline.enrich(self.db, ramped, self.role)
        pipeline.verify_emails(self.db, ramped, self.role)
        pipeline.queue_next(self.db, ramped, self.role)
        result = pipeline.send_due(self.db, ramped, self.role, live=False, commit=True)
        self.assertLessEqual(result.counts.get("sent", 0), 2)

    def test_the_bounce_guard_stops_a_send(self):
        day = pipeline.sending_day(self.settings)
        # 50 sends, 5 of them bounced: 10 percent, over the 3 percent ceiling.
        for index in range(50):
            cid, _ = self.db.upsert_candidate(
                self.role.key, {"linkedin_url": f"linkedin.com/in/p{index}", "full_name": f"P {index}"}
            )
            address = f"p{index}@example.com"
            self.db.add_email(cid, address)
            mid = self.db.queue_message(cid, self.role.key, 1, address, "s", "b", "2026-08-01T00:00:00+00:00")
            self.db.mark_sent(mid, "dryrun")
            if index < 5:
                self.db.set_stage(cid, "bounced")
        rate, bounced, sent = self.db.bounce_rate()
        self.assertEqual((bounced, sent), (5, 50))
        self.assertAlmostEqual(rate, 0.1, places=3)
        self.assertIn("bounce rate", pipeline.bounce_guard(self.settings, self.db))
        with self.assertRaises(SafetyStop):
            pipeline.send_due(self.db, self.settings, self.role, live=False)

    def test_the_bounce_guard_waits_for_enough_data(self):
        """Two bounces out of five is 40 percent and means nothing."""
        for index in range(5):
            cid, _ = self.db.upsert_candidate(
                self.role.key, {"linkedin_url": f"linkedin.com/in/q{index}", "full_name": f"Q {index}"}
            )
            address = f"q{index}@example.com"
            self.db.add_email(cid, address)
            mid = self.db.queue_message(cid, self.role.key, 1, address, "s", "b", "2026-08-01T00:00:00+00:00")
            self.db.mark_sent(mid, "dryrun")
            if index < 2:
                self.db.set_stage(cid, "bounced")
        self.assertEqual(pipeline.bounce_guard(self.settings, self.db), "")

    def test_a_test_send_touches_nothing(self):
        """It must not count against the cap, mark a candidate, or suppress."""
        self._seed()
        day = pipeline.sending_day(self.settings)
        before_cap = self.db.sends_today(self.role.key, day)
        before_stages = self.db.funnel(self.role.key)
        result = pipeline.send_test(
            self.db, self.settings, self.role, "me@example.com", live=False
        )
        self.assertEqual(result.counts.get("sent"), 1)
        self.assertEqual(self.db.sends_today(self.role.key, day), before_cap)
        self.assertEqual(self.db.funnel(self.role.key), before_stages)
        self.assertEqual(
            self.db.query("SELECT * FROM messages WHERE to_address = 'me@example.com'"), []
        )

    def test_a_test_send_can_use_a_real_candidate_and_a_variant(self):
        self._seed()
        row = self.db.candidates(self.role.key, stages=["review"])[0]
        self.db.execute(
            "UPDATE candidates SET personal_note = 'A real detail.' WHERE id = ?",
            (row["id"],),
        )
        result = pipeline.send_test(
            self.db, self.settings, self.role, "me@example.com",
            candidate_id=int(row["id"]), variant="b", live=False,
        )
        self.assertEqual(result.counts.get("sent"), 1)
        self.assertTrue(any("variant b" in n for n in result.notes), result.notes)

    def test_a_test_send_needs_an_address(self):
        with self.assertRaises(OutboundError):
            pipeline.send_test(self.db, self.settings, self.role, "")

    def test_a_test_send_supplies_its_own_note(self):
        """Step one refuses without a personal note, and a test has no person."""
        result = pipeline.send_test(
            self.db, self.settings, self.role, "me@example.com", live=False
        )
        self.assertEqual(result.counts.get("sent"), 1)

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

    def test_max_steps_one_gives_a_single_email_with_no_follow_ups(self):
        """The one-email flow: intro, JD link, screener link, then nothing."""
        raw = json.loads(json.dumps(self.settings.raw))
        raw["sending"]["max_steps"] = 1
        one = Settings(raw=raw)
        self._seed()
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a detail")
        pipeline.enrich(self.db, one, self.role)
        pipeline.verify_emails(self.db, one, self.role)
        pipeline.queue_next(self.db, one, self.role)
        pipeline.send_due(self.db, one, self.role, live=False, commit=True)
        # Everyone is at 'sent' after one email. A second queue must add no
        # step-2 message, because the sequence is capped at one.
        pipeline.queue_next(self.db, one, self.role)
        step_twos = self.db.query(
            "SELECT id FROM messages WHERE role_key = ? AND step > 1", (self.role.key,)
        )
        self.assertEqual(step_twos, [], "max_steps=1 must never queue a follow-up")
        sent = self.db.query(
            "SELECT DISTINCT step FROM messages WHERE role_key = ?", (self.role.key,)
        )
        self.assertEqual([r["step"] for r in sent], [1])

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
        import copy

        draft = copy.deepcopy(self.roles["controller"])
        draft.status = "draft"
        with self.assertRaises(ComplianceError):
            pipeline.send_due(
                self.db, self.settings, draft, live=True,
                attest_warmup=True, ignore_window=True,
            )

    def test_the_variant_is_recorded_on_the_message(self):
        self._seed()
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a detail")
        pipeline.enrich(self.db, self.settings, self.role)
        pipeline.verify_emails(self.db, self.settings, self.role)
        pipeline.queue_next(self.db, self.settings, self.role)
        rows = self.db.query(
            "SELECT variant FROM messages WHERE role_key = ? AND step = 1", (self.role.key,)
        )
        self.assertTrue(rows)
        self.assertTrue(all(r["variant"] in ("a", "b") for r in rows), rows)

    def test_variant_stats_count_replies(self):
        cid, _ = self.db.upsert_candidate(
            self.role.key, {"linkedin_url": "linkedin.com/in/v1", "full_name": "V One"}
        )
        self.db.add_email(cid, "v1@example.com")
        mid = self.db.queue_message(cid, self.role.key, 1, "v1@example.com", "s", "b",
                                    "2026-08-01T00:00:00+00:00", variant="b")
        self.db.mark_sent(mid, "dryrun")
        self.db.set_stage(cid, "replied")
        stats = {r["variant"]: r for r in self.db.variant_stats(self.role.key, 1)}
        self.assertEqual(int(stats["b"]["sent"]), 1)
        self.assertEqual(int(stats["b"]["replied"]), 1)

    def test_the_timeline_records_why_someone_was_rejected(self):
        self._seed()
        rejected = self.db.candidates(self.role.key, stages=["rejected"])
        self.assertTrue(rejected)
        entries = self.db.timeline(int(rejected[0]["id"]))
        self.assertTrue(any(e["kind"].startswith("scored:") for e in entries), entries)

    def test_stop_on_halts_the_sequence(self):
        """sending.stop_on is real config, not decoration."""
        self._seed()
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a detail")
        pipeline.enrich(self.db, self.settings, self.role)
        pipeline.verify_emails(self.db, self.settings, self.role)
        pipeline.queue_next(self.db, self.settings, self.role)
        target = self.db.query(
            "SELECT * FROM messages WHERE role_key = ? AND status = 'queued'", (self.role.key,)
        )[0]
        self.db.set_stage(int(target["candidate_id"]), "replied")
        result = pipeline.send_due(self.db, self.settings, self.role, live=False)
        self.assertGreaterEqual(result.counts.get("skipped_stage", 0), 1)
        after = self.db.one("SELECT status FROM messages WHERE id = ?", (target["id"],))
        self.assertEqual(after["status"], "skipped")

    def test_a_person_is_never_written_to_for_two_roles(self):
        other = self.roles["engineer"]
        for role in (self.role, other):
            pipeline.run_search(self.db, self.settings, role)
            pipeline.score_all(self.db, self.settings, role)
            for row in self.db.candidates(role.key, stages=["review"]):
                pipeline.set_review(self.db, role, int(row["id"]), "approve", "a detail")
            pipeline.enrich(self.db, self.settings, role)
            pipeline.verify_emails(self.db, self.settings, role)
        # Put the same person in both roles, then send for the first.
        first = self.db.candidates(self.role.key, stages=["verified"])[0]
        key = first["linkedin_key"]
        # Go through normalize, as the importer does. Passing a raw dict
        # straight to upsert leaves country null, and a null country is
        # refused by the geo gate before the cross role guard is reached.
        self.db.upsert_candidate(other.key, normalize({
            "fullName": first["full_name"], "profileUrl": first["linkedin_url"],
            "headline": first["title"], "companyName": first["company"],
            "location": first["location"],
        }))
        dupe = self.db.one(
            "SELECT * FROM candidates WHERE role_key = ? AND linkedin_key = ?",
            (other.key, key),
        )
        self.db.execute(
            "UPDATE candidates SET personal_note = 'x', stage = 'verified', "
            "review_state = 'approved' WHERE id = ?", (dupe["id"],))
        self.db.add_email(int(dupe["id"]), "dupe@example.com", primary=True)
        pipeline.queue_next(self.db, self.settings, self.role)
        pipeline.send_due(self.db, self.settings, self.role, live=False, commit=True)

        result = pipeline.queue_next(self.db, self.settings, other)
        self.assertGreaterEqual(
            result.counts.get("already_contacted_for_another_role", 0), 1
        )
        after = self.db.candidate(int(dupe["id"]))
        self.assertEqual(after["stage"], "stopped")

    def test_a_follow_up_is_not_queued_for_someone_suppressed_after_step_one(self):
        """A bulk unsubscribe import suppresses the address without changing
        the stage, so the follow-up loop has to check it too."""
        self._seed()
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a detail")
        pipeline.enrich(self.db, self.settings, self.role)
        pipeline.verify_emails(self.db, self.settings, self.role)
        pipeline.queue_next(self.db, self.settings, self.role)
        pipeline.send_due(self.db, self.settings, self.role, live=False, commit=True)
        sent = self.db.candidates(self.role.key, stages=["sent"])
        self.assertTrue(sent)
        target = sent[0]
        address = self.db.primary_email(int(target["id"]))["address"]
        self.db.suppress("email", address, "bulk unsubscribe import")
        pipeline.queue_next(self.db, self.settings, self.role)
        followups = self.db.query(
            "SELECT * FROM messages WHERE candidate_id = ? AND step > 1 AND status = 'queued'",
            (target["id"],),
        )
        self.assertEqual(followups, [])
        self.assertEqual(self.db.candidate(int(target["id"]))["stage"], "unsubscribed")

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
            reason="not a fit", live=False, force_late=True,
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
        from outbound.pages import CONTENT_DIR, build_all

        out = Path(self.dir.name)
        written = build_all(self.settings, self.roles, out)
        names = {p.name for p in written}
        self.assertIn("index.html", names)
        self.assertIn("unsubscribe.html", names)
        for role in self.roles.values():
            has_content = (CONTENT_DIR / f"{role.key}.md").exists()
            if role.is_live and has_content:
                self.assertIn(f"{role.key}.html", names)
            elif not role.is_live:
                self.assertNotIn(f"{role.key}.html", names)

    def test_every_live_role_has_a_job_description(self):
        """A live role with no page has an email linking to a 404."""
        from outbound.pages import CONTENT_DIR

        missing = [
            r.key for r in self.roles.values()
            if r.is_live and not (CONTENT_DIR / f"{r.key}.md").exists()
        ]
        self.assertEqual(missing, [], f"live roles with no content/jd page: {missing}")

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
