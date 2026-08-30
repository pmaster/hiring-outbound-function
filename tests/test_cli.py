"""CLI smoke tests.

Every command runs, and every error path fails with a readable message rather
than a traceback. This catches argparse wiring, which unit tests miss.
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import unittest
from pathlib import Path
from unittest import mock

# No test may reach the network. An unmocked call fails immediately and says so.
os.environ.setdefault("OUTBOUND_OFFLINE", "1")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from outbound.cli import main  # noqa: E402
from outbound.config import load_settings  # noqa: E402

DEMO_SETTINGS = ROOT / "sample" / "settings.demo.toml"
BASE = ["--config", str(DEMO_SETTINGS)]


def run(*args: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(BASE + list(args))
    return code, out.getvalue() + err.getvalue()


class TestCli(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings = load_settings(DEMO_SETTINGS)
        for directory in (settings.db_path.parent, settings.outbox_dir):
            if directory.exists() and "demo" in str(directory):
                shutil.rmtree(directory)
        code, _ = run("demo")
        assert code == 0, "demo must succeed before the CLI tests run"

    def test_read_only_commands_all_succeed(self):
        for args in (
            ("roles",), ("doctor",), ("doctor", "head-of-operations"),
            ("search", "engineer"), ("questions", "engineer"),
            ("review", "engineer"), ("review", "engineer", "--json"),
            ("bookings", "list"), ("bookings", "triage"),
            ("report",), ("report", "engineer"),
        ):
            with self.subTest(args=args):
                code, output = run(*args)
                self.assertEqual(code, 0, output)
                self.assertNotIn("Traceback", output)

    def test_pipeline_commands_all_succeed(self):
        for args in (
            ("score", "engineer"), ("enrich", "engineer"), ("verify", "engineer"),
            ("verify", "engineer", "--accept-risky"), ("queue", "engineer"),
            ("send", "engineer"), ("bookings", "sync"),
            ("suppress", "x@y.test"), ("suppress", "y.test", "--kind", "domain"),
            ("replies", "mark", "nobody@nowhere.test"),
        ):
            with self.subTest(args=args):
                code, output = run(*args)
                self.assertEqual(code, 0, output)
                self.assertNotIn("Traceback", output)

    def test_send_without_live_says_so(self):
        _code, output = run("send", "engineer")
        up = output.upper()
        # No --live is a preview now: it must say nothing was sent and
        # point at --live, so no one mistakes it for a real send.
        self.assertIn("PREVIEW", up)
        self.assertIn("--LIVE", up)

    def test_errors_are_messages_not_tracebacks(self):
        cases = [
            (("score", "nosuchrole"), "unknown role"),
            (("review", "engineer", "--approve", "999999"), "no candidate"),
            (("bookings", "decide", "999", "cancel"), "no booking"),
            (("import", "engineer", "/nope.csv"), "no such file"),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                code, output = run(*args)
                self.assertEqual(code, 2, output)
                self.assertNotIn("Traceback", output)
                self.assertIn(expected, output.lower())

    def test_a_missing_credential_is_a_readable_error(self):
        with mock.patch.dict(os.environ, {"IMAP_HOST": ""}):
            code, output = run("replies", "sync")
        self.assertEqual(code, 2, output)
        self.assertIn("IMAP_HOST", output)
        self.assertNotIn("Traceback", output)

    def test_doctor_reports_a_bounce_rate_over_the_ceiling(self):
        from outbound.config import load_all
        from outbound.db import open_db

        settings, _roles = load_all(DEMO_SETTINGS)
        db = open_db(settings.db_path)
        try:
            for index in range(60):
                cid, _ = db.upsert_candidate(
                    "engineer",
                    {"linkedin_url": f"linkedin.com/in/bounce{index}", "full_name": f"B {index}"},
                )
                address = f"bounce{index}@example.com"
                db.add_email(cid, address)
                mid = db.queue_message(cid, "engineer", 1, address, "s", "b",
                                       "2026-08-01T00:00:00+00:00")
                db.mark_sent(mid, "dryrun")
                if index < 20:
                    db.set_stage(cid, "bounced")
            code, output = run("doctor")
            self.assertEqual(code, 1, output)
            self.assertIn("bounce rate", output.lower())
        finally:
            # Leave the demo database as the other tests expect it.
            db.execute("DELETE FROM messages WHERE to_address LIKE 'bounce%'")
            db.execute("DELETE FROM candidates WHERE linkedin_key LIKE '%bounce%'")
            db.close()

    def test_pages_writes_a_site(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            code, output = run("pages", "--out", tmp)
            self.assertEqual(code, 0, output)
            self.assertTrue((Path(tmp) / "index.html").exists())
            self.assertTrue((Path(tmp) / "unsubscribe.html").exists())
            self.assertTrue((Path(tmp) / "roles" / "engineer.html").exists())

    def test_unknown_command_exits_non_zero(self):
        with self.assertRaises(SystemExit) as ctx:
            with contextlib.redirect_stderr(io.StringIO()):
                main(BASE + ["nonsense"])
        self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
