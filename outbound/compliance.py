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

# Hard block. Both source doctrines agree these must never send FTE outreach.
#
# cornerstonegigs.com is reserved exclusively for client and gig worker
# engagement, and the Cornerstone name carries public reviews bad enough to
# fail a bank compliance check. sunrunlabs.com is the internal corporate
# identity holding the shared Workspace login. Free mail providers cannot
# carry SPF, DKIM and DMARC for a brand, and read as a scam from a stranger.
FORBIDDEN_SENDING_DOMAINS = {
    "cornerstonegigs.com",
    "sunrunlabs.com",
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "hotmail.com",
    "yahoo.com",
    "icloud.com",
    "proton.me",
    "protonmail.com",
}

# Not blocked, but not free either. Peter's own scoping doc designates
# viewlineventures.com as the FTE hiring domain, and it already sends job
# notifications. The outbound SOP argues the opposite: a complaint cluster
# blocklists the domain and takes normal business email with it. Both
# arguments are real, so this is a decision, not a rule. See docs/DECISIONS.md
# Q4, and docs/SOURCE-BRIEF.md section 3.1.
CONTESTED_SENDING_DOMAINS = {
    "viewlineventures.com": (
        "the designated FTE hiring domain, and it already sends job "
        "notifications. It also carries normal business email, which a "
        "complaint cluster would take down with it. Lock this decision for "
        "12 months before warming anything."
    ),
    "sunbirdsystems.com": (
        "the careers site brand used at the Rutgers career fair and for "
        "Handshake. Burning it costs the campus channel, which produced real "
        "hires."
    ),
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
        url = str(settings.get("identity.unsubscribe_url", "")).strip()
        # Strip the token template so the base of the link can be matched in
        # the rendered body.
        base = url.split("{email_token}")[0].split("{{email_token}}")[0].split("?")[0].strip()
        if "unsubscribe" not in body.lower():
            problems.append(
                Problem("no_unsubscribe", "CAN-SPAM: the body has no unsubscribe route")
            )
        elif not url or PLACEHOLDER.search(url):
            problems.append(
                Problem(
                    "no_unsubscribe",
                    "CAN-SPAM: identity.unsubscribe_url is empty or a placeholder, "
                    "so the opt-out link does not work.",
                )
            )
        elif base and base not in body:
            problems.append(
                Problem(
                    "no_unsubscribe",
                    "CAN-SPAM: the configured unsubscribe URL does not appear in the "
                    "body. The template mentions unsubscribing but links nowhere.",
                )
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
                f"{domain} must never send FTE outreach. Use a recruiting "
                f"domain on separate hosting. See docs/OPSEC.md.",
            )
        )
    elif domain in CONTESTED_SENDING_DOMAINS:
        decided = str(settings.get("identity.sending_domain_decided_on", "")).strip()
        if not decided:
            problems.append(
                Problem(
                    "contested_domain",
                    f"{domain} is {CONTESTED_SENDING_DOMAINS[domain]} "
                    f"Sending from it is a decision someone has to make on "
                    f"purpose. Record it with identity.sending_domain_decided_on.",
                    fatal=False,
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
                fatal=True,
            )
        )

    screener = str(settings.get("booking.screener_url", ""))
    if not screener or PLACEHOLDER.search(screener):
        problems.append(Problem("no_screener", "booking.screener_url is not set"))

    allow, _ = country_sets(settings)
    if settings.get("compliance.enforce_geo_block", True) and not allow:
        problems.append(
            Problem("no_allow_list", "compliance.allow_countries is empty, so nothing can send")
        )

    if role is not None:
        problems.extend(_template_problems(settings, role))
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


def _template_problems(settings: Settings, role: Role) -> list[Problem]:
    """Catch a missing or broken template now, not at 08:40 on a cron."""
    from .compose import render, steps_available

    problems: list[Problem] = []
    steps = steps_available(role)
    if not steps:
        return [
            Problem(
                "no_templates",
                f"no templates in templates/{role.template_dir}/. Expected step-1.md.",
            )
        ]
    if 1 not in steps:
        problems.append(
            Problem("no_step_one", f"templates/{role.template_dir}/step-1.md is missing")
        )
    sample = {
        "id": 0,
        "first_name": "Sample",
        "last_name": "Person",
        "full_name": "Sample Person",
        "title": "Head of Operations",
        "company": "Example",
        "personal_note": "A specific detail from their profile.",
    }
    for step in steps:
        try:
            rendered = render(settings, role, sample, "sample@example.com", step, strict=True)
        except Exception as exc:
            problems.append(
                Problem("template_broken", f"{role.key} step {step} will not render: {exc}")
            )
            continue
        for problem in message_problems(settings, rendered.body):
            problems.append(
                Problem(problem.code, f"{role.key} step {step}: {problem.message}")
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
