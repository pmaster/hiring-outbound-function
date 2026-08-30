"""The two things a person reads: the sourcing plan and the report."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# No test may reach the network.
os.environ.setdefault("OUTBOUND_OFFLINE", "1")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from outbound import pipeline, report  # noqa: E402
from outbound.config import load_all  # noqa: E402
from outbound.db import open_db  # noqa: E402
from outbound.search import boolean_string, linkedin_url, manual_checklist, render_plan  # noqa: E402

DEMO_SETTINGS = ROOT / "sample" / "settings.demo.toml"


class TestSearchPlan(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = load_all(DEMO_SETTINGS)
        self.role = self.roles["head-of-operations"]

    def test_boolean_string_quotes_titles_and_ands_the_keywords(self):
        spec = self.role.searches[0]
        query = boolean_string(spec)
        for title in spec.titles:
            self.assertIn(f'"{title}"', query)
        self.assertIn(" OR ", query)
        if spec.keywords:
            self.assertIn(" AND ", query)

    def test_the_url_is_encoded_and_points_at_people_search(self):
        url = linkedin_url(self.role.searches[0])
        self.assertTrue(url.startswith("https://www.linkedin.com/search/results/people/?"))
        self.assertNotIn(" ", url)
        self.assertNotIn('"', url)

    def test_the_checklist_carries_every_icp_filter(self):
        items = " | ".join(manual_checklist(self.role, self.role.searches[0]))
        for needle in ("Geography", "Company headcount", "Years of experience",
                       "Exclude titles", "Target for this search"):
            self.assertIn(needle, items)
        # The rules that came out of the source documents.
        self.assertIn("09:00 and 22:00 ET", items)
        self.assertIn("Philadelphia", items)

    def test_the_plan_warns_about_scrapers(self):
        """The account safety rule has to be where the person building the
        list will read it, not only in a document."""
        plan = render_plan(self.role, self.settings)
        self.assertIn("Do NOT connect a real LinkedIn account to a scraper", plan)

    def test_every_live_role_produces_a_usable_plan(self):
        for role in self.roles.values():
            if not role.is_live:
                continue
            plan = render_plan(role, self.settings)
            self.assertIn(role.title, plan)
            self.assertIn("outbound import", plan)
            self.assertNotIn("{{", plan)
            if role.searches:
                self.assertIn("linkedin.com/search", plan)


class TestReport(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = load_all(DEMO_SETTINGS)
        self.dir = tempfile.TemporaryDirectory()
        self.db = open_db(Path(self.dir.name) / "t.db")
        self.role = self.roles["head-of-operations"]

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def _run_funnel(self):
        pipeline.run_search(self.db, self.settings, self.role)
        pipeline.score_all(self.db, self.settings, self.role)
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a detail")
        pipeline.enrich(self.db, self.settings, self.role)
        pipeline.verify_emails(self.db, self.settings, self.role)
        pipeline.queue_next(self.db, self.settings, self.role)
        pipeline.send_due(self.db, self.settings, self.role, live=False, commit=True)

    def test_an_empty_report_does_not_crash_or_lie(self):
        text = report.summary(self.db, self.settings, self.roles)
        self.assertIn("Outbound report", text)
        self.assertIn("nothing sent today", text)

    def test_the_sending_line_agrees_with_what_was_sent(self):
        """These disagreed once: the sender logged against the sending
        timezone's day and the report looked for the UTC day."""
        self._run_funnel()
        sent = self.db.scalar(
            "SELECT COUNT(*) FROM messages WHERE status = 'sent' AND role_key = ?",
            (self.role.key,),
        )
        self.assertGreater(sent, 0)
        text = report.summary(self.db, self.settings, self.roles)
        self.assertNotIn("nothing sent today", text)
        day = pipeline.sending_day(self.settings)
        self.assertEqual(self.db.sends_today(self.role.key, day), sent)
        self.assertIn(f"{sent}/", text)

    def test_next_actions_name_a_command_that_exists(self):
        from outbound.cli import build_parser

        self._run_funnel()
        verbs = set(build_parser()._subparsers._group_actions[0].choices)
        text = report.next_actions(self.db, self.settings, self.roles)
        for line in text.splitlines():
            if "`outbound " not in line:
                continue
            verb = line.split("`outbound ", 1)[1].split()[0].strip("`")
            self.assertIn(verb, verbs, line)

    def test_conversion_never_divides_by_zero(self):
        text = report.conversions(self.db, None)
        self.assertIn("n/a", text)

    def test_the_bounce_line_appears_once_there_is_data(self):
        self._run_funnel()
        text = report.summary(self.db, self.settings, self.roles)
        self.assertIn("bounce rate", text)


if __name__ == "__main__":
    unittest.main()
