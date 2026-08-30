"""Reply and bounce detection.

The failure this guards against: sending "I am closing this search" to someone
who replied four days ago.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from outbound import pipeline, replies  # noqa: E402
from outbound.config import load_all  # noqa: E402
from outbound.db import open_db  # noqa: E402

DEMO_SETTINGS = ROOT / "sample" / "settings.demo.toml"


def inbound(sender, subject="Re: a role", body="Sure, happy to talk."):
    return replies.Inbound(from_address=sender, subject=subject, body=body, date="")


class TestClassify(unittest.TestCase):
    def setUp(self):
        self.written = {"dana@acme.com", "sam@beta.com"}

    def test_a_reply_from_someone_we_wrote_to(self):
        self.assertEqual(
            replies.classify(inbound("dana@acme.com"), self.written),
            ("replied", "dana@acme.com"),
        )

    def test_a_stranger_is_ignored(self):
        kind, _ = replies.classify(inbound("newsletter@elsewhere.com"), self.written)
        self.assertEqual(kind, "ignore")

    def test_opt_out_language_beats_reply(self):
        for text in ("please unsubscribe me", "Remove me from this list",
                     "stop emailing me", "do not contact me again"):
            kind, address = replies.classify(inbound("dana@acme.com", body=text), self.written)
            self.assertEqual((kind, address), ("unsubscribed", "dana@acme.com"), text)

    def test_a_hard_bounce_is_attributed_to_the_recipient(self):
        item = inbound(
            "mailer-daemon@acme.com",
            subject="Undelivered Mail Returned to Sender",
            body="550 5.1.1 <dana@acme.com>: Recipient address rejected: User unknown",
        )
        self.assertEqual(replies.classify(item, self.written), ("bounced", "dana@acme.com"))

    def test_a_soft_bounce_is_not_treated_as_hard(self):
        item = inbound(
            "postmaster@acme.com",
            subject="Delayed delivery",
            body="Your message to dana@acme.com is delayed and will be retried.",
        )
        kind, _ = replies.classify(item, self.written)
        self.assertEqual(kind, "ignore")

    def test_a_daemon_about_someone_we_never_wrote_to_is_ignored(self):
        item = inbound("mailer-daemon@x.com", body="550 5.1.1 <nobody@zzz.com> User unknown")
        self.assertEqual(replies.classify(item, self.written), ("ignore", ""))


class TestApply(unittest.TestCase):
    def setUp(self):
        self.settings, self.roles = load_all(DEMO_SETTINGS)
        self.dir = tempfile.TemporaryDirectory()
        self.db = open_db(Path(self.dir.name) / "t.db")
        self.role = self.roles["head-of-operations"]
        pipeline.run_search(self.db, self.settings, self.role)
        pipeline.score_all(self.db, self.settings, self.role)
        for row in self.db.candidates(self.role.key, stages=["review"]):
            pipeline.set_review(self.db, self.role, int(row["id"]), "approve", "a detail")
        pipeline.enrich(self.db, self.settings, self.role)
        pipeline.verify_emails(self.db, self.settings, self.role)
        pipeline.queue_next(self.db, self.settings, self.role)
        pipeline.send_due(self.db, self.settings, self.role, live=False)
        self.address = replies.written_addresses(self.db).pop()

    def tearDown(self):
        self.db.close()
        self.dir.cleanup()

    def test_a_reply_stops_the_follow_up(self):
        self.assertTrue(replies.apply(self.db, "replied", self.address))
        row = self.db.one(
            "SELECT c.stage FROM candidates c JOIN emails e ON e.candidate_id = c.id "
            "WHERE e.address = ?",
            (self.address,),
        )
        self.assertEqual(row["stage"], "replied")
        pipeline.queue_next(self.db, self.settings, self.role)
        queued = self.db.query(
            "SELECT * FROM messages WHERE to_address = ? AND status = 'queued'",
            (self.address,),
        )
        self.assertEqual(queued, [], "a follow up was queued for someone who replied")

    def test_a_bounce_suppresses_the_address(self):
        replies.apply(self.db, "bounced", self.address)
        self.assertTrue(self.db.is_suppressed("email", self.address))

    def test_an_unsubscribe_suppresses_and_skips_queued_mail(self):
        pipeline.queue_next(self.db, self.settings, self.role)
        replies.apply(self.db, "unsubscribed", self.address)
        self.assertTrue(self.db.is_suppressed("email", self.address))
        left = self.db.query(
            "SELECT * FROM messages WHERE to_address = ? AND status = 'queued'",
            (self.address,),
        )
        self.assertEqual(left, [])

    def test_a_reply_never_walks_a_booking_backwards(self):
        row = self.db.one(
            "SELECT c.id FROM candidates c JOIN emails e ON e.candidate_id = c.id "
            "WHERE e.address = ?",
            (self.address,),
        )
        self.db.set_stage(int(row["id"]), "booked")
        replies.apply(self.db, "replied", self.address)
        after = self.db.candidate(int(row["id"]))
        self.assertEqual(after["stage"], "booked")

    def test_sync_reads_the_mailbox_and_applies(self):
        items = [
            inbound(self.address),
            inbound("stranger@nowhere.com"),
        ]
        with mock.patch.object(replies, "fetch", lambda settings, since=None: items):
            result = replies.sync(self.db, self.settings)
        self.assertEqual(result.counts.get("replied"), 1)
        self.assertEqual(result.counts.get("ignored"), 1)

    def test_fetch_routes_through_the_configured_provider(self):
        """The reply source is configurable, so a sequencer's inbox works too."""
        rows = [{"from_address": "A@Example.com", "subject": "Re: x", "body": "yes", "date": ""}]

        class FakeProvider:
            name = "fake"

            def __init__(self, _settings):
                pass

            def fetch_replies(self, since=None):
                return rows

        from outbound import providers

        providers.REGISTRY["replies"]["fake"] = FakeProvider
        try:
            import json as _json

            from outbound.config import Settings

            raw = _json.loads(_json.dumps(self.settings.raw))
            raw["providers"]["replies"] = "fake"
            out = replies.fetch(Settings(raw=raw))
        finally:
            providers.REGISTRY["replies"].pop("fake", None)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].from_address, "a@example.com")


if __name__ == "__main__":
    unittest.main()
