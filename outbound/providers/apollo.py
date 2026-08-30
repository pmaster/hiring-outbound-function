"""Apollo.io. People search and email reveal.

Apollo can do both stages, which makes it the cheapest way to start. Its data
on senior operators at small companies is thinner than a hand built list, so
use it for the volume seats and hand build the senior ones.
"""

from __future__ import annotations

from typing import Any

from ..config import secret
from ..httpjson import post
from ..util import norm_email
from . import register

BASE = "https://api.apollo.io/api/v1"

# Apollo seniority facet values.
SENIORITY_MAP = {
    "manager": "manager",
    "senior": "senior",
    "staff": "senior",
    "lead": "manager",
    "director": "director",
    "vp": "vp",
    "cxo": "c_suite",
    "owner": "owner",
    "partner": "partner",
    "principal": "director",
}

# Apollo headcount ranges, as strings it accepts.
HEADCOUNT_MAP = {
    "1": "1,10", "2-10": "1,10", "11-50": "11,50", "51-200": "51,200",
    "201-500": "201,500", "501-1000": "501,1000", "1001-5000": "1001,5000",
    "5001-10000": "5001,10000", "10001+": "10001,1000000",
}


def _headers() -> dict[str, str]:
    return {"X-Api-Key": secret("APOLLO_API_KEY", required=True), "Content-Type": "application/json"}


class ApolloSearch:
    name = "apollo"

    def __init__(self, settings: Any):
        self.settings = settings

    def search(self, spec: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        per_page = 100
        while len(out) < limit and page <= 20:
            body: dict[str, Any] = {
                "person_titles": spec.get("titles") or [],
                "person_locations": spec.get("geo") or [],
                "q_keywords": spec.get("keywords") or "",
                "page": page,
                "per_page": min(per_page, limit - len(out)),
            }
            seniorities = [
                SENIORITY_MAP[s.lower()] for s in spec.get("seniority", [])
                if s.lower() in SENIORITY_MAP
            ]
            if seniorities:
                body["person_seniorities"] = sorted(set(seniorities))
            ranges = [
                HEADCOUNT_MAP[h] for h in spec.get("headcount", []) if h in HEADCOUNT_MAP
            ]
            if ranges:
                body["organization_num_employees_ranges"] = ranges
            data = post(f"{BASE}/mixed_people/search", headers=_headers(), body=body)
            people = (data or {}).get("people") or []
            if not people:
                break
            for person in people:
                person["_search"] = spec.get("name")
                out.append(person)
            page += 1
        return out[:limit]


class ApolloEnrich:
    name = "apollo"

    def __init__(self, settings: Any):
        self.settings = settings

    def find_email(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"reveal_personal_emails": False}
        if candidate.get("linkedin_url"):
            body["linkedin_url"] = candidate["linkedin_url"]
        if candidate.get("first_name"):
            body["first_name"] = candidate["first_name"]
        if candidate.get("last_name"):
            body["last_name"] = candidate["last_name"]
        if candidate.get("company"):
            body["organization_name"] = candidate["company"]
        if candidate.get("company_domain"):
            body["domain"] = candidate["company_domain"]
        data = post(f"{BASE}/people/match", headers=_headers(), body=body)
        person = (data or {}).get("person") or {}
        address = norm_email(person.get("email") or "")
        if not address or "email_not_unlocked" in address or "domain.com" in address:
            return []
        status = str(person.get("email_status") or "").lower()
        confidence = {"verified": 0.95, "guessed": 0.55, "likely": 0.7}.get(status, 0.6)
        return [{"address": address, "confidence": confidence, "source": "apollo"}]


register("search", "apollo")(ApolloSearch)
register("enrich", "apollo")(ApolloEnrich)
