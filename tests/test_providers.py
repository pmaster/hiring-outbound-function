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
        "ZEROBOUNCE_API_KEY": "tok",
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
                adapter.find_email({"linkedin_url": "https://linkedin.com/in/ab"})


class TestEnrichAdapters(ProviderTestCase):
    def test_apollo_sends_parameters_in_the_query_not_the_body(self):
        """Apollo declares every parameter as in=query and has no request
        body. A JSON body is a silent no-op: you get results, they are just
        not filtered the way you asked."""
        recorder = Recorder({"person": {"email": "a.b@acme.com", "email_status": "verified"}})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("enrich", "apollo", self.settings)
            out = adapter.find_email(
                {"full_name": "A B", "first_name": "A", "last_name": "B",
                 "company": "Acme", "linkedin_url": "https://linkedin.com/in/ab"}
            )
        self.assertEqual(out[0]["address"], "a.b@acme.com")
        self.assertGreater(out[0]["confidence"], 0.9)
        self.assertIn("x-api-key", recorder.last["headers"])
        self.assertIsNone(recorder.last["body"], "a body here is silently ignored")
        self.assertEqual(recorder.last["params"]["reveal_personal_emails"], "false")
        self.assertEqual(
            recorder.last["params"]["linkedin_url"], "https://linkedin.com/in/ab"
        )
        self.assertTrue(recorder.last["url"].endswith("/people/match"))

    def test_apollo_search_uses_the_api_search_path_and_bracketed_arrays(self):
        recorder = Recorder({"people": []})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("search", "apollo", self.settings)
            adapter.search(
                {"name": "s1", "titles": ["Head of Operations", "Director of Operations"],
                 "geo": ["United States"], "seniority": ["director"],
                 "headcount": ["51-200"], "keywords": "built"},
                50,
            )
        self.assertTrue(recorder.last["url"].endswith("/mixed_people/api_search"))
        params = recorder.last["params"]
        self.assertEqual(params["person_titles[]"], ["Head of Operations", "Director of Operations"])
        self.assertEqual(params["person_seniorities[]"], ["director"])
        self.assertEqual(params["organization_num_employees_ranges[]"], ["51,200"])
        self.assertIsNone(recorder.last["body"])

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
        self.assertEqual(
            recorder.last["params"]["linkedin_url"], "https://linkedin.com/in/ab"
        )

    def test_rocketreach_polls_checkstatus_not_the_lookup(self):
        """Repeating the lookup can bill again. checkStatus does not."""
        calls = []

        def respond(url, params, body):
            calls.append(url)
            if url.endswith("/person/lookup"):
                return {"id": 5244, "status": "searching", "emails": []}
            return [{"id": 5244, "status": "complete",
                     "emails": [{"email": "a@acme.com", "type": "professional", "grade": "A"}]}]

        recorder = Recorder(respond)
        with mock.patch.object(httpjson, "get", recorder):
            adapter = providers.build("enrich", "rocketreach", self.settings)
            out = adapter.find_email(
                {"linkedin_url": "https://linkedin.com/in/ab"}, sleep=lambda _s: None
            )
        self.assertEqual(out[0]["address"], "a@acme.com")
        self.assertEqual(calls.count("https://api.rocketreach.co/api/v2/person/lookup"), 1)
        self.assertIn("https://api.rocketreach.co/api/v2/person/checkStatus", calls)

    def test_rocketreach_gives_up_on_a_failed_lookup(self):
        recorder = Recorder({"id": 1, "status": "failed", "emails": []})
        with mock.patch.object(httpjson, "get", recorder):
            adapter = providers.build("enrich", "rocketreach", self.settings)
            out = adapter.find_email(
                {"linkedin_url": "https://linkedin.com/in/ab"}, sleep=lambda _s: None
            )
        self.assertEqual(out, [])

    def test_findymail_uses_the_business_profile_endpoint(self):
        """The path is /api/search/business-profile. /api/search/linkedin does
        not exist, and the first version of this adapter used it."""
        recorder = Recorder({"contact": {"email": "a@acme.com"}})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("enrich", "findymail", self.settings)
            out = adapter.find_email({"linkedin_url": "https://linkedin.com/in/ab"})
        self.assertEqual(out[0]["address"], "a@acme.com")
        self.assertTrue(recorder.last["url"].endswith("/api/search/business-profile"))
        self.assertEqual(recorder.last["body"], {"linkedin_url": "https://linkedin.com/in/ab"})
        self.assertTrue(recorder.last["headers"]["Authorization"].startswith("Bearer "))

    def test_findymail_reads_through_the_async_payload_wrapper(self):
        recorder = Recorder({"payload": {"contact": {"email": "a@acme.com"}}})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("enrich", "findymail", self.settings)
            out = adapter.find_email({"linkedin_url": "https://linkedin.com/in/ab"})
        self.assertEqual(out[0]["address"], "a@acme.com")

    def test_findymail_falls_back_to_name_and_company(self):
        recorder = Recorder({"contact": {"email": "a@acme.com"}})
        with mock.patch.object(httpjson, "post", recorder):
            adapter = providers.build("enrich", "findymail", self.settings)
            adapter.find_email({"full_name": "A B", "company": "Acme"})
        self.assertTrue(recorder.last["url"].endswith("/api/search/name"))
        self.assertEqual(recorder.last["body"], {"name": "A B", "domain": "Acme"})

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

    def test_neverbounce_maps_accept_all_to_catch_all_on_v4_2(self):
        recorder = Recorder({"status": "success", "result": "accept_all"})
        with mock.patch.object(httpjson, "get", recorder):
            adapter = providers.build("verify", "neverbounce", self.settings)
            self.assertEqual(adapter.verify("a@b.com"), "catch_all")
        self.assertIn("/v4.2/single/check", recorder.last["url"])

    def test_neverbounce_treats_a_non_success_status_as_unknown(self):
        with mock.patch.object(httpjson, "get", Recorder({"status": "auth_failure"})):
            adapter = providers.build("verify", "neverbounce", self.settings)
            self.assertEqual(adapter.verify("a@b.com"), "unknown")

    def test_zerobounce_maps_every_status(self):
        cases = {"valid": "valid", "invalid": "invalid", "catch-all": "catch_all",
                 "spamtrap": "invalid", "abuse": "invalid", "do_not_mail": "invalid",
                 "unknown": "unknown", "surprise": "unknown"}
        for raw, expected in cases.items():
            with mock.patch.object(httpjson, "get", Recorder({"status": raw})):
                adapter = providers.build("verify", "zerobounce", self.settings)
                self.assertEqual(adapter.verify("a@b.com"), expected, raw)

    def test_zerobounce_regional_host(self):
        adapter = providers.build("verify", "zerobounce", settings_with("zerobounce", {"region": "eu"}))
        self.assertIn("api-eu.zerobounce.net", adapter.base)
        plain = providers.build("verify", "zerobounce", settings_with("zerobounce", {}))
        self.assertIn("//api.zerobounce.net", plain.base)

    def test_millionverifier_path_has_no_trailing_slash(self):
        recorder = Recorder({"result": "ok"})
        with mock.patch.object(httpjson, "get", recorder):
            adapter = providers.build("verify", "millionverifier", self.settings)
            adapter.verify("a@b.com")
        self.assertTrue(recorder.last["url"].endswith("/api/v3"))


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


class TestRepliesAdapters(ProviderTestCase):
    def test_instantly_reads_received_mail_from_the_unibox(self):
        settings = settings_with("instantly", {"campaign_id": "c1"})
        recorder = Recorder({
            "items": [{
                "from_address_email": "Dana@Acme.com",
                "subject": "Re: the ops seat",
                "body_text": "Happy to talk.",
                "timestamp_created": "2026-09-01T10:00:00Z",
            }],
        })
        with mock.patch.object(httpjson, "get", recorder):
            adapter = providers.build("replies", "instantly", settings)
            out = adapter.fetch_replies()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["from_address"], "Dana@Acme.com")
        self.assertTrue(recorder.last["url"].endswith("/api/v2/emails"))
        self.assertEqual(recorder.last["params"]["email_type"], "received")
        self.assertEqual(recorder.last["params"]["campaign_id"], "c1")

    def test_imap_replies_adapter_delegates(self):
        from outbound import replies as replies_mod

        fake = [replies_mod.Inbound("a@b.com", "s", "body", "")]
        with mock.patch.object(replies_mod, "fetch_imap", lambda since=None, folders=("INBOX",): fake):
            adapter = providers.build("replies", "imap", self.settings)
            out = adapter.fetch_replies()
        self.assertEqual(out[0]["from_address"], "a@b.com")


class TestBookingAdapters(ProviderTestCase):
    def test_calcom_uses_a_different_version_per_endpoint(self):
        """cal-api-version is per endpoint. Listing wants 2026-05-01 and
        cancelling wants 2026-02-25. The wrong one is a 400."""
        from outbound.providers.calcom import (
            VERSION_CANCEL_BOOKING, VERSION_LIST_BOOKINGS,
        )

        self.assertNotEqual(VERSION_LIST_BOOKINGS, VERSION_CANCEL_BOOKING)
        listing = Recorder({"data": [], "pagination": {"hasMore": False}})
        with mock.patch.object(httpjson, "get", listing):
            adapter = providers.build("booking", "calcom", self.settings)
            adapter.list_bookings()
        self.assertEqual(listing.last["headers"]["cal-api-version"], VERSION_LIST_BOOKINGS)

        cancelling = Recorder({})
        with mock.patch.object(httpjson, "post", cancelling):
            adapter.cancel("abc", "not a fit")
        self.assertEqual(cancelling.last["headers"]["cal-api-version"], VERSION_CANCEL_BOOKING)

    def test_calcom_pages_through_bookings(self):
        pages = [
            {"data": [{"uid": "a", "attendees": [{"name": "A", "email": "a@x.com"}]}],
             "pagination": {"hasMore": True, "cursor": "c1"}},
            {"data": [{"uid": "b", "attendees": [{"name": "B", "email": "b@x.com"}]}],
             "pagination": {"hasMore": False}},
        ]
        seen = iter(pages)
        with mock.patch.object(httpjson, "get", lambda *a, **k: next(seen)):
            adapter = providers.build("booking", "calcom", self.settings)
            out = adapter.list_bookings()
        self.assertEqual([b["provider_id"] for b in out], ["a", "b"])

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

    def test_apify_uses_the_async_run_path_not_run_sync(self):
        """run-sync is cut off at 300 seconds. Any real sourcing run is
        longer, so the adapter starts a run, polls, then reads the dataset."""
        settings = settings_with(
            "apify", {"actor": "someone/linkedin-scraper", "max_charge_usd": 10}
        )
        posts, gets = [], []

        def on_post(url, headers=None, params=None, body=None, **kw):
            posts.append({"url": url, "params": params or {}, "body": body})
            return {"data": {"id": "run1", "status": "RUNNING"}}

        def on_get(url, headers=None, params=None, body=None, **kw):
            gets.append({"url": url, "params": params or {}})
            if url.endswith("/actor-runs/run1"):
                return {"data": {"id": "run1", "status": "SUCCEEDED"}}
            return [{"fullName": "A B"}]

        with mock.patch.object(httpjson, "post", on_post), \
             mock.patch.object(httpjson, "get", on_get):
            adapter = providers.build("search", "apify", settings)
            out = adapter.search(
                {"name": "s1", "boolean": "x", "titles": [], "geo": []}, 5,
                sleep=lambda _s: None,
            )
        self.assertTrue(posts[0]["url"].endswith("/actors/someone~linkedin-scraper/runs"))
        self.assertNotIn("run-sync", posts[0]["url"])
        self.assertEqual(posts[0]["params"]["maxTotalChargeUsd"], 10)
        self.assertEqual(posts[0]["params"]["maxItems"], 5)
        self.assertTrue(any("/actor-runs/run1" == g["url"].split("apify.com/v2")[1] for g in gets))
        self.assertTrue(any(g["url"].endswith("/actor-runs/run1/dataset/items") for g in gets))
        self.assertEqual(out[0]["_search"], "s1")

    def test_apify_raises_when_a_run_does_not_succeed(self):
        settings = settings_with("apify", {"actor": "someone/x"})
        with mock.patch.object(httpjson, "post", Recorder({"data": {"id": "r", "status": "RUNNING"}})), \
             mock.patch.object(httpjson, "get", Recorder({"data": {"id": "r", "status": "FAILED", "statusMessage": "boom"}})):
            adapter = providers.build("search", "apify", settings)
            with self.assertRaises(Exception) as ctx:
                adapter.search({"name": "s", "boolean": "x", "titles": [], "geo": []}, 5,
                               sleep=lambda _s: None)
        self.assertIn("FAILED", str(ctx.exception))

    def test_apify_uses_a_bearer_header_not_a_url_token(self):
        settings = settings_with("apify", {"actor": "someone/x"})
        recorder = Recorder({"data": {"id": "r", "status": "SUCCEEDED"}})
        with mock.patch.object(httpjson, "post", recorder), \
             mock.patch.object(httpjson, "get", Recorder([])):
            adapter = providers.build("search", "apify", settings)
            adapter.search({"name": "s", "boolean": "x", "titles": [], "geo": []}, 5,
                           sleep=lambda _s: None)
        self.assertTrue(recorder.last["headers"]["Authorization"].startswith("Bearer "))
        self.assertNotIn("token", recorder.last["params"])


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
