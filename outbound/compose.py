"""Render the sequence emails.

Templates live in `templates/<role.template_dir>/step-N.md`. The format is a
`Subject:` line, a blank line, then the body. Tokens are `{{double_braced}}`.

Two rules are enforced rather than suggested:

1. Step 1 must contain `{{personal_note}}` and the note must be filled in.
   No detail, no email. The personalisation is the product.
2. The rendered copy is linted for the house writing rules before it is
   queued. Em dashes and AI tells fail the render, they do not warn.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import PLACEHOLDER, REPO_ROOT, Role, Settings
from .errors import ConfigError, OutboundError
from .util import now, token_for

TEMPLATES_DIR = REPO_ROOT / "templates"
TOKEN_RE = re.compile(r"\{\{\s*([a-z0-9_]+)\s*\}\}", re.I)

# Tells from topics/no-ai-smell.md. A rendered email that trips these reads as
# machine written, and the whole point of a founder send is that it does not.
BANNED_PHRASES = [
    "i hope this email finds you well",
    "i hope this finds you well",
    "reaching out",
    "circle back",
    "touch base",
    "at your earliest convenience",
    "i wanted to reach out",
    "delve",
    "leverage your",
    "game changer",
    "in today's fast",
    "fast-paced world",
    "it's not just",
    "not just a",
    "not just the",
    "this isn't about",
    "is not about",
    "isn't about",
    "that said",
    "excited to share",
    "thrilled to",
    "passionate about",
    "world-class",
    "cutting-edge",
    "best-in-class",
    "unlock your",
    "take your career to the next level",
    "rockstar",
    "ninja",
    "wear many hats",
    "hit the ground running",
    "synergy",
    "robust",
    "seamless",
    "holistic",
    "tapestry",
    "underscore",
    "navigate the",
    "dive deep",
    "deep dive",
    "key takeaways",
    "at its core",
]

MAX_WORDS = 170
MAX_LINKS = 3  # the JD link, the booking link, and the unsubscribe link


@dataclass
class Rendered:
    step: int
    subject: str
    body: str
    to_address: str
    warnings: list[str]


def _read_template(path: Path) -> tuple[str, str]:
    if not path.exists():
        raise ConfigError(f"missing template: {path}")
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    lines = text.split("\n")
    subject = ""
    start = 0
    for index, line in enumerate(lines[:5]):
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            start = index + 1
            break
    else:
        raise ConfigError(f"{path}: the first lines must contain a `Subject:` line")
    body_lines = lines[start:]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    if body_lines and body_lines[0].strip() == "---":
        body_lines.pop(0)
    return subject, "\n".join(body_lines).strip()


def template_path(role: Role, step: int) -> Path:
    return TEMPLATES_DIR / role.template_dir / f"step-{step}.md"


def steps_available(role: Role) -> list[int]:
    directory = TEMPLATES_DIR / role.template_dir
    if not directory.exists():
        return []
    steps = []
    for path in directory.glob("step-*.md"):
        match = re.fullmatch(r"step-(\d+)", path.stem)
        if match:
            steps.append(int(match.group(1)))
    return sorted(steps)


def build_context(
    settings: Settings, role: Role, candidate: dict[str, Any], to_address: str
) -> dict[str, str]:
    import datetime as _dt

    # A real date beats "shortly". The last email in a sequence only works if
    # the deadline is checkable.
    closes_in = int(settings.get("sending.search_closes_days", 10))
    closing = now() + _dt.timedelta(days=closes_in)
    closing_date = f"{closing.day} {closing.strftime('%B')}"

    unsub = str(settings.get("identity.unsubscribe_url", ""))
    token = token_for(to_address, salt=str(settings.get("identity.sending_domain", "")))
    unsub = unsub.replace("{email_token}", token).replace("{{email_token}}", token)
    return {
        "first_name": str(candidate.get("first_name") or "there").strip(),
        "last_name": str(candidate.get("last_name") or "").strip(),
        "full_name": str(candidate.get("full_name") or "").strip(),
        "title": str(candidate.get("title") or "").strip(),
        "company": str(candidate.get("company") or "").strip(),
        "location": str(candidate.get("location") or "").strip(),
        "personal_note": str(candidate.get("personal_note") or "").strip(),
        "role_title": role.title,
        "role_one_liner": role.one_liner,
        "comp": role.comp_for(candidate.get("source_search")),
        "employment": role.employment,
        "jd_url": role.jd_url,
        "screener_url": str(settings.get("booking.screener_url", "")),
        "screener_minutes": str(settings.get("booking.screener_minutes", 10)),
        "sender_name": str(settings.get("identity.from_name", "")),
        "sender_email": str(settings.get("identity.from_email", "")),
        "careers_page": str(settings.get("identity.careers_page", "")),
        "postal_address": str(settings.get("identity.postal_address", "")),
        "unsubscribe_url": unsub,
        "to_address": to_address,
        "closing_date": closing_date,
    }


def render_text(text: str, context: dict[str, str], where: str) -> str:
    unknown = sorted(
        {m.group(1) for m in TOKEN_RE.finditer(text)} - set(context)
    )
    if unknown:
        raise ConfigError(
            f"{where}: unknown token(s) {', '.join('{{' + u + '}}' for u in unknown)}. "
            f"Known tokens: {', '.join(sorted(context))}"
        )
    return TOKEN_RE.sub(lambda m: context[m.group(1).lower()], text)


def lint(subject: str, body: str, strict: bool = True) -> list[str]:
    """House writing rules. Returns the problems found."""
    problems: list[str] = []
    joined = f"{subject}\n{body}"
    low = joined.lower()

    if "—" in joined or "–" in joined:
        problems.append("em or en dash present. Use a comma, a colon or a full stop.")
    for phrase in BANNED_PHRASES:
        if phrase in low:
            problems.append(f"banned phrase: {phrase!r}")
    words = len(re.findall(r"\S+", body))
    if words > MAX_WORDS:
        problems.append(f"body is {words} words. Keep it under {MAX_WORDS}.")
    links = re.findall(r"https?://\S+", body)
    if len(links) > MAX_LINKS:
        problems.append(f"{len(links)} links in the body. Keep it to {MAX_LINKS}.")
    if PLACEHOLDER.search(joined):
        problems.append("CHANGEME or NEEDS_PETER left in the copy")
    # Unfinished copy. This nearly went out: six roles carried DRAFT
    # placeholder templates, and flipping them to live removed the only thing
    # that was stopping them from sending.
    for marker in ("DRAFT", "TODO", "TBD", "FIXME", "XXX", "lorem ipsum",
                   "PLACEHOLDER", "WRITE THIS", "[insert"):
        if marker.lower() in low:
            problems.append(f"unfinished copy marker in the text: {marker!r}")
    if TOKEN_RE.search(joined):
        problems.append("an unrendered {{token}} is still in the copy")
    if not subject.strip():
        problems.append("empty subject")
    if subject.strip().endswith("!"):
        problems.append("exclamation mark in the subject")
    if strict and re.search(r"\b(?:we are|we're) (?:excited|thrilled|delighted)\b", low):
        problems.append("promotional opener")
    return problems


def render(
    settings: Settings,
    role: Role,
    candidate: dict[str, Any],
    to_address: str,
    step: int,
    strict: bool = True,
) -> Rendered:
    path = template_path(role, step)
    subject_raw, body_raw = _read_template(path)

    if step == 1 and "{{personal_note}}" not in body_raw.replace(" ", ""):
        if "personal_note" not in body_raw:
            raise ConfigError(
                f"{path}: step 1 must include {{{{personal_note}}}}. "
                f"No detail, no email."
            )
    if step == 1 and not str(candidate.get("personal_note") or "").strip():
        raise OutboundError(
            f"candidate {candidate.get('id')} ({candidate.get('full_name')}) has no "
            f"personal_note. Add one in `outbound review` before composing. "
            f"The specific detail is mandatory."
        )

    context = build_context(settings, role, candidate, to_address)
    subject = render_text(subject_raw, context, f"{path} subject")
    body = render_text(body_raw, context, f"{path} body")

    problems = lint(subject, body, strict=strict)
    if problems and strict:
        joined = "\n".join(f"  - {p}" for p in problems)
        raise OutboundError(f"copy check failed for {path}:\n{joined}")
    return Rendered(step=step, subject=subject, body=body, to_address=to_address, warnings=problems)
