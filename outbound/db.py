"""SQLite storage. One file, no server, no migrations tool.

The database is the state of the funnel. Every command reads and writes here,
so a run can stop at any point and resume without losing work.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Sequence

from .util import iso, norm_email, norm_linkedin, now

SCHEMA_VERSION = 4

# The funnel, in order. `stage_index` uses this, so keep it ordered.
STAGES = [
    "sourced",     # pulled from a search, not yet scored
    "scored",      # scored, awaiting routing
    "rejected",    # below the bar or disqualified. Terminal.
    "review",      # in the hand review queue
    "approved",    # cleared for enrichment
    "enriched",    # has at least one candidate email address
    "verified",    # address passed verification
    "queued",      # message rendered, waiting to send
    "sent",        # at least one message sent
    "replied",     # replied to any message
    "booked",      # booked the screener
    "confirmed",   # booking survived the pre call re check
    "cancelled",   # booking cancelled by us. Terminal for this role.
    "screened",    # screener call happened
    "hired",       # terminal, good
    "bounced",     # terminal, bad address
    "unsubscribed",  # terminal, do not contact
    "stopped",     # terminal, stopped by hand
]
TERMINAL_STAGES = {"rejected", "cancelled", "hired", "bounced", "unsubscribed", "stopped"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidates (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    role_key                 TEXT NOT NULL,
    linkedin_key             TEXT NOT NULL,
    linkedin_url             TEXT,
    full_name                TEXT,
    first_name               TEXT,
    last_name                TEXT,
    headline                 TEXT,
    title                    TEXT,
    company                  TEXT,
    company_domain           TEXT,
    company_headcount        INTEGER,
    location                 TEXT,
    country                  TEXT,
    years_experience         REAL,
    months_in_current_role   REAL,
    jobs_last_3_years        INTEGER,
    longest_tenure_years     REAL,
    profile_text             TEXT,
    profile_json             TEXT,
    source                   TEXT,
    source_search            TEXT,
    sourced_at               TEXT,
    score                    REAL,
    score_json               TEXT,
    stage                    TEXT NOT NULL DEFAULT 'sourced',
    review_state             TEXT NOT NULL DEFAULT 'pending',
    review_note              TEXT,
    personal_note            TEXT,
    updated_at               TEXT,
    UNIQUE (role_key, linkedin_key)
);
CREATE INDEX IF NOT EXISTS idx_candidates_stage ON candidates (role_key, stage);
CREATE INDEX IF NOT EXISTS idx_candidates_score ON candidates (role_key, score DESC);

CREATE TABLE IF NOT EXISTS emails (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id   INTEGER NOT NULL REFERENCES candidates (id) ON DELETE CASCADE,
    address        TEXT NOT NULL,
    provider       TEXT,
    confidence     REAL,
    verify_status  TEXT NOT NULL DEFAULT 'unknown',
    verify_provider TEXT,
    verified_at    TEXT,
    is_primary     INTEGER NOT NULL DEFAULT 0,
    found_at       TEXT,
    UNIQUE (candidate_id, address)
);
CREATE INDEX IF NOT EXISTS idx_emails_address ON emails (address);

CREATE TABLE IF NOT EXISTS messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id  INTEGER NOT NULL REFERENCES candidates (id) ON DELETE CASCADE,
    role_key      TEXT NOT NULL,
    step          INTEGER NOT NULL,
    to_address    TEXT NOT NULL,
    subject       TEXT NOT NULL,
    body          TEXT NOT NULL,
    rendered_at   TEXT,
    send_after    TEXT,
    sent_at       TEXT,
    provider      TEXT,
    provider_id   TEXT,
    status        TEXT NOT NULL DEFAULT 'queued',
    error         TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    variant       TEXT NOT NULL DEFAULT 'a',
    UNIQUE (candidate_id, step)
);
CREATE INDEX IF NOT EXISTS idx_messages_status ON messages (role_key, status, send_after);

CREATE TABLE IF NOT EXISTS bookings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id    INTEGER REFERENCES candidates (id) ON DELETE SET NULL,
    role_key        TEXT,
    provider        TEXT NOT NULL,
    provider_id     TEXT NOT NULL,
    attendee_name   TEXT,
    attendee_email  TEXT,
    start_at        TEXT,
    end_at          TEXT,
    answers_json    TEXT,
    status          TEXT NOT NULL DEFAULT 'booked',
    recheck_score   REAL,
    recheck_verdict TEXT,
    recheck_note    TEXT,
    cancelled_at    TEXT,
    created_at      TEXT,
    UNIQUE (provider, provider_id)
);

CREATE TABLE IF NOT EXISTS suppression (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    value      TEXT NOT NULL,
    reason     TEXT,
    added_at   TEXT,
    UNIQUE (kind, value)
);

CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,
    candidate_id INTEGER,
    role_key     TEXT,
    kind         TEXT NOT NULL,
    detail       TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_candidate ON events (candidate_id, ts);

CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    command   TEXT NOT NULL,
    args      TEXT,
    summary   TEXT,
    dry_run   INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS inbound (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at   TEXT,
    stored_at     TEXT NOT NULL,
    from_address  TEXT NOT NULL,
    subject       TEXT,
    body          TEXT,
    kind          TEXT NOT NULL DEFAULT 'replied',
    candidate_id  INTEGER REFERENCES candidates (id) ON DELETE SET NULL,
    role_key      TEXT,
    handled       INTEGER NOT NULL DEFAULT 0,
    fingerprint   TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_inbound_handled ON inbound (handled, id DESC);

CREATE TABLE IF NOT EXISTS send_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    day       TEXT NOT NULL,
    role_key  TEXT NOT NULL,
    mailbox   TEXT NOT NULL DEFAULT 'default',
    count     INTEGER NOT NULL DEFAULT 0,
    UNIQUE (day, role_key, mailbox)
);
"""


def stage_index(stage: str) -> int:
    try:
        return STAGES.index(stage)
    except ValueError:
        return -1


class Database:
    """Thin wrapper over sqlite3. Rows come back as dicts."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")

    # ---- lifecycle -------------------------------------------------

    MIGRATIONS = [
        # (version introduced, SQL). Each runs once, and is safe to re-run.
        (2, "ALTER TABLE messages ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"),
        (3, "ALTER TABLE messages ADD COLUMN variant TEXT NOT NULL DEFAULT 'a'"),
    ]

    def _migrate(self) -> None:
        """Add columns to a database created by an older version.

        CREATE TABLE IF NOT EXISTS does not add a column to a table that
        already exists, so every schema change needs a line here.
        """
        existing = {row["name"] for row in self.query("PRAGMA table_info(messages)")}
        for _version, sql in self.MIGRATIONS:
            column = sql.split("ADD COLUMN ")[-1].split()[0] if "ADD COLUMN" in sql else ""
            if column and column in existing:
                continue
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # already applied
        self.conn.commit()

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self._migrate()
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ---- helpers ---------------------------------------------------

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = self.conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        cur = self.conn.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None

    # ---- candidates ------------------------------------------------

    def upsert_candidate(self, role_key: str, profile: dict[str, Any]) -> tuple[int, bool]:
        """Insert or update one candidate. Returns (id, created).

        Dedupe key is the normalised LinkedIn URL within a role. The same
        person may legitimately sit in two roles; that is two rows.
        """
        key = norm_linkedin(profile.get("linkedin_url"))
        if not key:
            # No profile URL. Fall back to the provider's id, else name plus
            # company, so two different people called Chris Taylor do not
            # collapse into one row.
            fallback = str(profile.get("external_id") or "").strip()
            if not fallback:
                fallback = "|".join(
                    str(profile.get(f) or "").strip().lower()
                    for f in ("full_name", "company", "location")
                )
            key = "noli:" + fallback.lower()
        existing = self.one(
            "SELECT id FROM candidates WHERE role_key = ? AND linkedin_key = ?",
            (role_key, key),
        )
        payload = {
            "role_key": role_key,
            "linkedin_key": key,
            "linkedin_url": profile.get("linkedin_url"),
            "full_name": profile.get("full_name"),
            "first_name": profile.get("first_name"),
            "last_name": profile.get("last_name"),
            "headline": profile.get("headline"),
            "title": profile.get("title"),
            "company": profile.get("company"),
            "company_domain": profile.get("company_domain"),
            "company_headcount": profile.get("company_headcount"),
            "location": profile.get("location"),
            "country": profile.get("country"),
            "years_experience": profile.get("years_experience"),
            "months_in_current_role": profile.get("months_in_current_role"),
            "jobs_last_3_years": profile.get("jobs_last_3_years"),
            "longest_tenure_years": profile.get("longest_tenure_years"),
            "profile_text": profile.get("profile_text"),
            "profile_json": json.dumps(profile.get("raw") or profile, ensure_ascii=False),
            "source": profile.get("source"),
            "source_search": profile.get("source_search"),
            "updated_at": iso(),
        }
        if existing:
            # MERGE, do not overwrite. A second sighting of the same person by
            # a thinner search (Apollo search returns name + linkedin_url only)
            # must not blank the rich data from the first sighting. Write only
            # the columns the new payload carries a value for; always refresh
            # the housekeeping columns; and keep the stored profile_json unless
            # the new payload has a real profile_text, because losing the raw
            # makes `score --restage` unable to recover the row.
            always = {"updated_at", "source", "source_search"}
            skip = {"role_key", "linkedin_key", "profile_json"}
            has_text = bool(str(profile.get("profile_text") or "").strip())
            updates: dict[str, Any] = {}
            for column, value in payload.items():
                if column in skip:
                    continue
                if column in always or value not in (None, ""):
                    updates[column] = value
            if has_text:
                updates["profile_json"] = payload["profile_json"]
            if updates:
                sets = ", ".join(f"{k} = ?" for k in updates)
                self.conn.execute(
                    f"UPDATE candidates SET {sets} WHERE id = ?",
                    (*updates.values(), existing["id"]),
                )
                self.conn.commit()
            return int(existing["id"]), False
        payload["sourced_at"] = iso()
        payload["stage"] = "sourced"
        cols = ", ".join(payload)
        marks = ", ".join("?" for _ in payload)
        cur = self.conn.execute(
            f"INSERT INTO candidates ({cols}) VALUES ({marks})", tuple(payload.values())
        )
        self.conn.commit()
        return int(cur.lastrowid), True

    def set_stage(self, candidate_id: int, stage: str, note: str = "") -> None:
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}")
        self.conn.execute(
            "UPDATE candidates SET stage = ?, updated_at = ? WHERE id = ?",
            (stage, iso(), candidate_id),
        )
        self.conn.commit()
        self.log_event(candidate_id, f"stage:{stage}", note)

    def candidates(
        self,
        role_key: str | None = None,
        stages: Iterable[str] | None = None,
        limit: int | None = None,
        order: str = "score DESC, id ASC",
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if role_key:
            clauses.append("role_key = ?")
            params.append(role_key)
        stage_list = list(stages) if stages else []
        if stage_list:
            clauses.append(f"stage IN ({', '.join('?' for _ in stage_list)})")
            params.extend(stage_list)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT * FROM candidates {where} ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.query(sql, params)

    def candidate(self, candidate_id: int) -> dict[str, Any] | None:
        return self.one("SELECT * FROM candidates WHERE id = ?", (candidate_id,))

    def contacted_for_another_role(
        self, linkedin_key: str, role_key: str
    ) -> dict[str, Any] | None:
        """Has this person already been written to for a different seat?

        One internal role is posted publicly under five titles at different
        bands. A person who receives two of our emails can see the duplication,
        and it reads as a mass mailing rather than a considered approach.
        """
        if not linkedin_key:
            return None
        return self.one(
            "SELECT c.* FROM candidates c "
            "JOIN messages m ON m.candidate_id = c.id "
            "WHERE c.linkedin_key = ? AND c.role_key != ? "
            "AND m.status IN ('queued', 'sent') "
            "ORDER BY (m.sent_at IS NULL), m.sent_at ASC LIMIT 1",
            (linkedin_key, role_key),
        )

    # ---- emails ----------------------------------------------------

    def add_email(
        self,
        candidate_id: int,
        address: str,
        provider: str = "",
        confidence: float | None = None,
        primary: bool = True,
    ) -> int | None:
        address = norm_email(address)
        if not address:
            return None
        self.conn.execute(
            "INSERT INTO emails (candidate_id, address, provider, confidence, is_primary, found_at) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (candidate_id, address) DO UPDATE SET "
            "provider = excluded.provider, confidence = excluded.confidence",
            (candidate_id, address, provider, confidence, 1 if primary else 0, iso()),
        )
        self.conn.commit()
        row = self.one(
            "SELECT id FROM emails WHERE candidate_id = ? AND address = ?",
            (candidate_id, address),
        )
        return int(row["id"]) if row else None

    def primary_email(self, candidate_id: int) -> dict[str, Any] | None:
        return self.one(
            # Verification outranks the is_primary flag. is_primary only means
            # "found first", and a checked address beats a first guess.
            "SELECT * FROM emails WHERE candidate_id = ? "
            "ORDER BY CASE verify_status "
            "WHEN 'valid' THEN 0 WHEN 'unknown' THEN 1 WHEN 'catch_all' THEN 2 "
            "WHEN 'risky' THEN 3 ELSE 4 END, "
            "is_primary DESC, COALESCE(confidence, 0) DESC, id ASC LIMIT 1",
            (candidate_id,),
        )

    def set_verify(self, email_id: int, status: str, provider: str = "") -> None:
        self.conn.execute(
            "UPDATE emails SET verify_status = ?, verify_provider = ?, verified_at = ? WHERE id = ?",
            (status, provider, iso(), email_id),
        )
        self.conn.commit()

    # ---- suppression -----------------------------------------------

    def suppress(self, kind: str, value: str, reason: str = "") -> None:
        value = value.strip().lower()
        if kind == "email":
            value = norm_email(value)
        elif kind == "linkedin":
            value = norm_linkedin(value)
        if not value:
            return
        self.conn.execute(
            "INSERT INTO suppression (kind, value, reason, added_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (kind, value) DO UPDATE SET reason = excluded.reason",
            (kind, value, reason, iso()),
        )
        self.conn.commit()

    def is_suppressed(self, kind: str, value: str) -> dict[str, Any] | None:
        value = (value or "").strip().lower()
        if kind == "email":
            value = norm_email(value)
        elif kind == "linkedin":
            value = norm_linkedin(value)
        if not value:
            return None
        hit = self.one(
            "SELECT * FROM suppression WHERE kind = ? AND value = ?", (kind, value)
        )
        if hit:
            return hit
        if kind == "email" and "@" in value:
            return self.one(
                "SELECT * FROM suppression WHERE kind = 'domain' AND value = ?",
                (value.split("@", 1)[1],),
            )
        return None

    # ---- messages --------------------------------------------------

    def queue_message(
        self,
        candidate_id: int,
        role_key: str,
        step: int,
        to_address: str,
        subject: str,
        body: str,
        send_after: str,
        variant: str = "a",
    ) -> int:
        self.conn.execute(
            "INSERT INTO messages "
            "(candidate_id, role_key, step, to_address, subject, body, rendered_at, send_after, status, variant) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?) "
            "ON CONFLICT (candidate_id, step) DO UPDATE SET "
            "to_address = excluded.to_address, subject = excluded.subject, "
            "body = excluded.body, rendered_at = excluded.rendered_at, "
            "send_after = excluded.send_after, variant = excluded.variant "
            "WHERE messages.status = 'queued'",
            (candidate_id, role_key, step, norm_email(to_address), subject, body,
             iso(), send_after, variant),
        )
        self.conn.commit()
        row = self.one(
            "SELECT id FROM messages WHERE candidate_id = ? AND step = ?",
            (candidate_id, step),
        )
        return int(row["id"]) if row else 0

    def mark_sent(self, message_id: int, provider: str, provider_id: str = "") -> None:
        self.conn.execute(
            "UPDATE messages SET status = 'sent', sent_at = ?, provider = ?, provider_id = ? WHERE id = ?",
            (iso(), provider, provider_id, message_id),
        )
        self.conn.commit()

    def mark_failed(self, message_id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE messages SET status = 'failed', error = ?, attempts = attempts + 1 "
            "WHERE id = ?",
            (error[:500], message_id),
        )
        self.conn.commit()

    def requeue_failed(self, role_key: str, max_attempts: int = 3) -> int:
        """Put failed sends back in the queue until they have had enough tries.

        A provider outage should not silently drop a person out of the funnel.
        """
        cur = self.conn.execute(
            "UPDATE messages SET status = 'queued' "
            "WHERE role_key = ? AND status = 'failed' AND attempts < ?",
            (role_key, max_attempts),
        )
        self.conn.commit()
        return cur.rowcount or 0

    # ---- send accounting -------------------------------------------

    def sends_today(self, role_key: str, day: str, mailbox: str = "default") -> int:
        row = self.one(
            "SELECT count FROM send_log WHERE day = ? AND role_key = ? AND mailbox = ?",
            (day, role_key, mailbox),
        )
        return int(row["count"]) if row else 0

    def meta_get(self, key: str, default: str = "") -> str:
        row = self.one("SELECT value FROM meta WHERE key = ?", (key,))
        return str(row["value"]) if row else default

    def meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def meta_setdefault(self, key: str, value: str) -> str:
        current = self.meta_get(key)
        if current:
            return current
        self.meta_set(key, value)
        return value

    def sending_days_used(self, before: str | None = None) -> int:
        """How many distinct days this domain has actually sent on.

        Pass `before` (a YYYY-MM-DD day) to count only days strictly earlier
        than it. The warm-up ramp uses this with today's day, so that today's
        own sends cannot advance the ramp tier mid-day: a second send run on a
        ramp-boundary day must see the same tier as the first, or it would send
        the next tier's higher volume and defeat the warm up.
        """
        if before:
            return int(
                self.scalar(
                    "SELECT COUNT(DISTINCT day) FROM send_log WHERE count > 0 AND day < ?",
                    (before,),
                )
                or 0
            )
        return int(
            self.scalar("SELECT COUNT(DISTINCT day) FROM send_log WHERE count > 0") or 0
        )

    def store_inbound(
        self,
        from_address: str,
        subject: str,
        body: str,
        kind: str,
        received_at: str = "",
        candidate_id: int | None = None,
        role_key: str | None = None,
    ) -> tuple[int, bool]:
        """Keep the reply. Returns (id, created).

        Deduped on a fingerprint so re-running the sync does not pile up
        copies of the same message.
        """
        address = norm_email(from_address)
        fingerprint = hashlib.sha256(
            "|".join([address, subject or "", (body or "")[:600], received_at or ""]).encode("utf-8")
        ).hexdigest()
        existing = self.one("SELECT id FROM inbound WHERE fingerprint = ?", (fingerprint,))
        if existing:
            return int(existing["id"]), False
        cur = self.conn.execute(
            "INSERT INTO inbound (received_at, stored_at, from_address, subject, body, "
            "kind, candidate_id, role_key, fingerprint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (received_at, iso(), address, subject, (body or "")[:20000], kind,
             candidate_id, role_key, fingerprint),
        )
        self.conn.commit()
        return int(cur.lastrowid), True

    def inbox(self, only_unhandled: bool = True, limit: int = 50) -> list[dict[str, Any]]:
        where = "WHERE i.handled = 0" if only_unhandled else ""
        return self.query(
            "SELECT i.*, c.full_name, c.stage, c.linkedin_url "
            "FROM inbound i LEFT JOIN candidates c ON c.id = i.candidate_id "
            f"{where} ORDER BY i.id DESC LIMIT ?",
            (limit,),
        )

    def mark_inbound_handled(self, inbound_id: int, handled: bool = True) -> None:
        self.conn.execute(
            "UPDATE inbound SET handled = ? WHERE id = ?",
            (1 if handled else 0, inbound_id),
        )
        self.conn.commit()

    def variant_stats(self, role_key: str | None = None, step: int = 1) -> list[dict[str, Any]]:
        """Reply and booking rate per copy variant, for the given step."""
        where = "WHERE m.step = ? AND m.status = 'sent'"
        params: list[Any] = [step]
        if role_key:
            where += " AND m.role_key = ?"
            params.append(role_key)
        return self.query(
            "SELECT m.variant, COUNT(*) AS sent, "
            "SUM(CASE WHEN c.stage IN ('replied','booked','confirmed','screened','hired') "
            "         THEN 1 ELSE 0 END) AS replied, "
            "SUM(CASE WHEN c.stage IN ('booked','confirmed','screened','hired') "
            "         THEN 1 ELSE 0 END) AS booked "
            "FROM messages m JOIN candidates c ON c.id = m.candidate_id "
            f"{where} GROUP BY m.variant ORDER BY m.variant",
            params,
        )

    def timeline(self, candidate_id: int) -> list[dict[str, Any]]:
        rows = self.query(
            "SELECT ts, kind, detail FROM events WHERE candidate_id = ? ORDER BY ts, id",
            (candidate_id,),
        )
        for message in self.query(
            "SELECT step, variant, subject, status, sent_at, rendered_at, error "
            "FROM messages WHERE candidate_id = ? ORDER BY step",
            (candidate_id,),
        ):
            rows.append({
                "ts": message["sent_at"] or message["rendered_at"],
                "kind": f"message:step{message['step']}:{message['status']}",
                "detail": f"[{message['variant']}] {message['subject']}"
                          + (f" ERROR {message['error']}" if message["error"] else ""),
            })
        return sorted(rows, key=lambda r: str(r.get("ts") or ""))

    def bounce_rate(self, window: int = 200) -> tuple[float, int, int]:
        """(rate, bounced, sent) over the most recent `window` sends."""
        recent = self.query(
            "SELECT to_address FROM messages WHERE status = 'sent' "
            "ORDER BY sent_at DESC LIMIT ?",
            (window,),
        )
        if not recent:
            return 0.0, 0, 0
        # Distinct addresses on both sides. Counting sent MESSAGES in the
        # denominator would inflate it with follow-ups and push the rate down,
        # which is the wrong direction for a safety guard.
        addresses = sorted({r["to_address"] for r in recent if r["to_address"]})
        if not addresses:
            return 0.0, 0, 0
        marks = ",".join("?" for _ in addresses)
        bounced = int(
            self.scalar(
                f"SELECT COUNT(DISTINCT c.id) FROM candidates c "
                f"JOIN emails e ON e.candidate_id = c.id "
                f"WHERE c.stage = 'bounced' AND e.address IN ({marks})",
                addresses,
            )
            or 0
        )
        return bounced / len(addresses), bounced, len(addresses)

    def sends_today_all_roles(self, day: str) -> int:
        """Every role shares the same mailboxes, so the domain cap is global."""
        return int(self.scalar("SELECT COALESCE(SUM(count), 0) FROM send_log WHERE day = ?", (day,)) or 0)

    def record_send(self, role_key: str, day: str, mailbox: str = "default", n: int = 1) -> None:
        self.conn.execute(
            "INSERT INTO send_log (day, role_key, mailbox, count) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (day, role_key, mailbox) DO UPDATE SET count = count + excluded.count",
            (day, role_key, mailbox, n),
        )
        self.conn.commit()

    # ---- events and runs -------------------------------------------

    def log_event(self, candidate_id: int | None, kind: str, detail: str = "") -> None:
        role_key = None
        if candidate_id:
            row = self.one("SELECT role_key FROM candidates WHERE id = ?", (candidate_id,))
            role_key = row["role_key"] if row else None
        self.conn.execute(
            "INSERT INTO events (ts, candidate_id, role_key, kind, detail) VALUES (?, ?, ?, ?, ?)",
            (iso(), candidate_id, role_key, kind, detail[:2000]),
        )
        self.conn.commit()

    def log_run(self, command: str, args: str, summary: str, dry_run: bool) -> None:
        self.conn.execute(
            "INSERT INTO runs (ts, command, args, summary, dry_run) VALUES (?, ?, ?, ?, ?)",
            (iso(), command, args[:2000], summary[:2000], 1 if dry_run else 0),
        )
        self.conn.commit()

    # ---- reporting -------------------------------------------------

    def funnel(self, role_key: str | None = None) -> dict[str, int]:
        rows = self.query(
            "SELECT stage, COUNT(*) AS n FROM candidates "
            + ("WHERE role_key = ? " if role_key else "")
            + "GROUP BY stage",
            (role_key,) if role_key else (),
        )
        counts = {row["stage"]: int(row["n"]) for row in rows}
        return {stage: counts.get(stage, 0) for stage in STAGES}


def open_db(path: Path | str, init: bool = True) -> Database:
    db = Database(path)
    if init:
        db.init_schema()
    return db
