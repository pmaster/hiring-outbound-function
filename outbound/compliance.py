"""The rules that stop a send.

Two kinds of rule live here. Legal ones (CAN-SPAM, CASL, GDPR) and house ones
(domain warm up, no sending from the live brands). Both raise rather than warn,
because a warning in a nightly run is a warning nobody reads.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .config import PLACEHOLDER, Role, Settings
from .errors import ComplianceError
from .util import email_domain, norm_email

# Never send from these. A complaint cluster on a live brand domain
# blocklists it and kills normal business email.
FORBIDDEN_SENDING_DOMAINS = {
    "viewlineventures.com",
    "sunbirdsystems.com",
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
}


@dataclass
class Problem:
    code: str
    message: str
    fatal: bool = True

    def __str__(self) -> str:
        mark = "BLOCK" if self.fatal else "WARN "
        return f"{mark} {self.code}: {self.message}"


def country_sets(settings: Settings) -> tuple[set[str], set[str]]:
    allow = {str(c).upper() for c in settings.get("compliance.allow_countries", []) or []}
    block = {str(c).upper() for c in settings.get("compliance.block_countries", []) or []}
    return allow, block


def geo_allowed(settings: Settings, country: str | None) -> tuple[bool, str]:
    """Country gate. Unknown is refused, on purpose."""
    if not settings.get("compliance.enforce_geo_block", True):
        return True, ""
    allow, block = country_sets(settings)
    code = str(country or "").upper()
    if not code:
        return False, "country unknown, and unknown is not sendable"
    if code in block:
        return False, f"{code} is on the block list"
    if allow and code not in allow:
        return False, f"{code} is not on the allow list"
    return True, ""


def message_problems(settings: Settings, body: str) -> list[Problem]:
    """Every commercial email needs an unsubscribe route and a postal address."""
    problems: list[Problem] = []
    if settings.get("compliance.require_unsubscribe", True):
        if "unsubscribe" not in body.lower():
            problems.append(
                Problem("no_unsubscribe", "CAN-SPAM: the body has no unsubscribe route")
            )
    if settings.get("compliance.require_postal", True):
        postal = str(settings.get("identity.postal_address", ""))
        if not postal or postal not in body:
            problems.append(
                Problem("no_postal", "CAN-SPAM: the body has no physical postal address")
            )
    return problems


def preflight(settings: Settings, role: Role | None = None) -> list[Problem]:
    """Everything that must be true before a real send. Run by `outbound doctor`."""
    problems: list[Problem] = []

    for entry in settings.placeholders():
        problems.append(Problem("placeholder", f"settings still has {entry}"))

    from_email = norm_email(str(settings.get("identity.from_email", "")))
    domain = email_domain(from_email) or str(settings.get("identity.sending_domain", "")).lower()
    if not from_email:
        problems.append(Problem("no_sender", "identity.from_email is empty"))
    if domain in FORBIDDEN_SENDING_DOMAINS:
        problems.append(
            Problem(
                "forbidden_domain",
                f"{domain} must never send outbound. Use a separate recruiting "
                f"domain on separate hosting. See docs/OPSEC.md.",
            )
        )
    if domain and not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", domain):
        problems.append(Problem("bad_domain", f"sending domain {domain!r} looks wrong"))

    if settings.get("warmup.require_warmup_done", True):
        problems.append(
            Problem(
                "warmup_attested",
                "warmup.require_warmup_done is on. Confirm both mailboxes finished "
                "warm up and SPF, DKIM and DMARC pass, then run with --attest-warmup.",
                fatal=False,
            )
        )

    screener = str(settings.get("booking.screener_url", ""))
    if not screener or PLACEHOLDER.search(screener):
        problems.append(Problem("no_screener", "booking.screener_url is not set"))

    allow, _ = country_sets(settings)
    if not allow:
        problems.append(
            Problem("no_allow_list", "compliance.allow_countries is empty, so nothing can send")
        )

    if role is not None:
        if not role.is_live:
            problems.append(
                Problem("role_not_live", f"role {role.key} has status {role.status!r}")
            )
        for entry in role.placeholders():
            problems.append(Problem("placeholder", f"role {role.key} still has {entry}"))
        if role.comp_in_email and PLACEHOLDER.search(role.comp):
            problems.append(
                Problem(
                    "no_comp",
                    f"role {role.key} puts comp in the email but comp is unset. "
                    f"A senior operator will not answer a blind approach.",
                )
            )
    return problems


def assert_sendable(settings: Settings, role: Role, attest_warmup: bool = False) -> None:
    problems = [p for p in preflight(settings, role) if p.fatal]
    if attest_warmup:
        problems = [p for p in problems if p.code != "warmup_attested"]
    if problems:
        lines = "\n".join(f"  {p}" for p in problems)
        raise ComplianceError(
            f"refusing to send for role {role.key}. Fix these first:\n{lines}"
        )
