"""The pre-send list audit."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from outbound import pipeline  # noqa: E402
from outbound.audit import audit_role  # noqa: E402
from outbound.config import Settings, load_all  # noqa: E402
from outbound.db import open_db  # noqa: E402
from outbound.profiles import normalize  # noqa: E402

DEMO_SETTINGS = ROOT / "sample" / "settings.demo.toml"


class TestAudit(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = load_all(DEMO_SETTINGS)
        self.dir = tempfile.TemporaryDirectory()
        self.db = open_db(Path(self.dir.name) / "t.db")
        self.role = self.roles["head-of-operations"]

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def _seed(self):
        pipeline.run_search(self.db, self.settings, self.role)
        pipeline.score_all(self.db, self.settings, self.role)

    def _texts(self, report):
        return " | ".join(n.text for n in report.notes)

    def test_an_empty_list_warns_but_does_not_block(self):
        """Every later step is a no-op on an empty list, so this is a gap in
        the plan rather than a fault in the run."""
        report = audit_role(self.db, self.settings, self.role)
        self.assertEqual(report.blocking, [])
        self.assertIn("empty", self._texts(report))
        self.assertIn("warn", [n.level for n in report.notes])

    def test_an_approved_candidate_with_no_note_blocks(self):
        self._seed()
        row = self.db.candidates(self.role.key, stages=["review"])[0]
        # Approve around the guard, the way a bad import would.
        self.db.execute(
            "UPDATE candidates SET stage = 'approved', review_state = 'approved', "
            "personal_note = NULL WHERE id = ?", (row["id"],))
        report = audit_role(self.db, self.settings, self.role)
        self.assertTrue(report.blocking)
        self.assertIn("no personal note", self._texts(report))

    def test_an_approved_candidate_in_a_blocked_country_blocks(self):
        self.db.upsert_candidate(self.role.key, normalize({
            "fullName": "A N", "headline": "Director of Operations at Foo",
            "profileUrl": "https://linkedin.com/in/an", "location": "Warsaw, Poland",
        }))
        row = self.db.candidates(self.role.key)[0]
        self.db.execute(
            "UPDATE candidates SET stage = 'approved', personal_note = 'x' WHERE id = ?",
            (row["id"],))
        report = audit_role(self.db, self.settings, self.role)
        self.assertTrue(report.blocking)
        self.assertIn("country we do not send to", self._texts(report))

    def test_it_warns_when_the_list_is_short(self):
        self._seed()
        report = audit_role(self.db, self.settings, self.role)
        self.assertIn("of a target", self._texts(report))

    def test_it_warns_when_a_filter_rejects_almost_everything(self):
        for index in range(30):
            self.db.upsert_candidate(self.role.key, normalize({
                "fullName": f"P {index}",
                "headline": "Operations Coordinator at BigCo",
                "profileUrl": f"https://linkedin.com/in/p{index}",
                "location": "Austin, TX",
            }))
        pipeline.score_all(self.db, self.settings, self.role)
        report = audit_role(self.db, self.settings, self.role)
        self.assertIn("was rejected", self._texts(report))

    def test_it_warns_when_profiles_are_too_thin_to_score(self):
        for index in range(20):
            self.db.upsert_candidate(self.role.key, normalize({
                "fullName": f"T {index}",
                "headline": "Head of Operations",
                "profileUrl": f"https://linkedin.com/in/t{index}",
                "location": "Austin, TX",
            }))
        pipeline.score_all(self.db, self.settings, self.role)
        report = audit_role(self.db, self.settings, self.role)
        self.assertIn("almost no text", self._texts(report))

    def test_it_estimates_how_long_the_list_takes(self):
        self._seed()
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a detail")
        pipeline.enrich(self.db, self.settings, self.role)
        pipeline.verify_emails(self.db, self.settings, self.role)
        report = audit_role(self.db, self.settings, self.role)
        self.assertIn("working day", self._texts(report))

    def test_it_reports_the_warm_up_state(self):
        raw = json.loads(json.dumps(self.settings.raw))
        raw["warmup"]["ramp"] = [[3, 5], [0, 0]]
        ramped = Settings(raw=raw)
        self._seed()
        report = audit_role(self.db, ramped, self.role)
        self.assertIn("warm up is active", self._texts(report))


if __name__ == "__main__":
    unittest.main()
