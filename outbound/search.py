"""Turn a role's saved searches into something you can actually run.

Two outputs, because there are two ways to build a list.

1. A URL and a boolean string you paste into LinkedIn or Sales Navigator, plus
   the filters to set by hand. This is the default for the senior seats. The
   SOP is explicit: read each profile, and never connect a real LinkedIn
   account to a scraper.
2. A provider spec, for when `providers.search` is set to an API that returns
   profiles without touching anyone's LinkedIn session.
"""

from __future__ import annotations

import urllib.parse
from typing import Any

from .config import Role, Search, Settings

LINKEDIN_PEOPLE = "https://www.linkedin.com/search/results/people/"
SALES_NAV = "https://www.linkedin.com/sales/search/people"

# Sales Navigator seniority facet labels, as they read in the UI.
SENIORITY_LABELS = {
    "manager": "Manager",
    "senior": "Senior",
    "staff": "Senior",
    "lead": "Manager",
    "director": "Director",
    "vp": "VP",
    "cxo": "CXO",
    "owner": "Owner / Partner",
    "partner": "Owner / Partner",
    "principal": "Director",
}


def boolean_string(spec: Search) -> str:
    """The keyword box contents. Titles ORed, then the extra keywords ANDed."""
    parts: list[str] = []
    if spec.titles:
        titles = " OR ".join(f'"{t}"' for t in spec.titles)
        parts.append(f"({titles})")
    if spec.keywords:
        parts.append(f"({spec.keywords})")
    return " AND ".join(parts)


def linkedin_url(spec: Search) -> str:
    query = boolean_string(spec)
    params = {"keywords": query, "origin": "GLOBAL_SEARCH_HEADER"}
    return LINKEDIN_PEOPLE + "?" + urllib.parse.urlencode(params)


def manual_checklist(role: Role, spec: Search) -> list[str]:
    """Filters that no URL can carry reliably. Set these by hand."""
    icp = role.icp or {}
    items: list[str] = []
    if spec.geo:
        items.append(f"Geography: {', '.join(spec.geo)}")
    if spec.headcount:
        items.append(f"Company headcount: {', '.join(spec.headcount)}")
    if spec.seniority:
        items.append(f"Seniority: {', '.join(spec.seniority)}")
    if icp.get("min_years_experience"):
        items.append(f"Years of experience: {icp['min_years_experience']}+")
    if icp.get("min_months_in_role"):
        low = icp["min_months_in_role"]
        high = icp.get("max_months_in_role")
        items.append(
            f"Time in current role: {low} months"
            + (f" to {high} months" if high else " or more")
        )
    if icp.get("timezone_rule"):
        items.append(f"Working hours rule: {icp['timezone_rule']}")
    if icp.get("metro_priority"):
        items.append("Work these metros first: " + ", ".join(icp["metro_priority"]))
    if icp.get("title_excludes"):
        items.append("Exclude titles: " + ", ".join(icp["title_excludes"][:8]))
    if icp.get("geo_exclude"):
        items.append("Do not source from: " + ", ".join(icp["geo_exclude"]))
    items.append(f"Target for this search: {spec.target} profiles")
    return items


def provider_spec(role: Role, spec: Search, settings: Settings) -> dict[str, Any]:
    """A neutral search description. Each adapter maps it to its own API."""
    icp = role.icp or {}
    return {
        "name": spec.name,
        "role_key": role.key,
        "titles": list(spec.titles or icp.get("titles") or []),
        "title_excludes": list(icp.get("title_excludes") or []),
        "keywords": spec.keywords,
        "boolean": boolean_string(spec),
        "geo": list(spec.geo or icp.get("geo") or []),
        "headcount": list(spec.headcount or []),
        "seniority": list(spec.seniority or icp.get("seniority") or []),
        "seniority_labels": [
            SENIORITY_LABELS.get(str(s).lower(), str(s)) for s in (spec.seniority or [])
        ],
        "min_years_experience": icp.get("min_years_experience"),
        "target": spec.target,
        "linkedin_url": linkedin_url(spec),
    }


def render_plan(role: Role, settings: Settings) -> str:
    """The text `outbound search <role>` prints."""
    lines: list[str] = []
    lines.append(f"# Sourcing plan: {role.title} ({role.key})")
    lines.append("")
    lines.append(f"Target list size: {role.target_list_size} hand checked people.")
    lines.append(
        "Read every profile before it goes on the list. Keep the person only if "
        "the work history shows a finished hard thing. That is the whole edge."
    )
    lines.append("")
    lines.append(
        "Do NOT connect a real LinkedIn account to a scraper. Read profiles in "
        "the browser and take email data from a vendor instead. See docs/OPSEC.md."
    )
    lines.append("")
    for index, spec in enumerate(role.searches, start=1):
        lines.append(f"## {index}. {spec.name}")
        lines.append("")
        lines.append("Keyword box:")
        lines.append("")
        lines.append(f"    {boolean_string(spec)}")
        lines.append("")
        lines.append("Paste into LinkedIn people search:")
        lines.append("")
        lines.append(f"    {linkedin_url(spec)}")
        lines.append("")
        lines.append("Sales Navigator filters to set by hand:")
        for item in manual_checklist(role, spec):
            lines.append(f"  - {item}")
        lines.append("")
    lines.append("## Import")
    lines.append("")
    lines.append(
        "Save the list as CSV with at least these columns: full_name, "
        "linkedin_url, title, company, location. Optional and useful: "
        "company_headcount, company_domain, summary, personal_note."
    )
    lines.append("")
    lines.append(f"    python3 -m outbound import {role.key} list.csv")
    return "\n".join(lines)
