"""Candidate export."""

from __future__ import annotations

import os

import csv
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
from outbound.config import load_all  # noqa: E402
from outbound.db import open_db  # noqa: E402
from outbound.errors import OutboundError  # noqa: E402
from outbound.export import ATS_COLUMNS, DEFAULT_STAGES, export  # noqa: E402

DEMO_SETTINGS = ROOT / "sample" / "settings.demo.toml"


class TestExport(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = load_all(DEMO_SETTINGS)
        self.dir = tempfile.TemporaryDirectory()
        self.out = Path(self.dir.name)
        self.db = open_db(self.out / "t.db")
        self.role = self.roles["head-of-operations"]
        pipeline.run_search(self.db, self.settings, self.role)
        pipeline.score_all(self.db, self.settings, self.role)
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a detail")
        pipeline.enrich(self.db, self.settings, self.role)
        pipeline.verify_emails(self.db, self.settings, self.role)
        pipeline.queue_next(self.db, self.settings, self.role)
        pipeline.send_due(self.db, self.settings, self.role, live=False, commit=True)
        for row in self.db.candidates(self.role.key, stages=["sent"]):
            self.db.set_stage(int(row["id"]), "replied")

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def test_ats_format_has_stable_columns_and_an_address(self):
        path = self.out / "ats.csv"
        count = export(self.db, self.settings, self.role, path, fmt="ats")
        self.assertGreater(count, 0)
        with path.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(list(rows[0].keys()), ATS_COLUMNS)
        self.assertTrue(all(r["email"] for r in rows), "every exported row needs an address")
        self.assertTrue(all(r["source"] == "outbound" for r in rows))

    def test_default_stages_exclude_people_never_written_to(self):
        path = self.out / "ats.csv"
        export(self.db, self.settings, self.role, path, fmt="ats")
        with path.open(encoding="utf-8") as handle:
            stages = {r["stage"] for r in csv.DictReader(handle)}
        self.assertTrue(stages.issubset(set(DEFAULT_STAGES)), stages)

    def test_all_stages_exports_the_rejected_too(self):
        path = self.out / "all.csv"
        count = export(self.db, self.settings, self.role, path, fmt="csv", stages=[])
        total = self.db.scalar(
            "SELECT COUNT(*) FROM candidates WHERE role_key = ?", (self.role.key,)
        )
        self.assertEqual(count, total)

    def test_jsonl_drops_the_big_blobs(self):
        path = self.out / "out.jsonl"
        export(self.db, self.settings, self.role, path, fmt="jsonl")
        lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        self.assertTrue(lines)
        for row in lines:
            self.assertNotIn("profile_json", row)
            self.assertNotIn("score_json", row)
            self.assertIn("full_name", row)

    def test_an_unknown_format_is_refused(self):
        with self.assertRaises(OutboundError):
            export(self.db, self.settings, self.role, self.out / "x", fmt="pdf")

    def test_a_booked_candidate_carries_the_booking_time(self):
        cid = int(self.db.candidates(self.role.key, stages=["replied"])[0]["id"])
        self.db.set_stage(cid, "booked")
        self.db.execute(
            "INSERT INTO bookings (candidate_id, role_key, provider, provider_id, "
            "start_at, status, created_at) VALUES (?, ?, 'dryrun', 'bk1', "
            "'2026-09-02T15:00:00+00:00', 'booked', '2026-08-30T00:00:00+00:00')",
            (cid, self.role.key),
        )
        path = self.out / "ats.csv"
        export(self.db, self.settings, self.role, path, fmt="ats")
        with path.open(encoding="utf-8") as handle:
            rows = {r["linkedin_url"]: r for r in csv.DictReader(handle)}
        booked = [r for r in rows.values() if r["screener_booked_for"]]
        self.assertTrue(booked)


if __name__ == "__main__":
    unittest.main()
