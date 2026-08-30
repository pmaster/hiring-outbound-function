"""Turn a provider's raw profile payload into the one shape we score.

Every sourcing provider returns a different JSON. This module is the only
place that knows about their key names. Add a provider's aliases here rather
than teaching the scorer a new shape.
"""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Iterable

from .util import name_parts, norm_linkedin, now

# Alias tables. First hit wins, so put the most reliable key first.
ALIASES: dict[str, tuple[str, ...]] = {
    "full_name": ("full_name", "fullName", "name", "displayName", "profile_name"),
    "first_name": ("first_name", "firstName", "given_name"),
    "last_name": ("last_name", "lastName", "family_name", "surname"),
    "headline": ("headline", "occupation", "sub_title", "subTitle", "tagline"),
    "title": ("title", "job_title", "jobTitle", "position", "current_title",
              "currentTitle", "positionTitle"),
    "company": ("company", "company_name", "companyName", "current_company",
                "currentCompany", "organization", "employer"),
    "company_domain": ("company_domain", "companyDomain", "organization_domain",
                       "website", "company_website"),
    "company_headcount": ("company_headcount", "companySize", "company_size",
                          "employee_count", "employeeCount", "staff_count",
                          "estimated_num_employees"),
    "location": ("location", "location_name", "locationName", "geo",
                 "geoLocationName", "addressWithCountry", "formatted_address"),
    "country": ("country", "country_code", "countryCode", "location_country"),
    "linkedin_url": ("linkedin_url", "linkedinUrl", "profile_url", "profileUrl",
                     "publicProfileUrl", "public_profile_url", "url", "link",
                     "linkedin_profile_url"),
    "summary": ("summary", "about", "bio", "description"),
    "external_id": ("external_id", "id", "profile_id", "publicIdentifier",
                    "public_identifier", "urn"),
    "email": ("email", "work_email", "workEmail", "email_address", "primary_email"),
}

POSITION_KEYS = ("positions", "experience", "experiences", "work_experience", "jobs")

# Country names we see in a LinkedIn location string, mapped to ISO codes.
# Only the countries that matter for the compliance gate are listed; anything
# else stays unknown and the geo rules treat unknown as "do not send".
COUNTRY_HINTS: list[tuple[str, str]] = [
    ("united states", "US"), ("usa", "US"), ("u.s.", "US"),
    ("united kingdom", "GB"), ("england", "GB"), ("scotland", "GB"),
    ("wales", "GB"), ("northern ireland", "GB"),
    ("canada", "CA"), ("poland", "PL"), ("polska", "PL"),
    ("germany", "DE"), ("deutschland", "DE"), ("france", "FR"),
    ("spain", "ES"), ("españa", "ES"), ("italy", "IT"), ("italia", "IT"),
    ("netherlands", "NL"), ("ireland", "IE"), ("portugal", "PT"),
    ("sweden", "SE"), ("denmark", "DK"), ("finland", "FI"), ("norway", "NO"),
    ("austria", "AT"), ("belgium", "BE"), ("czech", "CZ"), ("greece", "GR"),
    ("hungary", "HU"), ("romania", "RO"), ("slovakia", "SK"),
    ("slovenia", "SI"), ("bulgaria", "BG"), ("croatia", "HR"),
    ("estonia", "EE"), ("latvia", "LV"), ("lithuania", "LT"),
    ("luxembourg", "LU"), ("malta", "MT"), ("cyprus", "CY"),
    ("australia", "AU"), ("new zealand", "NZ"), ("india", "IN"),
    ("philippines", "PH"), ("mexico", "MX"), ("brazil", "BR"),
    ("south africa", "ZA"), ("singapore", "SG"), ("japan", "JP"),
    ("united arab emirates", "AE"), ("israel", "IL"), ("switzerland", "CH"),
]

# Two letter US state abbreviations used in "Austin, TX" style locations.
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID",
    "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS",
    "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV",
    "WI", "WY", "DC",
}

HEADCOUNT_BANDS = {
    "1": 1, "2-10": 6, "11-50": 30, "51-200": 125, "201-500": 350,
    "501-1000": 750, "1001-5000": 3000, "5001-10000": 7500, "10001+": 20000,
}


def _first(raw: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        if name in raw and raw[name] not in (None, "", [], {}):
            return raw[name]
    return None


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if text in HEADCOUNT_BANDS:
        return HEADCOUNT_BANDS[text]
    match = re.search(r"(\d[\d,]*)\s*(?:-|to|–)\s*(\d[\d,]*)", text)
    if match:
        low = int(match.group(1).replace(",", ""))
        high = int(match.group(2).replace(",", ""))
        return (low + high) // 2
    match = re.search(r"\d[\d,]*", text)
    return int(match.group(0).replace(",", "")) if match else None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        match = re.search(r"\d+(\.\d+)?", str(value))
        return float(match.group(0)) if match else None


def guess_country(location: str | None, explicit: str | None = None) -> str:
    """ISO 3166 alpha 2, or "" when we cannot tell.

    Unknown is a real answer. The compliance gate refuses to send to unknown
    rather than guessing US, because guessing wrong is the expensive direction.
    """
    if explicit:
        text = str(explicit).strip()
        if len(text) == 2 and text.isalpha():
            return text.upper()
        for needle, code in COUNTRY_HINTS:
            if needle in text.lower():
                return code
    text = (location or "").lower()
    if not text:
        return ""
    for needle, code in COUNTRY_HINTS:
        if needle in text:
            return code
    tail = (location or "").split(",")[-1].strip().upper()
    if tail in US_STATES:
        return "US"
    return ""


def _parse_date(value: Any) -> _dt.date | None:
    if value in (None, "", "Present", "present"):
        return None
    if isinstance(value, dict):
        year = _to_int(value.get("year"))
        if not year:
            return None
        month = _to_int(value.get("month")) or 1
        return _dt.date(year, max(1, min(12, month)), 1)
    text = str(value).strip()
    if re.fullmatch(r"\d{4}", text):
        return _dt.date(int(text), 1, 1)
    match = re.fullmatch(r"(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", text)
    if match:
        return _dt.date(
            int(match.group(1)),
            max(1, min(12, int(match.group(2)))),
            max(1, min(28, int(match.group(3) or 1))),
        )
    months = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
    match = re.search(r"([A-Za-z]{3,})\s+(\d{4})", text)
    if match and match.group(1)[:3].lower() in months:
        return _dt.date(int(match.group(2)), months.index(match.group(1)[:3].lower()) + 1, 1)
    return None


def _positions(raw: dict[str, Any]) -> list[dict[str, Any]]:
    for key in POSITION_KEYS:
        value = raw.get(key)
        if isinstance(value, list) and value:
            return [p for p in value if isinstance(p, dict)]
    return []


def _months_between(start: _dt.date, end: _dt.date) -> float:
    return max(0.0, (end.year - start.year) * 12 + (end.month - start.month))


def derive_history(raw: dict[str, Any], today: _dt.date | None = None) -> dict[str, Any]:
    """Work out tenure numbers from a positions list. Missing stays missing."""
    today = today or now().date()
    spans: list[tuple[_dt.date, _dt.date, bool]] = []
    for position in _positions(raw):
        start = _parse_date(
            _first(position, ("start_date", "startDate", "starts_at", "startsAt",
                              "date_from", "from", "start"))
        )
        end_value = _first(position, ("end_date", "endDate", "ends_at", "endsAt",
                                      "date_to", "to", "end"))
        end = _parse_date(end_value)
        current = bool(
            position.get("is_current")
            or position.get("current")
            or (end is None and start is not None)
        )
        if start is None:
            continue
        spans.append((start, end or today, current))
    if not spans:
        return {}
    spans.sort(key=lambda s: s[0])
    longest = max(_months_between(s, e) for s, e, _ in spans) / 12.0
    earliest = min(s for s, _, _ in spans)
    years_experience = _months_between(earliest, today) / 12.0
    three_years_ago = _dt.date(today.year - 3, today.month, 1)
    jobs_recent = sum(1 for s, _, _ in spans if s >= three_years_ago)
    current_spans = [s for s, _, c in spans if c]
    months_in_role = (
        _months_between(max(current_spans), today) if current_spans else None
    )
    out: dict[str, Any] = {
        "longest_tenure_years": round(longest, 2),
        "years_experience": round(years_experience, 2),
        "jobs_last_3_years": jobs_recent,
    }
    if months_in_role is not None:
        out["months_in_current_role"] = round(months_in_role, 1)
    return out


def build_profile_text(raw: dict[str, Any], base: dict[str, Any]) -> str:
    """One searchable blob. Regex signals run against this."""
    chunks: list[str] = []
    for key in ("headline", "title", "company", "location"):
        if base.get(key):
            chunks.append(str(base[key]))
    summary = _first(raw, ALIASES["summary"])
    if summary:
        chunks.append(str(summary))
    for position in _positions(raw):
        for key in ("title", "jobTitle", "position", "company", "companyName",
                    "description", "summary"):
            value = position.get(key)
            if value:
                chunks.append(str(value))
    for key in ("skills", "certifications", "education", "projects"):
        value = raw.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    chunks.append(item)
                elif isinstance(item, dict):
                    for sub in ("name", "title", "school", "degree", "field_of_study"):
                        if item.get(sub):
                            chunks.append(str(item[sub]))
    text = " \n ".join(c for c in chunks if c)
    return re.sub(r"\s+", " ", text).strip()


def normalize(raw: dict[str, Any], source: str = "", source_search: str = "") -> dict[str, Any]:
    """Provider payload in, canonical profile out."""
    if not isinstance(raw, dict):
        raise TypeError("profile payload must be a dict")
    out: dict[str, Any] = {"source": source, "source_search": source_search, "raw": raw}
    for canonical, names in ALIASES.items():
        value = _first(raw, names)
        if value is not None:
            out[canonical] = value

    full_name = str(out.get("full_name") or "").strip()
    first = str(out.get("first_name") or "").strip()
    last = str(out.get("last_name") or "").strip()
    if not full_name and (first or last):
        full_name = f"{first} {last}".strip()
    if full_name and not (first and last):
        first, last = name_parts(full_name)
    out["full_name"] = full_name
    out["first_name"] = first
    out["last_name"] = last

    out["linkedin_url"] = str(out.get("linkedin_url") or "").strip()
    if out["linkedin_url"] and "linkedin.com" not in out["linkedin_url"].lower():
        out["linkedin_url"] = ""
    out["company_headcount"] = _to_int(out.get("company_headcount"))
    out["country"] = guess_country(out.get("location"), out.get("country"))

    if not out.get("title") and out.get("headline"):
        # "Head of Operations at Acme" -> "Head of Operations"
        out["title"] = str(out["headline"]).split(" at ")[0].strip()

    derived = derive_history(raw)
    for key, value in derived.items():
        if out.get(key) in (None, ""):
            out[key] = value
    for key in ("years_experience", "months_in_current_role", "longest_tenure_years"):
        out[key] = _to_float(out.get(key))
    out["jobs_last_3_years"] = _to_int(out.get("jobs_last_3_years"))

    out["profile_text"] = build_profile_text(raw, out)
    out["linkedin_key"] = norm_linkedin(out.get("linkedin_url"))
    return out
