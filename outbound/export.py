"""Get candidates out of here and into whatever else needs them.

Applying through a posting and being emailed cold are two intake paths, and
nothing reconciles them today. This is the bridge: export the people who
replied or booked, import them into the applicant tracking system, and the
recruiting team sees one pipeline.

Three shapes:

- `csv`   every field, for a spreadsheet or a person.
- `ats`   a trimmed set with plain column names, for an applicant tracking
          system's importer. Every ATS asks you to map columns on import, so
          the names are chosen to be obvious rather than to match one vendor.
- `jsonl` one JSON object per line, for anything programmatic.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .config import Role, Settings
from .db import Database
from .errors import OutboundError

FORMATS = ("csv", "ats", "jsonl")

# Stages worth handing to a recruiter. Everything before "sent" is a list, not
# a candidate.
DEFAULT_STAGES = ("replied", "booked", "confirmed", "screened", "hired")

ATS_COLUMNS = [
    "first_name", "last_name", "email", "headline", "current_title",
    "current_company", "location", "linkedin_url", "role", "stage",
    "source", "sourced_on", "screener_booked_for", "notes",
]


def _rows(
    db: Database, role: Role | None, stages: Iterable[str], limit: int | None
) -> list[dict[str, Any]]:
    stage_list = list(stages)
    clauses, params = [], []
    if role:
        clauses.append("c.role_key = ?")
        params.append(role.key)
    if stage_list:
        clauses.append(f"c.stage IN ({', '.join('?' for _ in stage_list)})")
        params.extend(stage_list)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = (
        "SELECT c.*, "
        "  (SELECT e.address FROM emails e WHERE e.candidate_id = c.id "
        "   ORDER BY CASE e.verify_status WHEN 'valid' THEN 0 ELSE 1 END, "
        "            e.is_primary DESC, e.id ASC LIMIT 1) AS email, "
        "  (SELECT b.start_at FROM bookings b WHERE b.candidate_id = c.id "
        "   AND b.status IN ('booked','confirmed') ORDER BY b.start_at ASC LIMIT 1) "
        "   AS screener_booked_for "
        f"FROM candidates c {where} ORDER BY c.score DESC, c.id ASC"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return db.query(sql, params)


def _ats_row(row: dict[str, Any]) -> dict[str, Any]:
    notes = " | ".join(
        part for part in (row.get("personal_note"), row.get("review_note")) if part
    )
    return {
        "first_name": row.get("first_name") or "",
        "last_name": row.get("last_name") or "",
        "email": row.get("email") or "",
        "headline": row.get("headline") or "",
        "current_title": row.get("title") or "",
        "current_company": row.get("company") or "",
        "location": row.get("location") or "",
        "linkedin_url": row.get("linkedin_url") or "",
        "role": row.get("role_key") or "",
        "stage": row.get("stage") or "",
        "source": "outbound",
        "sourced_on": str(row.get("sourced_at") or "")[:10],
        "screener_booked_for": row.get("screener_booked_for") or "",
        "notes": notes,
    }


def export(
    db: Database,
    settings: Settings,
    role: Role | None,
    path: Path,
    fmt: str = "ats",
    stages: Iterable[str] | None = None,
    limit: int | None = None,
) -> int:
    if fmt not in FORMATS:
        raise OutboundError(f"format must be one of {', '.join(FORMATS)}, not {fmt!r}")
    rows = _rows(db, role, stages if stages is not None else DEFAULT_STAGES, limit)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "jsonl":
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                clean = {k: v for k, v in row.items() if k not in ("profile_json", "score_json")}
                handle.write(json.dumps(clean, ensure_ascii=False, default=str) + "\n")
        return len(rows)

    if fmt == "ats":
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=ATS_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow(_ats_row(row))
        return len(rows)

    fields = [
        "id", "role_key", "stage", "score", "full_name", "first_name", "last_name",
        "email", "title", "company", "company_headcount", "location", "country",
        "linkedin_url", "years_experience", "months_in_current_role",
        "jobs_last_3_years", "longest_tenure_years", "source", "source_search",
        "sourced_at", "review_state", "personal_note", "review_note",
        "screener_booked_for",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})
    return len(rows)
