"""Provider adapter tests.

No network. A fake transport records every call, so a wrong header, a wrong
path or a wrong field name fails here instead of on a live run against a
vendor that charges per call.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from outbound import httpjson  # noqa: E402
from outbound import providers  # noqa: E402
from outbound.config import Settings, load_all  # noqa: E402
from outbound.errors import ConfigError, CredentialError  # noqa: E402

DEMO_SETTINGS = ROOT / "sample" / "settings.demo.toml"


class Recorder:
    """Stands in for httpjson.get and httpjson.post."""

    def __init__(self, response=None):
        self.calls: list[dict] = []
        self.response = response if response is not None else {}

    def __call__(self, url, headers=None, params=None, body=None, **kwargs):
        self.calls.append(
            {"url": url, "headers": headers or {}, "params": params or {}, "body": body}
        )
        if callable(self.response):
            return self.response(url, params, body)
        return self.response

    @property
    def last(self) -> dict:
        return self.calls[-1]


def settings_with(section: str, values: dict) -> Settings:
    _settings, _roles = load_all(DEMO_SETTINGS)
    raw = dict(_settings.raw)
    providers_block = dict(raw.get("providers") or {})
    providers_block[section] = values
    raw["providers"] = providers_block
    return Settings(raw=raw)


class ProviderTestCase(unittest.TestCase):
    """Sets the env keys every adapter asks for, and clears them after."""

    KEYS = {
        "APIFY_TOKEN": "tok", "APOLLO_API_KEY": "tok", "ROCKETREACH_API_KEY": "tok",
        "FINDYMAIL_API_KEY": "tok", "MILLIONVERIFIER_API_KEY": "tok",
        "NEVERBOUNCE_API_KEY": "tok", "INSTANTLY_API_KEY": "tok",
        "SMARTLEAD_API_KEY": "tok", "CALCOM_API_KEY": "tok", "CALENDLY_TOKEN": "tok",
    }

    def setUp(self):
        self._patch = mock.patch.dict(os.environ, self.KEYS)
        self._patch.start()
        self.settings, self.roles = load_all(DEMO_SETTINGS)

    def tearDown(self):
        self._patch.stop()


class TestRegistry(ProviderTestCase):
    def test_every_stage_has_a_dryrun_adapter(self):
        for stage in ("search", "enrich", "verify", "send", "booking"):
            self.assertIsNotNone(providers.build(stage, "dryrun", self.settings))

    def test_unknown_provider_names_the_options(self):
        with self.assertRaises(ConfigError) as ctx:
            providers.build("enrich", "nope", self.settings)
        self.assertIn("Available", str(ctx.exception))

    def test_none_disables_a_stage(self):
        self.assertIsNone(providers.build("verify", "none", self.settings))

    def test_a_missing_key_is_a_clear_error(self):
        with mock.patch.dict(os.environ, {"APOLLO_API_KEY": ""}):
            adapter = providers.build("enrich", "apollo", self.settings)
            with self.assertRaises(CredentialError):
                adapter.find_email({"full_name": "A B"})


class TestEnrichAdapters(ProviderTestCase):
    def test_apollo_sends_the_key_header_and_never_reveals_personal_email(self):
        recorder = Recorder({"person": {"email": "a.b@acme.com", "email_status": "verified"}})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("enrich", "apollo", self.settings)
            out = adapter.find_email(
                {"full_name": "A B", "first_name": "A", "last_name": "B",
                 "company": "Acme", "linkedin_url": "https://linkedin.com/in/ab"}
            )
        self.assertEqual(out[0]["address"], "a.b@acme.com")
        self.assertGreater(out[0]["confidence"], 0.9)
        self.assertIn("X-Api-Key", recorder.last["headers"])
        self.assertIs(recorder.last["body"]["reveal_personal_emails"], False)
        self.assertTrue(recorder.last["url"].endswith("/people/match"))

    def test_apollo_drops_a_locked_placeholder_address(self):
        recorder = Recorder({"person": {"email": "email_not_unlocked@domain.com"}})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("enrich", "apollo", self.settings)
            self.assertEqual(adapter.find_email({"full_name": "A B"}), [])

    def test_rocketreach_drops_personal_addresses_and_ranks_by_grade(self):
        recorder = Recorder(
            {
                "status": "complete",
                "emails": [
                    {"email": "personal@gmail.com", "type": "personal", "grade": "A"},
                    {"email": "c@acme.com", "type": "professional", "grade": "C"},
                    {"email": "a@acme.com", "type": "professional", "grade": "A"},
                ],
            }
        )
        with mock.patch.object(httpjson, "get", recorder):
            adapter = providers.build("enrich", "rocketreach", self.settings)
            out = adapter.find_email({"linkedin_url": "https://linkedin.com/in/ab"})
        self.assertEqual([e["address"] for e in out], ["a@acme.com", "c@acme.com"])
        self.assertIn("Api-Key", recorder.last["headers"])
        self.assertEqual(recorder.last["params"]["li_url"], "https://linkedin.com/in/ab")

    def test_findymail_uses_the_linkedin_endpoint_when_it_can(self):
        recorder = Recorder({"contact": {"email": "a@acme.com"}})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("enrich", "findymail", self.settings)
            out = adapter.find_email({"linkedin_url": "https://linkedin.com/in/ab"})
        self.assertEqual(out[0]["address"], "a@acme.com")
        self.assertTrue(recorder.last["url"].endswith("/search/linkedin"))
        self.assertTrue(recorder.last["headers"]["Authorization"].startswith("Bearer "))

    def test_findymail_returns_nothing_when_it_has_neither_input(self):
        adapter = providers.build("enrich", "findymail", self.settings)
        self.assertEqual(adapter.find_email({"full_name": "A B"}), [])


class TestVerifyAdapters(ProviderTestCase):
    def test_millionverifier_maps_every_result_to_our_vocabulary(self):
        cases = {"ok": "valid", "catch_all": "catch_all", "invalid": "invalid",
                 "disposable": "invalid", "unknown": "unknown", "weird": "unknown"}
        for raw, expected in cases.items():
            with mock.patch.object(httpjson, "get", Recorder({"result": raw})):
                adapter = providers.build("verify", "millionverifier", self.settings)
                self.assertEqual(adapter.verify("a@b.com"), expected, raw)

    def test_neverbounce_maps_accept_all_to_catch_all(self):
        with mock.patch.object(httpjson, "get", Recorder({"result": "accept_all"})):
            adapter = providers.build("verify", "neverbounce", self.settings)
            self.assertEqual(adapter.verify("a@b.com"), "catch_all")


class TestSendAdapters(ProviderTestCase):
    def test_instantly_needs_a_campaign(self):
        with self.assertRaises(ConfigError):
            providers.build("send", "instantly", settings_with("instantly", {}))

    def test_instantly_routes_per_role(self):
        settings = settings_with(
            "instantly", {"campaign_id": "default", "campaign_by_role": {"engineer": "eng"}}
        )
        recorder = Recorder({"id": "lead_1"})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("send", "instantly", settings)
            adapter.send({"to": "a@b.com", "subject": "s", "body": "b", "step": 1,
                          "role_key": "engineer"})
            self.assertEqual(recorder.last["body"]["campaign"], "eng")
            adapter.send({"to": "a@b.com", "subject": "s", "body": "b", "step": 1,
                          "role_key": "head-of-operations"})
            self.assertEqual(recorder.last["body"]["campaign"], "default")
        self.assertTrue(recorder.last["headers"]["Authorization"].startswith("Bearer "))

    def test_smartlead_puts_the_key_in_the_query(self):
        settings = settings_with("smartlead", {"campaign_id": "42"})
        recorder = Recorder({"id": 7})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("send", "smartlead", settings)
            adapter.send({"to": "a.b@x.com", "subject": "s", "body": "b", "step": 1,
                          "role_key": "engineer"})
        self.assertIn("/campaigns/42/leads", recorder.last["url"])
        self.assertEqual(recorder.last["params"]["api_key"], "tok")


class TestBookingAdapters(ProviderTestCase):
    def test_calcom_sends_the_version_header_and_reads_attendees(self):
        recorder = Recorder(
            {
                "data": [
                    {
                        "uid": "abc",
                        "start": "2026-09-02T15:00:00Z",
                        "end": "2026-09-02T15:10:00Z",
                        "attendees": [{"name": "Dana Reyes", "email": "Dana@Acme.com"}],
                        "bookingFieldsResponses": {
                            "name": "Dana", "email": "Dana@Acme.com",
                            "years-owning-ops": "Six years",
                        },
                    }
                ]
            }
        )
        with mock.patch.object(httpjson, "get", recorder):
            adapter = providers.build("booking", "calcom", self.settings)
            out = adapter.list_bookings()
        self.assertEqual(out[0]["provider_id"], "abc")
        self.assertEqual(out[0]["attendee_email"], "dana@acme.com")
        self.assertEqual(out[0]["answers"], {"years-owning-ops": "Six years"})
        self.assertIn("cal-api-version", recorder.last["headers"])

    def test_calcom_cancel_sends_a_reason(self):
        recorder = Recorder({})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("booking", "calcom", self.settings)
            self.assertTrue(adapter.cancel("abc", "not a fit"))
        self.assertIn("/bookings/abc/cancel", recorder.last["url"])
        self.assertEqual(recorder.last["body"]["cancellationReason"], "not a fit")

    def test_calendly_needs_an_organization_or_user(self):
        with self.assertRaises(ConfigError):
            providers.build("booking", "calendly", settings_with("calendly", {}))

    def test_calendly_pairs_events_with_invitee_answers(self):
        def respond(url, params, body):
            if url.endswith("/scheduled_events"):
                return {"collection": [{"uri": "https://api.calendly.com/scheduled_events/e1",
                                        "start_time": "2026-09-02T15:00:00Z",
                                        "end_time": "2026-09-02T15:10:00Z"}]}
            return {"collection": [{"name": "Dana", "email": "d@acme.com",
                                    "questions_and_answers": [
                                        {"question": "Target comp?", "answer": "$16k"}]}]}

        settings = settings_with("calendly", {"user": "https://api.calendly.com/users/u1"})
        recorder = Recorder(respond)
        with mock.patch.object(httpjson, "get", recorder):
            adapter = providers.build("booking", "calendly", settings)
            out = adapter.list_bookings()
        self.assertEqual(out[0]["provider_id"], "e1")
        self.assertEqual(out[0]["answers"], {"Target comp?": "$16k"})


class TestApifySafety(ProviderTestCase):
    def test_an_actor_is_required(self):
        with self.assertRaises(ConfigError):
            providers.build("search", "apify", settings_with("apify", {}))

    def test_a_cookie_actor_is_refused_by_default(self):
        settings = settings_with(
            "apify", {"actor": "someone/linkedin-scraper", "input": {"sessionCookie": "li_at=..."}}
        )
        with self.assertRaises(ConfigError) as ctx:
            providers.build("search", "apify", settings)
        self.assertIn("cookie", str(ctx.exception).lower())

    def test_a_cookie_actor_is_allowed_only_on_purpose(self):
        settings = settings_with(
            "apify",
            {"actor": "someone/linkedin-scraper", "cookie_actor_ok": True,
             "input": {"sessionCookie": "li_at=..."}},
        )
        self.assertIsNotNone(providers.build("search", "apify", settings))

    def test_actor_slug_is_converted_for_the_path(self):
        settings = settings_with("apify", {"actor": "someone/linkedin-scraper"})
        recorder = Recorder([{"fullName": "A B"}])
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("search", "apify", settings)
            out = adapter.search({"name": "s1", "boolean": "x", "titles": [], "geo": []}, 5)
        self.assertIn("someone~linkedin-scraper", recorder.last["url"])
        self.assertEqual(out[0]["_search"], "s1")


class TestHttp(unittest.TestCase):
    def test_params_are_appended_and_none_dropped(self):
        recorder = []

        class FakeResponse:
            def read(self):
                return b'{"ok": true}'

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(request, timeout=None):
            recorder.append(request.full_url)
            return FakeResponse()

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            out = httpjson.get("https://x.test/a", params={"k": "v", "skip": None})
        self.assertEqual(out, {"ok": True})
        self.assertIn("k=v", recorder[0])
        self.assertNotIn("skip", recorder[0])

    def test_retries_then_raises_with_the_status(self):
        import urllib.error

        attempts = []

        def fake_urlopen(request, timeout=None):
            attempts.append(1)
            raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(httpjson.HttpError) as ctx:
                httpjson.get("https://x.test/a", retries=2, sleep=lambda _s: None)
        self.assertEqual(ctx.exception.status, 503)
        self.assertEqual(len(attempts), 3)

    def test_a_4xx_is_not_retried(self):
        import urllib.error

        attempts = []

        def fake_urlopen(request, timeout=None):
            attempts.append(1)
            raise urllib.error.HTTPError(request.full_url, 401, "no", {}, None)

        with mock.patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(httpjson.HttpError):
                httpjson.get("https://x.test/a", retries=3, sleep=lambda _s: None)
        self.assertEqual(len(attempts), 1)


if __name__ == "__main__":
    unittest.main()
