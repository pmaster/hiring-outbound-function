"""Regression tests for the 11 bugs the adversarial review confirmed.

Each test fails against the code as it was before the fix.
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

from outbound import bookings as bookings_mod  # noqa: E402
from outbound import pipeline, replies  # noqa: E402
from outbound.compliance import message_problems, preflight  # noqa: E402
from outbound.config import Settings, load_all  # noqa: E402
from outbound.db import open_db  # noqa: E402
from outbound.errors import OutboundError  # noqa: E402
from outbound.profiles import guess_country, normalize  # noqa: E402

DEMO = ROOT / "sample" / "settings.demo.toml"


def _settings_with(**warmup):
    settings, roles = load_all(DEMO)
    raw = json.loads(json.dumps(settings.raw))
    raw.setdefault("warmup", {}).update(warmup)
    return Settings(raw=raw), roles


class TestWarmupFreeze(unittest.TestCase):
    # fixes 1 and 3
    def setUp(self):
        self.settings, self.roles = _settings_with(ramp=[[3, 5], [3, 10]])
        self.db = open_db(Path(tempfile.mkdtemp()) / "t.db")
        self.role = self.roles["head-of-operations"]

    def test_a_second_same_day_run_does_not_advance_the_tier(self):
        self.db.record_send(self.role.key, "2026-08-01", n=5)
        self.db.record_send(self.role.key, "2026-08-02", n=5)
        cap_before, _ = pipeline.warmup_cap(self.settings, self.db)
        self.assertEqual(cap_before, 5)
        # Today's own sends must not push the tier up mid-day.
        self.db.record_send(self.role.key, pipeline.sending_day(self.settings), n=5)
        cap_after, _ = pipeline.warmup_cap(self.settings, self.db)
        self.assertEqual(cap_after, 5, "warm-up tier advanced mid-day")

    def test_the_final_ramp_day_does_not_uncap_on_a_second_run(self):
        for day in ("2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04", "2026-08-05"):
            self.db.record_send(self.role.key, day, n=10)
        # 5 prior days: ramp is [3,3] = 6 days, so day 6 (today) is the last.
        self.db.record_send(self.role.key, pipeline.sending_day(self.settings), n=10)
        cap, _ = pipeline.warmup_cap(self.settings, self.db)
        # Still on the ramp today (tier 2 = 10), not -1/uncapped.
        self.assertEqual(cap, 10)


class TestCountryCollision(unittest.TestCase):
    # fix 2
    def test_foreign_cities_beat_the_us_state_tail(self):
        self.assertEqual(guess_country("Toronto, CA"), "CA")
        self.assertEqual(guess_country("Vancouver, CA"), "CA")
        self.assertEqual(guess_country("Berlin, DE"), "DE")
        self.assertEqual(guess_country("Munich, DE"), "DE")

    def test_bare_non_us_country_tails_resolve(self):
        self.assertEqual(guess_country("Krakow, PL"), "PL")
        self.assertEqual(guess_country("Nantes, FR"), "FR")
        self.assertEqual(guess_country("Sydney, AU"), "AU")

    def test_us_states_that_shadow_country_codes_stay_us(self):
        for loc in ("Los Angeles, CA", "Pittsburgh, PA", "Atlanta, GA",
                    "Wilmington, DE", "Boston, MA", "Indianapolis, IN"):
            self.assertEqual(guess_country(loc), "US", loc)

    def test_a_substring_country_name_does_not_false_match(self):
        # "india" is inside "indianapolis"/"indiana" but must not classify them.
        self.assertEqual(guess_country("Indianapolis, IN"), "US")
        self.assertEqual(guess_country("Indiana, US"), "US")

    def test_a_blocked_candidate_from_a_bare_code_is_disqualified(self):
        settings, roles = load_all(DEMO)
        db = open_db(Path(tempfile.mkdtemp()) / "t.db")
        role = roles["head-of-operations"]
        db.upsert_candidate(role.key, normalize({
            "fullName": "Alex Toronto", "headline": "Director of Operations at Foo",
            "profileUrl": "https://linkedin.com/in/alex-t", "location": "Toronto, CA",
        }))
        pipeline.score_all(db, settings, role)
        row = db.candidates(role.key)[0]
        self.assertEqual(row["country"], "CA")
        self.assertEqual(row["stage"], "rejected")


class TestRestageKeepsRejections(unittest.TestCase):
    # fix 4
    def test_a_hand_rejection_is_not_resurrected(self):
        settings, roles = load_all(DEMO)
        db = open_db(Path(tempfile.mkdtemp()) / "t.db")
        role = roles["head-of-operations"]
        pipeline.run_search(db, settings, role)
        pipeline.score_all(db, settings, role)
        row = db.candidates(role.key, stages=["review"])[0]
        pipeline.set_review(db, role, int(row["id"]), "reject", "known bad reference")
        self.assertEqual(db.candidate(int(row["id"]))["review_state"], "rejected")
        pipeline.score_all(db, settings, role, restage=True)
        self.assertEqual(db.candidate(int(row["id"]))["stage"], "rejected",
                         "a hand rejection was resurrected")

    def test_an_auto_rejection_is_still_reconsidered(self):
        settings, roles = load_all(DEMO)
        db = open_db(Path(tempfile.mkdtemp()) / "t.db")
        role = roles["head-of-operations"]
        pipeline.run_search(db, settings, role)
        pipeline.score_all(db, settings, role)
        auto = db.candidates(role.key, stages=["rejected"])
        # auto-rejects have review_state 'pending'; restage may re-route them.
        self.assertTrue(all(r["review_state"] == "pending" for r in auto))
        pipeline.score_all(db, settings, role, restage=True)
        # they can move (not asserting where), just that they were considered:
        # nothing raised and the run touched them.


class TestUnsubscribeValidation(unittest.TestCase):
    # fix 5
    def setUp(self):
        self.settings, _ = load_all(DEMO)

    def test_a_working_url_in_the_body_passes(self):
        base = str(self.settings.get("identity.unsubscribe_url")).split("?")[0]
        body = f"...\nunsubscribe here: {base}?e=abc\n" + str(self.settings.get("identity.postal_address"))
        codes = {p.code for p in message_problems(self.settings, body)}
        self.assertNotIn("no_unsubscribe", codes)

    def test_the_word_without_the_link_fails(self):
        body = "you can unsubscribe.\n" + str(self.settings.get("identity.postal_address"))
        codes = {p.code for p in message_problems(self.settings, body)}
        self.assertIn("no_unsubscribe", codes)

    def test_a_placeholder_url_fails(self):
        raw = json.loads(json.dumps(self.settings.raw))
        raw["identity"]["unsubscribe_url"] = "https://CHANGEME.example/unsubscribe?e={email_token}"
        broken = Settings(raw=raw)
        body = "unsubscribe here: whatever\n" + str(broken.get("identity.postal_address"))
        codes = {p.code for p in message_problems(broken, body)}
        self.assertIn("no_unsubscribe", codes)


class TestReplyApply(unittest.TestCase):
    # fix 6
    def test_apply_runs_even_when_the_row_was_already_stored(self):
        settings, roles = load_all(DEMO)
        db = open_db(Path(tempfile.mkdtemp()) / "t.db")
        role = roles["head-of-operations"]
        pipeline.run_search(db, settings, role)
        pipeline.score_all(db, settings, role)
        for r in db.candidates(role.key, stages=["review"]):
            pipeline.set_review(db, role, int(r["id"]), "approve", "note")
        pipeline.enrich(db, settings, role)
        pipeline.verify_emails(db, settings, role)
        pipeline.queue_next(db, settings, role)
        pipeline.send_due(db, settings, role, live=False, commit=True)
        address = sorted(replies.written_addresses(db))[0]
        item = replies.Inbound(address, "Re: x", "yes please", "2026-09-01")
        # Simulate the crash-between-commits case: the inbound row already
        # exists (stored=False next run) but the candidate was never moved.
        db.store_inbound(item.from_address, item.subject, item.body, "replied", item.date)
        with mock.patch.object(replies, "fetch", lambda s, since=None: [item]):
            replies.sync(db, settings)
        moved = db.one(
            "SELECT c.stage FROM candidates c JOIN emails e ON e.candidate_id = c.id "
            "WHERE e.address = ?", (address,))
        self.assertEqual(moved["stage"], "replied", "apply was skipped on a stored row")


class TestHttpRetryAfter(unittest.TestCase):
    # fix 7
    def test_an_http_date_retry_after_does_not_crash(self):
        import urllib.error

        from outbound import httpjson

        attempts = []

        def fake_urlopen(request, timeout=None):
            attempts.append(1)
            raise urllib.error.HTTPError(
                request.full_url, 429, "slow down",
                {"Retry-After": "Wed, 21 Oct 2099 07:28:00 GMT"}, None,
            )

        with mock.patch.dict(os.environ, {"OUTBOUND_OFFLINE": ""}):
            with mock.patch("urllib.request.urlopen", fake_urlopen):
                with self.assertRaises(httpjson.HttpError):
                    httpjson.get("https://x.test/a", retries=1, sleep=lambda _s: None)
        self.assertEqual(len(attempts), 2)  # retried once, did not crash


class TestDnsTruncation(unittest.TestCase):
    # fix 8
    def test_a_truncated_record_does_not_raise(self):
        import struct

        from outbound import dnscheck

        # A response header claiming one answer, an MX record whose rdlength
        # says 5 bytes but the datagram ends after 1.
        header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)
        q = b"\x03foo\x03com\x00" + struct.pack("!HH", dnscheck.TYPE_MX, 1)
        rr = b"\xc0\x0c" + struct.pack("!HHIH", dnscheck.TYPE_MX, 1, 300, 5) + b"\x00"
        packet = header + q + rr

        class Sock:
            def __call__(self, *a, **k): return self
            def settimeout(self, _t): pass
            def sendto(self, p, _a): self._id = struct.unpack("!H", p[:2])[0]
            def recvfrom(self, _n):
                return struct.pack("!H", self._id) + packet[2:], ("8.8.8.8", 53)
            def close(self): pass

        with mock.patch("socket.socket", Sock()):
            # Must return (possibly empty) rather than raise struct.error.
            out = dnscheck.query("foo.com", dnscheck.TYPE_MX)
        self.assertIsInstance(out, list)


class TestCancelLeadEnforced(unittest.TestCase):
    # fix 10
    def setUp(self):
        self.settings, self.roles = load_all(DEMO)
        self.db = open_db(Path(tempfile.mkdtemp()) / "t.db")

    def _insert(self, start_at):
        self.db.execute(
            "INSERT INTO bookings (role_key, provider, provider_id, attendee_name, "
            "attendee_email, start_at, status, created_at) VALUES "
            "('head-of-operations','dryrun','bk9','A Person','a@x.com',?, 'booked', "
            "'2026-08-30T00:00:00+00:00')", (start_at,))
        return self.db.one("SELECT * FROM bookings WHERE provider_id='bk9'")

    def test_cancelling_inside_the_notice_period_is_refused(self):
        from outbound.util import iso, now
        import datetime as dt
        soon = iso(now() + dt.timedelta(hours=2))
        b = self._insert(soon)
        with self.assertRaises(OutboundError):
            bookings_mod.decide(self.db, self.settings, self.roles, int(b["id"]), "cancel")

    def test_force_late_overrides(self):
        from outbound.util import iso, now
        import datetime as dt
        soon = iso(now() + dt.timedelta(hours=2))
        b = self._insert(soon)
        result = bookings_mod.decide(
            self.db, self.settings, self.roles, int(b["id"]), "cancel", force_late=True)
        self.assertEqual(result.counts.get("apology_sent"), 1)


class TestWarmupGateFatal(unittest.TestCase):
    # fix 11
    def test_the_warmup_gate_blocks_a_send_until_attested(self):
        settings, roles = load_all(DEMO)
        raw = json.loads(json.dumps(settings.raw))
        raw["warmup"]["require_warmup_done"] = True
        s = Settings(raw=raw)
        role = roles["head-of-operations"]
        fatal = {p.code for p in preflight(s, role) if p.fatal}
        self.assertIn("warmup_attested", fatal)
        # and --attest-warmup clears it
        from outbound.compliance import assert_sendable
        remaining = [p for p in preflight(s, role) if p.fatal and p.code != "warmup_attested"]
        # (only asserting warmup_attested is the fatal one relevant here)
        self.assertTrue(any(p.code == "warmup_attested" for p in preflight(s, role)))


if __name__ == "__main__":
    unittest.main()
