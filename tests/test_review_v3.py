"""Regression tests for the six bugs the third adversarial review confirmed.

Each test fails against the code as it was before its fix.

  1. `outbound send` without --live mutated state (marked sent, spent the cap,
     advanced stages) instead of previewing.
  2. A US state tail that also reads as a country code (Athens, GA) was
     pushed offshore.
  3. The one-role-per-person guard only saw 'sent' mail, so a person queued
     for two roles at once slipped through.
  4. A single-brace {personal_note} passed the step-one guard and shipped as
     literal text.
  5. The follow-up queue skipped the CAN-SPAM check the first email runs.
  6. The pace estimate ignored the warm-up cap and used floor-plus-one weeks.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("OUTBOUND_OFFLINE", "1")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from outbound import compose, pipeline  # noqa: E402
from outbound.audit import audit_role  # noqa: E402
from outbound.config import Settings, load_all  # noqa: E402
from outbound.db import open_db  # noqa: E402
from outbound.errors import ConfigError  # noqa: E402
from outbound.profiles import guess_country  # noqa: E402

DEMO = ROOT / "sample" / "settings.demo.toml"


def _load():
    return load_all(DEMO)


class _Base(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = _load()
        self.dir = tempfile.TemporaryDirectory()
        self.db = open_db(Path(self.dir.name) / "t.db")
        self.role = self.roles["head-of-operations"]

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def _to_queued(self, role=None):
        role = role or self.role
        pipeline.run_search(self.db, self.settings, role)
        pipeline.score_all(self.db, self.settings, role)
        for row in self.db.candidates(role.key, stages=["review"]):
            pipeline.set_review(self.db, role, int(row["id"]), "approve", "a specific detail")
        pipeline.enrich(self.db, self.settings, role)
        pipeline.verify_emails(self.db, self.settings, role)
        pipeline.queue_next(self.db, self.settings, role)


class TestSendPreviewDoesNotMutate(_Base):
    # fix 1
    def test_a_preview_send_changes_nothing_then_a_commit_send_sends(self):
        self._to_queued()
        day = pipeline.sending_day(self.settings)
        queued_before = self.db.query(
            "SELECT id FROM messages WHERE role_key = ? AND status = 'queued'",
            (self.role.key,),
        )
        self.assertTrue(queued_before, "the setup must leave queued mail")

        # Default: no --live, no commit. This is a preview.
        preview = pipeline.send_due(self.db, self.settings, self.role)
        self.assertGreater(preview.counts.get("previewed", 0), 0)
        self.assertEqual(preview.counts.get("sent", 0), 0)
        self.assertEqual(
            self.db.sends_today(self.role.key, day), 0,
            "a preview must not spend the daily cap",
        )
        still_queued = self.db.query(
            "SELECT id FROM messages WHERE role_key = ? AND status = 'queued'",
            (self.role.key,),
        )
        self.assertEqual(
            {r["id"] for r in still_queued}, {r["id"] for r in queued_before},
            "a preview must leave every message queued",
        )
        self.assertEqual(self.db.funnel(self.role.key).get("sent", 0), 0)

        # commit=True actually walks the funnel.
        real = pipeline.send_due(self.db, self.settings, self.role, commit=True)
        self.assertGreater(real.counts.get("sent", 0), 0)
        self.assertGreater(self.db.sends_today(self.role.key, day), 0)


class TestCountryStateTailWins(_Base):
    # fix 2
    def test_a_us_city_with_a_state_that_shadows_a_country_code(self):
        # GA is Georgia the state, not Gabon; CA is California, not Canada;
        # DE is Delaware, not Germany; MT is Montana, not Malta.
        self.assertEqual(guess_country("Athens, GA"), "US")
        self.assertEqual(guess_country("San Jose, CA"), "US")
        self.assertEqual(guess_country("Wilmington, DE"), "US")
        self.assertEqual(guess_country("Bozeman, MT"), "US")

    def test_a_real_foreign_city_still_resolves_offshore(self):
        # For the two shadow codes with a known foreign city, the city wins.
        # (MT/Malta has no city hint, so it stays the US state by design;
        # real sourcing supplies an explicit country. See docs/DECISIONS.md.)
        self.assertEqual(guess_country("Toronto, CA"), "CA")
        self.assertEqual(guess_country("Berlin, DE"), "DE")


class TestOneRoleGuardSeesQueued(_Base):
    # fix 3
    def test_a_queued_message_counts_as_already_contacted(self):
        cid, _ = self.db.upsert_candidate(
            "head-of-operations",
            {"linkedin_url": "linkedin.com/in/sam-jones", "full_name": "Sam Jones"},
        )
        row = self.db.candidate(cid)
        key = row["linkedin_key"]
        self.db.add_email(cid, "sam@example.com", primary=True)

        # Not sent yet, only queued.
        self.db.queue_message(
            cid, "head-of-operations", 1, "sam@example.com", "s", "b",
            "2026-08-01T00:00:00+00:00",
        )
        hit = self.db.contacted_for_another_role(key, "engineer")
        self.assertIsNotNone(hit, "a queued message for another role must block a second")
        self.assertEqual(hit["id"], cid)

    def test_a_person_with_no_live_mail_is_not_blocked(self):
        cid, _ = self.db.upsert_candidate(
            "head-of-operations",
            {"linkedin_url": "linkedin.com/in/dana-lee", "full_name": "Dana Lee"},
        )
        key = self.db.candidate(cid)["linkedin_key"]
        self.assertIsNone(self.db.contacted_for_another_role(key, "engineer"))


class TestSingleBraceToken(_Base):
    # fix 4
    def test_lint_flags_a_single_brace_token(self):
        problems = compose.lint("A subject", "Hello {personal_note}, quick note.")
        self.assertTrue(
            any("single-brace" in p for p in problems), problems
        )

    def test_lint_leaves_ordinary_prose_alone(self):
        problems = compose.lint("A subject", "Base is 250k and the team is small.")
        self.assertFalse(any("single-brace" in p for p in problems), problems)

    def test_step_one_requires_a_real_double_brace_token(self):
        candidate = {"id": 1, "full_name": "X", "personal_note": "a specific detail"}
        for body in (
            "Subject: s\n\nHi, a personal_note goes here somewhere.",  # bare word
            "Subject: s\n\nHi {personal_note}, a quick note.",          # single brace
        ):
            with mock.patch.object(
                compose, "_read_template", return_value=("s", body.split("\n\n", 1)[1])
            ):
                with self.assertRaises(ConfigError):
                    compose.render(self.settings, self.role, candidate, "x@y.com", 1)


class TestFollowUpComplianceGate(_Base):
    # fix 5
    def test_a_follow_up_is_blocked_when_the_unsubscribe_route_breaks(self):
        self._to_queued()
        pipeline.send_due(self.db, self.settings, self.role, commit=True)
        sent = self.db.candidates(self.role.key, stages=["sent"])
        self.assertTrue(sent, "step one must have been sent")

        # Break the opt-out link the way a bad config edit would. The template
        # still says 'unsubscribe', so the link now points nowhere.
        raw = json.loads(json.dumps(self.settings.raw))
        raw.setdefault("identity", {})["unsubscribe_url"] = ""
        broken = Settings(raw=raw)

        result = pipeline.queue_next(self.db, broken, self.role)
        self.assertGreaterEqual(
            result.counts.get("compliance_failed", 0), 1,
            "the follow-up loop must run the CAN-SPAM check too",
        )
        step_twos = self.db.query(
            "SELECT id FROM messages WHERE role_key = ? AND step > 1 AND status = 'queued'",
            (self.role.key,),
        )
        self.assertEqual(step_twos, [], "no follow-up may be queued without an opt-out")


class TestAuditPaceRespectsWarmup(_Base):
    # fix 6
    def _ramped(self, ramp):
        raw = json.loads(json.dumps(self.settings.raw))
        raw.setdefault("warmup", {})["ramp"] = ramp
        return Settings(raw=raw)

    def test_the_pace_estimate_uses_the_warm_up_cap_and_ceils_weeks(self):
        # Day one of the ramp caps the domain at 5 a day, well under the 18
        # daily cap. 25 ready at 5 a day is 5 working days, so one week.
        settings = self._ramped([[3, 5], [0, 0]])
        for index in range(25):
            cid, _ = self.db.upsert_candidate(
                self.role.key,
                {"linkedin_url": f"linkedin.com/in/w{index}", "full_name": f"W {index}"},
            )
            self.db.set_stage(cid, "verified")
        report = audit_role(self.db, settings, self.role)
        text = " | ".join(n.text for n in report.notes)
        self.assertIn("at 5 a day", text)
        self.assertIn("5 working day(s)", text)
        self.assertIn("1 week(s)", text)


if __name__ == "__main__":
    unittest.main()
