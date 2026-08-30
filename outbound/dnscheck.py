"""DNS checks for the sending domain. Standard library only.

Bad or missing SPF, DKIM and DMARC records are the most common reason cold
email lands in spam, and they are silent: nothing tells you, the replies just
never come. This resolves the records directly over UDP so `outbound doctor`
can say what is wrong before the first send rather than after three weeks of
nothing.

A minimal resolver, deliberately. It sends one query, reads one answer, and
handles TXT, MX, A and CNAME. It does not do DNSSEC, EDNS or retries beyond a
second nameserver. That is enough to answer "is the record there and does it
say the right thing".
"""

from __future__ import annotations

import random
import re
import socket
import struct
from dataclasses import dataclass, field
from typing import Iterable

# Selectors used by the common senders. DKIM lives at
# <selector>._domainkey.<domain> and the selector is chosen by whoever signs,
# so there is no way to find it except to try the usual ones.
COMMON_DKIM_SELECTORS = [
    "google",           # Google Workspace
    "selector1", "selector2",  # Microsoft 365
    "k1", "k2",         # Mailchimp, Postmark
    "s1", "s2",         # generic
    "mail", "dkim", "default",
    "smtp",             # some hosts
    "zoho", "zohomail",
    "fm1", "fm2", "fm3",  # Fastmail
    "mandrill", "sendgrid", "amazonses",
    "protonmail", "protonmail2",
]

TYPE_A = 1
TYPE_CNAME = 5
TYPE_MX = 15
TYPE_TXT = 16
TYPE_NAMES = {TYPE_A: "A", TYPE_CNAME: "CNAME", TYPE_MX: "MX", TYPE_TXT: "TXT"}


class DnsError(Exception):
    """The query could not be answered. Not the same as "no such record"."""


def _nameservers() -> list[str]:
    servers: list[str] = []
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("nameserver"):
                    parts = line.split()
                    if len(parts) > 1:
                        servers.append(parts[1])
    except OSError:
        pass
    for fallback in ("8.8.8.8", "1.1.1.1"):
        if fallback not in servers:
            servers.append(fallback)
    return servers[:4]


def _encode_name(name: str) -> bytes:
    out = b""
    for label in name.strip(".").split("."):
        encoded = label.encode("idna") if any(ord(c) > 127 for c in label) else label.encode("ascii")
        if len(encoded) > 63:
            raise DnsError(f"label too long in {name!r}")
        out += bytes([len(encoded)]) + encoded
    return out + b"\x00"


def _read_name(data: bytes, offset: int) -> tuple[str, int]:
    """Read a possibly compressed name. Returns (name, offset after it)."""
    labels: list[str] = []
    jumped = False
    end = offset
    hops = 0
    while True:
        if offset >= len(data):
            raise DnsError("truncated name")
        length = data[offset]
        if length & 0xC0 == 0xC0:
            if offset + 1 >= len(data):
                raise DnsError("truncated pointer")
            pointer = struct.unpack("!H", data[offset : offset + 2])[0] & 0x3FFF
            if not jumped:
                end = offset + 2
            offset = pointer
            jumped = True
            hops += 1
            if hops > 20:
                raise DnsError("compression loop")
            continue
        offset += 1
        if length == 0:
            if not jumped:
                end = offset
            break
        labels.append(data[offset : offset + length].decode("latin-1"))
        offset += length
    return ".".join(labels), end


def query(name: str, rtype: int = TYPE_TXT, timeout: float = 3.0) -> list[str]:
    """One DNS query. Returns the record values as strings.

    TXT records come back with their chunks joined, which is what SPF and
    DMARC need: a long SPF record is split into 255 byte chunks on the wire
    and is meaningless unless they are concatenated.
    """
    request_id = random.SystemRandom().randint(0, 0xFFFF)
    header = struct.pack("!HHHHHH", request_id, 0x0100, 1, 0, 0, 0)
    packet = header + _encode_name(name) + struct.pack("!HH", rtype, 1)

    last_error: Exception | None = None
    for server in _nameservers():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            try:
                sock.sendto(packet, (server, 53))
                data, _ = sock.recvfrom(4096)
            finally:
                sock.close()
        except OSError as exc:
            last_error = exc
            continue

        if len(data) < 12:
            last_error = DnsError("short response")
            continue
        resp_id, flags, _qd, ancount, _ns, _ar = struct.unpack("!HHHHHH", data[:12])
        if resp_id != request_id:
            last_error = DnsError("response id mismatch")
            continue
        rcode = flags & 0x000F
        if rcode == 3:      # NXDOMAIN
            return []
        if rcode != 0:
            last_error = DnsError(f"server returned rcode {rcode}")
            continue

        offset = 12
        _qname, offset = _read_name(data, offset)
        offset += 4  # qtype and qclass

        out: list[str] = []
        for _ in range(ancount):
            _rname, offset = _read_name(data, offset)
            if offset + 10 > len(data):
                break
            atype, _aclass, _ttl, rdlength = struct.unpack("!HHIH", data[offset : offset + 10])
            offset += 10
            rdata = data[offset : offset + rdlength]
            end = offset + rdlength
            if atype == TYPE_TXT:
                chunks, position = [], 0
                while position < len(rdata):
                    size = rdata[position]
                    chunks.append(rdata[position + 1 : position + 1 + size].decode("utf-8", "replace"))
                    position += 1 + size
                out.append("".join(chunks))
            elif atype == TYPE_MX and rdlength >= 3:
                preference = struct.unpack("!H", rdata[:2])[0]
                host, _ = _read_name(data, offset + 2)
                out.append(f"{preference} {host}")
            elif atype == TYPE_A and rdlength == 4:
                out.append(".".join(str(b) for b in rdata))
            elif atype == TYPE_CNAME:
                host, _ = _read_name(data, offset)
                out.append(host)
            offset = end
        return out

    raise DnsError(f"no nameserver answered for {name}: {last_error}")


@dataclass
class Finding:
    check: str
    ok: bool
    detail: str
    fix: str = ""

    def __str__(self) -> str:
        mark = "PASS" if self.ok else "FAIL"
        line = f"{mark}  {self.check}: {self.detail}"
        if not self.ok and self.fix:
            line += f"\n      fix: {self.fix}"
        return line


@dataclass
class DomainReport:
    domain: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(f.ok for f in self.findings)

    def __str__(self) -> str:
        head = f"DNS for {self.domain}"
        return head + "\n" + "\n".join(f"  {f}" for f in self.findings)


def _spf(domain: str) -> Finding:
    try:
        records = [r for r in query(domain, TYPE_TXT) if r.lower().startswith("v=spf1")]
    except DnsError as exc:
        return Finding("SPF", False, f"lookup failed: {exc}")
    if not records:
        return Finding(
            "SPF", False, "no v=spf1 record",
            "add a TXT record at the root: v=spf1 include:<your mail provider> ~all",
        )
    if len(records) > 1:
        return Finding(
            "SPF", False, f"{len(records)} SPF records, which is invalid",
            "merge them into one. More than one SPF record makes every check fail.",
        )
    record = records[0]
    if re.search(r"[?+]all\s*$", record):
        return Finding(
            "SPF", False, f"ends with a permissive qualifier: {record}",
            "end the record with ~all or -all. +all and ?all authorise anyone.",
        )
    if not re.search(r"[-~]all\s*$", record):
        return Finding(
            "SPF", False, f"does not end in ~all or -all: {record}",
            "append ~all",
        )
    lookups = len(re.findall(r"\b(include|a|mx|ptr|exists|redirect)[:=]", record))
    if lookups > 10:
        return Finding(
            "SPF", False, f"{lookups} DNS lookups, over the limit of 10",
            "flatten some includes. Over ten lookups is a permanent error.",
        )
    return Finding("SPF", True, record)


def _dmarc(domain: str) -> Finding:
    try:
        records = [
            r for r in query(f"_dmarc.{domain}", TYPE_TXT)
            if r.lower().startswith("v=dmarc1")
        ]
    except DnsError as exc:
        return Finding("DMARC", False, f"lookup failed: {exc}")
    if not records:
        return Finding(
            "DMARC", False, "no record at _dmarc",
            "add a TXT record at _dmarc: v=DMARC1; p=none; rua=mailto:dmarc@"
            + domain + "  then read the reports for two weeks before tightening.",
        )
    record = records[0]
    policy = re.search(r"\bp=(\w+)", record)
    if not policy:
        return Finding("DMARC", False, f"no policy in the record: {record}", "add p=none to start")
    if "rua=" not in record:
        return Finding(
            "DMARC", False, f"policy {policy.group(1)} but no reporting address",
            f"add rua=mailto:dmarc@{domain}. Without it you are blind.",
        )
    return Finding("DMARC", True, record)


def _dkim(domain: str, selectors: Iterable[str]) -> Finding:
    found: list[str] = []
    errors = 0
    for selector in selectors:
        try:
            records = query(f"{selector}._domainkey.{domain}", TYPE_TXT)
        except DnsError:
            errors += 1
            continue
        for record in records:
            if "p=" in record and ("v=DKIM1" in record or "k=rsa" in record):
                found.append(selector)
                break
    if found:
        return Finding("DKIM", True, "signing key found at selector(s): " + ", ".join(found))
    if errors:
        return Finding("DKIM", False, f"could not resolve any selector ({errors} lookup errors)")
    return Finding(
        "DKIM", False,
        "no key at any common selector",
        "your mail provider gives you the selector and the key. Publish it, "
        "then re-run. An unsigned domain is treated as suspicious by every "
        "large mailbox provider.",
    )


def _mx(domain: str) -> Finding:
    try:
        records = query(domain, TYPE_MX)
    except DnsError as exc:
        return Finding("MX", False, f"lookup failed: {exc}")
    if not records:
        return Finding(
            "MX", False, "no MX record",
            "without MX you cannot receive replies, which makes the whole "
            "exercise pointless.",
        )
    return Finding("MX", True, "; ".join(sorted(records)))


def check_domain(domain: str, selectors: Iterable[str] | None = None) -> DomainReport:
    domain = domain.strip().lower().rstrip(".")
    report = DomainReport(domain=domain)
    report.findings.append(_spf(domain))
    report.findings.append(_dkim(domain, selectors or COMMON_DKIM_SELECTORS))
    report.findings.append(_dmarc(domain))
    report.findings.append(_mx(domain))
    return report
