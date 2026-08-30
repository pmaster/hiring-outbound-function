"""Detect replies and bounces, so a follow up never goes to someone who
already answered.

This closes the worst failure in the flow. Sending "I am closing this search"
to a person who replied four days ago is the one mistake that turns a good
approach into a bad story.

Two routes:

- **IMAP.** Reads the sending mailbox directly. This is the route for the
  founder sent seats, which go out over plain SMTP. Standard library only.
- **By hand.** `outbound replies mark <address>` for anything the scan misses,
  including a reply that arrives on another channel.

A sequencer (Instantly, Smartlead) does its own reply detection and stops its
own sequences. If you send through one, run `replies sync` anyway: this
database is what decides the stage, and the report reads from it.
"""

from __future__ import annotations

import email
import email.utils
import imaplib
import re
from dataclasses import dataclass
from typing import Any, Iterable

from .config import secret
from .db import Database
from .errors import ProviderError
from .pipeline import StepResult
from .util import iso, norm_email, now, parse_iso

# A bounce comes from one of these, not from the candidate.
DAEMON_PATTERNS = (
    "mailer-daemon", "postmaster", "no-reply", "noreply", "bounce",
    "mail-delivery", "mailerdaemon",
)
# Text that marks a hard bounce rather than a temporary one.
HARD_BOUNCE = re.compile(
    r"(user unknown|no such user|does not exist|address rejected|"
    r"recipient not found|mailbox unavailable|invalid recipient|550[ -]5\.1\.1)",
    re.I,
)
UNSUBSCRIBE_INTENT = re.compile(
    r"\b(unsubscribe|remove me|take me off|stop (?:emailing|contacting)|do not (?:contact|email))\b",
    re.I,
)
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


@dataclass
class Inbound:
    from_address: str
    subject: str
    body: str
    date: str


def _decode(part: Any) -> str:
    try:
        payload = part.get_payload(decode=True)
    except Exception:
        return ""
    if not payload:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, "replace")
    except LookupError:
        return payload.decode("utf-8", "replace")


def _body_text(message: email.message.Message) -> str:
    if message.is_multipart():
        chunks = [
            _decode(part)
            for part in message.walk()
            if part.get_content_type() in ("text/plain", "message/delivery-status")
        ]
        return "\n".join(c for c in chunks if c)
    return _decode(message)


def fetch_imap(since: str | None = None, folders: Iterable[str] = ("INBOX",)) -> list[Inbound]:
    """Read messages from the sending mailbox. Standard library imaplib."""
    host = secret("IMAP_HOST", required=True)
    port = int(secret("IMAP_PORT") or 993)
    user = secret("IMAP_USER", required=True)
    password = secret("IMAP_PASSWORD", required=True)

    when = parse_iso(since) or now()
    criterion = when.strftime("%d-%b-%Y")
    out: list[Inbound] = []
    try:
        connection = imaplib.IMAP4_SSL(host, port)
        connection.login(user, password)
        for folder in folders:
            status, _ = connection.select(folder, readonly=True)
            if status != "OK":
                continue
            status, data = connection.search(None, "SINCE", criterion)
            if status != "OK" or not data or not data[0]:
                continue
            for uid in data[0].split():
                status, chunk = connection.fetch(uid, "(RFC822)")
                if status != "OK" or not chunk or not isinstance(chunk[0], tuple):
                    continue
                message = email.message_from_bytes(chunk[0][1])
                _name, address = email.utils.parseaddr(message.get("From", ""))
                out.append(
                    Inbound(
                        from_address=norm_email(address),
                        subject=str(message.get("Subject") or ""),
                        body=_body_text(message)[:20000],
                        date=str(message.get("Date") or ""),
                    )
                )
        connection.logout()
    except imaplib.IMAP4.error as exc:
        raise ProviderError(f"IMAP failed: {exc}") from exc
    return out


def classify(item: Inbound, written_to: set[str]) -> tuple[str, str]:
    """Return (kind, address). kind is replied, bounced, unsubscribed or ignore."""
    sender = item.from_address
    is_daemon = any(p in sender for p in DAEMON_PATTERNS)

    if is_daemon:
        haystack = f"{item.subject}\n{item.body}"
        for candidate in {a.lower() for a in ADDRESS.findall(haystack)} & written_to:
            if HARD_BOUNCE.search(haystack):
                return "bounced", candidate
            return "ignore", candidate
        return "ignore", ""

    if sender not in written_to:
        return "ignore", sender

    if UNSUBSCRIBE_INTENT.search(item.subject) or UNSUBSCRIBE_INTENT.search(item.body[:1200]):
        return "unsubscribed", sender
    return "replied", sender


def apply(db: Database, kind: str, address: str, note: str = "") -> bool:
    """Move every candidate on that address to the right stage."""
    address = norm_email(address)
    if not address or kind == "ignore":
        return False
    rows = db.query(
        "SELECT c.* FROM candidates c JOIN emails e ON e.candidate_id = c.id "
        "WHERE e.address = ?",
        (address,),
    )
    if not rows:
        return False
    changed = False
    for row in rows:
        if row["stage"] in ("hired", "screened", "booked", "confirmed"):
            continue  # further along than a reply. Do not walk it backwards.
        db.set_stage(int(row["id"]), kind, note or f"inbound: {kind}")
        changed = True
    if kind in ("bounced", "unsubscribed"):
        db.suppress("email", address, note or f"inbound: {kind}")
    # Anything still queued for this person must not go out.
    db.execute(
        "UPDATE messages SET status = 'skipped' WHERE to_address = ? AND status = 'queued'",
        (address,),
    )
    return changed


def written_addresses(db: Database) -> set[str]:
    return {
        row["to_address"]
        for row in db.query("SELECT DISTINCT to_address FROM messages WHERE status = 'sent'")
        if row["to_address"]
    }


def fetch(settings: Any, since: str | None = None) -> list[Inbound]:
    """Inbound mail from whichever source is configured.

    `imap` reads the sending mailbox, which is right when the mailboxes are
    yours. A sequencer keeps replies in its own inbox, so when one is sending,
    point this at the sequencer instead.
    """
    from . import providers as provider_registry

    name = str(settings.get("providers.replies", "imap")) if hasattr(settings, "get") else "imap"
    provider = provider_registry.build("replies", name, settings)
    if provider is None:
        return []
    return [
        Inbound(
            from_address=norm_email(row.get("from_address") or ""),
            subject=str(row.get("subject") or ""),
            body=str(row.get("body") or ""),
            date=str(row.get("date") or ""),
        )
        for row in provider.fetch_replies(since=since) or []
    ]


def sync(db: Database, settings: Any, since: str | None = None) -> StepResult:
    result = StepResult(step="replies:sync")
    written = written_addresses(db)
    if not written:
        result.notes.append("nothing has been sent yet, so there is nothing to match.")
        return result
    if since is None:
        earliest = db.scalar("SELECT MIN(sent_at) FROM messages WHERE status = 'sent'")
        since = str(earliest) if earliest else iso()
    for item in fetch(settings, since=since):
        kind, address = classify(item, written)
        if kind == "ignore":
            result.bump("ignored")
            continue
        matched = db.one(
            "SELECT c.id, c.role_key FROM candidates c JOIN emails e ON e.candidate_id = c.id "
            "WHERE e.address = ? ORDER BY c.id DESC LIMIT 1",
            (address,),
        )
        # Keep the message. Knowing that someone replied is not the same as
        # knowing what they said, and the text is what you act on.
        _row_id, stored = db.store_inbound(
            from_address=item.from_address,
            subject=item.subject,
            body=item.body,
            kind=kind,
            received_at=item.date,
            candidate_id=int(matched["id"]) if matched else None,
            role_key=(matched or {}).get("role_key"),
        )
        if not stored:
            result.bump("already_seen")
            continue
        if apply(db, kind, address, note=f"from {item.from_address}: {item.subject[:120]}"):
            result.bump(kind)
        else:
            result.bump("no_match")
    return result
