"""Small helpers with no dependencies of their own."""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
import unicodedata


UTC = _dt.timezone.utc


def now() -> _dt.datetime:
    """Current time, timezone aware, UTC. Never use naive datetimes."""
    return _dt.datetime.now(tz=UTC)


def iso(ts: _dt.datetime | None = None) -> str:
    """ISO 8601 in UTC, seconds precision. The only timestamp format we store."""
    return (ts or now()).astimezone(UTC).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> _dt.datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def slug(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "item"


_EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[A-Za-z]{2,}$")


def is_email(value: str | None) -> bool:
    return bool(value) and bool(_EMAIL_RE.match(value.strip()))


def norm_email(value: str | None) -> str:
    return (value or "").strip().lower()


def email_domain(value: str | None) -> str:
    address = norm_email(value)
    return address.split("@", 1)[1] if "@" in address else ""


def norm_linkedin(url: str | None) -> str:
    """Canonical LinkedIn profile URL. Used as the dedupe key.

    Strips the scheme, the country subdomain, query strings, trailing slashes
    and any trailing locale segment. `https://uk.linkedin.com/in/Jane-Doe-1a2/`
    and `linkedin.com/in/jane-doe-1a2` become the same string.
    """
    if not url:
        return ""
    text = url.strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^([a-z]{2,3}\.)?linkedin\.com", "linkedin.com", text)
    text = text.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    match = re.search(r"linkedin\.com/(in|pub)/([^/]+)", text)
    if match:
        return "linkedin.com/in/" + match.group(2)
    return text


def name_parts(full_name: str | None) -> tuple[str, str]:
    """Best effort first and last name. Good enough for a merge field."""
    cleaned = re.sub(r"\s+", " ", (full_name or "").strip())
    cleaned = re.sub(
        r",?\s+(PhD|MBA|CPA|CFA|MSc|BSc|PMP|MD|JD|Jr\.?|Sr\.?|II|III|IV)\b",
        "",
        cleaned,
        flags=re.I,
    )
    parts = [p for p in cleaned.split(" ") if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


def token_for(value: str, salt: str = "") -> str:
    """Stable opaque token. Used for the unsubscribe link."""
    digest = hashlib.sha256((salt + "|" + (value or "")).encode("utf-8")).hexdigest()
    return digest[:32]


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def plural(count: int, one: str, many: str | None = None) -> str:
    return f"{count} {one}" if count == 1 else f"{count} {many or one + 's'}"
