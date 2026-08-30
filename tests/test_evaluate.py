"""The AI evaluation stage: the offline provider, the two modes, and the
Anthropic adapter's parsing. No test reaches the network."""

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

from outbound import pipeline  # noqa: E402
from outbound.config import Settings, load_all  # noqa: E402
from outbound.db import open_db  # noqa: E402
from outbound.evaluate import build_brief, route_verdict  # noqa: E402
from outbound.providers import build as build_provider  # noqa: E402

DEMO = ROOT / "sample" / "settings.demo.toml"


def _settings(**evaluation):
    settings, roles = load_all(DEMO)
    raw = json.loads(json.dumps(settings.raw))
    raw.setdefault("evaluation", {}).update(evaluation)
    return Settings(raw=raw), roles


class _Base(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = load_all(DEMO)
        self.dir = tempfile.TemporaryDirectory()
        self.db = open_db(Path(self.dir.name) / "t.db")
        self.role = self.roles["head-of-operations"]
        pipeline.run_search(self.db, self.settings, self.role)
        pipeline.score_all(self.db, self.settings, self.role)

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()


class TestOfflineEvaluator(_Base):
    def test_the_verdict_is_well_formed(self):
        provider = build_provider("evaluate", "dryrun", self.settings)
        brief = build_brief(self.role)
        row = self.db.candidates(self.role.key, stages=["review"])[0]
        v = provider.evaluate(brief, dict(row))
        self.assertIn(v["verdict"], ("strong", "maybe", "weak"))
        self.assertGreaterEqual(v["fit"], 0.0)
        self.assertLessEqual(v["fit"], 1.0)
        self.assertTrue(v["personal_note"].strip())
        self.assertIsInstance(v["reasons"], list)
        self.assertFalse(v["disqualify"])

    def test_a_higher_score_gets_at_least_as_strong_a_verdict(self):
        rank = {"weak": 0, "maybe": 1, "strong": 2}
        provider = build_provider("evaluate", "dryrun", self.settings)
        brief = build_brief(self.role)
        rows = sorted(
            self.db.candidates(self.role.key, stages=["review"]),
            key=lambda r: float(r["score"] or 0),
        )
        verdicts = [provider.evaluate(brief, dict(r))["verdict"] for r in rows]
        ranks = [rank[v] for v in verdicts]
        self.assertEqual(ranks, sorted(ranks), "verdict must be monotonic in score")


class TestAssistMode(_Base):
    def test_it_drafts_notes_and_leaves_everyone_in_review(self):
        before = len(self.db.candidates(self.role.key, stages=["review"]))
        result = pipeline.evaluate_candidates(self.db, self.settings, self.role)
        after = self.db.candidates(self.role.key, stages=["review"])
        self.assertEqual(len(after), before, "assist mode must not move anyone")
        self.assertTrue(all(str(c.get("personal_note") or "").strip() for c in after))
        self.assertGreaterEqual(result.counts.get("left_for_review", 0), 1)

    def test_it_never_overwrites_a_note_a_person_wrote(self):
        row = self.db.candidates(self.role.key, stages=["review"])[0]
        self.db.execute(
            "UPDATE candidates SET personal_note = ? WHERE id = ?",
            ("A human wrote this.", row["id"]),
        )
        pipeline.evaluate_candidates(self.db, self.settings, self.role)
        after = self.db.candidate(int(row["id"]))
        self.assertEqual(after["personal_note"], "A human wrote this.")


class TestAutoMode(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = _settings(mode="auto", auto_approve_at=0.6)
        self.dir = tempfile.TemporaryDirectory()
        self.db = open_db(Path(self.dir.name) / "t.db")
        self.role = self.roles["head-of-operations"]
        pipeline.run_search(self.db, self.settings, self.role)
        pipeline.score_all(self.db, self.settings, self.role)

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def test_a_strong_fit_is_approved_with_its_note(self):
        result = pipeline.evaluate_candidates(self.db, self.settings, self.role)
        approved = self.db.candidates(self.role.key, stages=["approved"])
        self.assertGreaterEqual(result.counts.get("approved", 0), 1)
        self.assertTrue(approved)
        for c in approved:
            self.assertEqual(c["review_state"], "approved")
            self.assertTrue(str(c.get("personal_note") or "").strip())

    def test_an_auto_approve_with_no_note_falls_back_to_review(self):
        # Force the note empty: the provider returns one, so patch it away.
        real = pipeline.evaluate_candidates

        class _NoNote:
            name = "dryrun"

            def __init__(self, settings=None):
                pass

            def evaluate(self, brief, candidate):
                return {"fit": 0.95, "verdict": "strong", "reasons": [],
                        "personal_note": "", "disqualify": False,
                        "disqualify_reason": ""}

        with mock.patch("outbound.providers.build", return_value=_NoNote()):
            result = real(self.db, self.settings, self.role)
        self.assertGreaterEqual(
            result.counts.get("approve_without_note_to_review", 0), 1
        )
        self.assertEqual(self.db.funnel(self.role.key).get("approved", 0), 0)


class TestDryRunFlag(_Base):
    def test_commit_false_writes_nothing(self):
        before = self.db.funnel(self.role.key)
        notes_before = [
            str(c.get("personal_note") or "")
            for c in self.db.candidates(self.role.key, stages=["review"])
        ]
        result = pipeline.evaluate_candidates(
            self.db, self.settings, self.role, commit=False
        )
        self.assertEqual(self.db.funnel(self.role.key), before)
        notes_after = [
            str(c.get("personal_note") or "")
            for c in self.db.candidates(self.role.key, stages=["review"])
        ]
        self.assertEqual(notes_before, notes_after)
        self.assertTrue(any(k.startswith("would:") for k in result.counts))


class TestBrief(_Base):
    def test_the_brief_carries_the_icp(self):
        brief = build_brief(self.role)
        self.assertTrue(brief["titles_wanted"])
        self.assertTrue(brief["titles_excluded"])
        self.assertEqual(brief["role_key"], self.role.key)
        self.assertIn("selectivity_or_leadership", brief["positive_signals"])


class TestRouteVerdict(unittest.TestCase):
    def test_disqualify_always_rejects(self):
        self.assertEqual(route_verdict(0.99, "strong", True, 0.75, 0.4), "reject")

    def test_strong_below_the_approve_bar_goes_to_review(self):
        self.assertEqual(route_verdict(0.70, "strong", False, 0.75, 0.4), "review")

    def test_a_weak_verdict_rejects(self):
        self.assertEqual(route_verdict(0.60, "weak", False, 0.75, 0.4), "reject")

    def test_a_maybe_goes_to_review(self):
        self.assertEqual(route_verdict(0.60, "maybe", False, 0.75, 0.4), "review")


class TestAnthropicParsing(unittest.TestCase):
    def _provider(self):
        settings, _ = _settings(provider="anthropic")
        from outbound.providers.anthropic_eval import AnthropicEvaluate
        return AnthropicEvaluate(settings)

    def test_it_parses_a_fenced_json_body(self):
        from outbound.providers.anthropic_eval import _parse_verdict
        text = 'Here is my read:\n```json\n{"fit": 0.8, "verdict": "strong"}\n```\n'
        self.assertEqual(_parse_verdict(text)["verdict"], "strong")

    def test_it_parses_bare_json_with_prose_around_it(self):
        from outbound.providers.anthropic_eval import _parse_verdict
        text = 'I think {"fit": 0.3, "verdict": "weak", "reasons": ["thin"]} is right.'
        self.assertEqual(_parse_verdict(text)["fit"], 0.3)

    def test_normalize_clamps_and_defaults(self):
        from outbound.providers.anthropic_eval import _normalize
        v = _normalize({"fit": 1.9, "verdict": "banana", "reasons": "one string"})
        self.assertEqual(v["fit"], 1.0)
        self.assertEqual(v["verdict"], "strong")  # from the clamped fit
        self.assertEqual(v["reasons"], ["one string"])

    def test_a_full_call_is_normalized(self):
        provider = self._provider()
        fake = {"content": [{"type": "text",
                             "text": '{"fit": 0.72, "verdict": "maybe", '
                                     '"reasons": ["good ops track"], '
                                     '"personal_note": "You ran ops at Kestrel.", '
                                     '"disqualify": false, "disqualify_reason": ""}'}]}
        with mock.patch("outbound.httpjson.post", return_value=fake) as post, \
                mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}):
            v = provider.evaluate({"role_key": "x"}, {"full_name": "A B"})
        self.assertTrue(post.called)
        self.assertEqual(v["verdict"], "maybe")
        self.assertEqual(v["personal_note"], "You ran ops at Kestrel.")


if __name__ == "__main__":
    unittest.main()
