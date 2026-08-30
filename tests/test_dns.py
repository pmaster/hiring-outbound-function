"""DNS resolver and record checks.

The wire-format tests build real DNS response packets, so the parser is
exercised without touching the network. The record-logic tests stub `query`.
"""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from outbound import dnscheck  # noqa: E402


def encode_name(name: str) -> bytes:
    out = b""
    for label in name.strip(".").split("."):
        out += bytes([len(label)]) + label.encode()
    return out + b"\x00"


def build_response(request_id: int, qname: str, qtype: int, answers, rcode: int = 0) -> bytes:
    header = struct.pack("!HHHHHH", request_id, 0x8180 | rcode, 1, len(answers), 0, 0)
    body = encode_name(qname) + struct.pack("!HH", qtype, 1)
    for atype, rdata in answers:
        body += b"\xc0\x0c"  # pointer to the question name
        body += struct.pack("!HHIH", atype, 1, 300, len(rdata)) + rdata
    return header + body


def txt_rdata(*chunks: str) -> bytes:
    out = b""
    for chunk in chunks:
        raw = chunk.encode()
        out += bytes([len(raw)]) + raw
    return out


class FakeSocket:
    """Stands in for socket.socket, returning one canned response."""

    def __init__(self, response_for):
        self.response_for = response_for
        self.sent = None

    def __call__(self, *_a, **_k):
        return self

    def settimeout(self, _t):
        pass

    def sendto(self, packet, _addr):
        self.sent = packet

    def recvfrom(self, _size):
        request_id = struct.unpack("!H", self.sent[:2])[0]
        return self.response_for(request_id, self.sent), ("8.8.8.8", 53)

    def close(self):
        pass


class TestWireFormat(unittest.TestCase):
    def _query(self, answers, name="example.com", qtype=dnscheck.TYPE_TXT, rcode=0):
        def respond(request_id, _packet):
            return build_response(request_id, name, qtype, answers, rcode)

        with mock.patch("socket.socket", FakeSocket(respond)):
            return dnscheck.query(name, qtype)

    def test_txt_chunks_are_joined(self):
        """A long SPF record is split into 255 byte chunks on the wire and is
        meaningless unless they are concatenated."""
        out = self._query([(dnscheck.TYPE_TXT, txt_rdata("v=spf1 include:a.com ", "include:b.com ~all"))])
        self.assertEqual(out, ["v=spf1 include:a.com include:b.com ~all"])

    def test_multiple_txt_records(self):
        out = self._query([
            (dnscheck.TYPE_TXT, txt_rdata("first")),
            (dnscheck.TYPE_TXT, txt_rdata("second")),
        ])
        self.assertEqual(out, ["first", "second"])

    def test_mx_preference_and_host(self):
        rdata = struct.pack("!H", 10) + encode_name("mail.example.com")
        out = self._query([(dnscheck.TYPE_MX, rdata)], qtype=dnscheck.TYPE_MX)
        self.assertEqual(out, ["10 mail.example.com"])

    def test_a_record(self):
        out = self._query([(dnscheck.TYPE_A, bytes([93, 184, 216, 34]))], qtype=dnscheck.TYPE_A)
        self.assertEqual(out, ["93.184.216.34"])

    def test_nxdomain_is_empty_not_an_error(self):
        self.assertEqual(self._query([], rcode=3), [])

    def test_a_mismatched_response_id_is_rejected(self):
        def respond(_request_id, _packet):
            return build_response(0xBEEF, "example.com", dnscheck.TYPE_TXT,
                                  [(dnscheck.TYPE_TXT, txt_rdata("x"))])

        with mock.patch("socket.socket", FakeSocket(respond)):
            with self.assertRaises(dnscheck.DnsError):
                dnscheck.query("example.com")

    def test_no_answer_is_a_clear_error(self):
        class Dead(FakeSocket):
            def recvfrom(self, _size):
                raise OSError("timed out")

        with mock.patch("socket.socket", Dead(lambda *_a: b"")):
            with self.assertRaises(dnscheck.DnsError):
                dnscheck.query("example.com")


class TestRecordChecks(unittest.TestCase):
    def _check(self, table, selectors=("google",)):
        def fake_query(name, rtype=dnscheck.TYPE_TXT, timeout=3.0):
            return table.get((name, rtype), [])

        with mock.patch.object(dnscheck, "query", fake_query):
            return dnscheck.check_domain("example.com", selectors)

    def _finding(self, report, check):
        return next(f for f in report.findings if f.check == check)

    def test_a_healthy_domain_passes(self):
        report = self._check({
            ("example.com", dnscheck.TYPE_TXT): ["v=spf1 include:_spf.google.com ~all"],
            ("google._domainkey.example.com", dnscheck.TYPE_TXT): ["v=DKIM1; k=rsa; p=MIGf"],
            ("_dmarc.example.com", dnscheck.TYPE_TXT): ["v=DMARC1; p=none; rua=mailto:d@example.com"],
            ("example.com", dnscheck.TYPE_MX): ["1 aspmx.l.google.com"],
        })
        self.assertTrue(report.ok, str(report))

    def test_two_spf_records_is_invalid(self):
        report = self._check({("example.com", dnscheck.TYPE_TXT): ["v=spf1 ~all", "v=spf1 -all"]})
        finding = self._finding(report, "SPF")
        self.assertFalse(finding.ok)
        self.assertIn("2 SPF records", finding.detail)

    def test_permissive_spf_is_rejected(self):
        for record in ("v=spf1 +all", "v=spf1 ?all"):
            report = self._check({("example.com", dnscheck.TYPE_TXT): [record]})
            self.assertFalse(self._finding(report, "SPF").ok, record)

    def test_spf_over_ten_lookups(self):
        record = "v=spf1 " + " ".join(f"include:s{i}.com" for i in range(11)) + " ~all"
        report = self._check({("example.com", dnscheck.TYPE_TXT): [record]})
        self.assertIn("over the limit", self._finding(report, "SPF").detail)

    def test_dmarc_without_a_reporting_address_fails(self):
        report = self._check({("_dmarc.example.com", dnscheck.TYPE_TXT): ["v=DMARC1; p=none"]})
        finding = self._finding(report, "DMARC")
        self.assertFalse(finding.ok)
        self.assertIn("no reporting address", finding.detail)

    def test_dkim_tries_every_selector(self):
        report = self._check(
            {("selector2._domainkey.example.com", dnscheck.TYPE_TXT): ["v=DKIM1; p=abc"]},
            selectors=("google", "selector1", "selector2"),
        )
        finding = self._finding(report, "DKIM")
        self.assertTrue(finding.ok)
        self.assertIn("selector2", finding.detail)

    def test_missing_mx_fails(self):
        report = self._check({})
        self.assertFalse(self._finding(report, "MX").ok)


if __name__ == "__main__":
    unittest.main()
