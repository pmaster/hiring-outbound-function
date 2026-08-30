"""Apollo.io. People search and email reveal.

Endpoints verified against Apollo's OpenAPI spec on 2026-08-30.

TWO THINGS THAT LOOK WRONG AND ARE NOT:

1. **Every parameter goes in the query string, not in a JSON body.** Both
   `mixed_people/api_search` and `people/match` declare all their parameters
   as `in: query` and have no request body at all. A JSON body is a silent
   no-op: you get results, they are just not filtered the way you asked. That
   is the worst kind of bug, so this adapter sends query parameters.
2. **Array parameters carry a literal `[]` suffix and repeat**, for example
   `person_titles[]=Head+of+Operations&person_titles[]=Director+of+Operations`.

Search returns obfuscated names and `has_email` booleans, not addresses. It
costs no credits. Revealing an address is a separate `people/match` call and
costs one credit per person found, zero per miss.
"""

from __future__ import annotations

from typing import Any

from .. import httpjson
from ..config import secret
from ..util import norm_email
from . import register

BASE = "https://api.apollo.io/api/v1"

SENIORITY_MAP = {
    "manager": "manager", "senior": "senior", "staff": "senior",
    "lead": "manager", "director": "director", "vp": "vp",
    "cxo": "c_suite", "owner": "owner", "partner": "partner",
    "principal": "director", "entry": "entry", "associate": "entry",
}
HEADCOUNT_MAP = {
    "1": "1,10", "2-10": "1,10", "11-50": "11,50", "51-200": "51,200",
    "201-500": "201,500", "501-1000": "501,1000", "1001-5000": "1001,5000",
    "5001-10000": "5001,10000", "10001+": "10001,1000000",
}


def _headers() -> dict[str, str]:
    return {
        "x-api-key": secret("APOLLO_API_KEY", required=True),
        "Content-Type": "application/json",
    }


class ApolloSearch:
    name = "apollo"

    def __init__(self, settings: Any):
        self.settings = settings

    def search(self, spec: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        per_page = 100
        while len(out) < limit and page <= 25:
            params: dict[str, Any] = {
                "page": page,
                "per_page": min(per_page, limit - len(out)),
            }
            if spec.get("titles"):
                params["person_titles[]"] = list(spec["titles"])
            if spec.get("geo"):
                params["person_locations[]"] = list(spec["geo"])
            if spec.get("keywords"):
                params["q_keywords"] = spec["keywords"]
            seniorities = sorted({
                SENIORITY_MAP[s.lower()] for s in spec.get("seniority", [])
                if s.lower() in SENIORITY_MAP
            })
            if seniorities:
                params["person_seniorities[]"] = seniorities
            ranges = [HEADCOUNT_MAP[h] for h in spec.get("headcount", []) if h in HEADCOUNT_MAP]
            if ranges:
                params["organization_num_employees_ranges[]"] = ranges

            data = httpjson.post(f"{BASE}/mixed_people/api_search", headers=_headers(), params=params)
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
        # Query parameters, not a body. A body here is silently ignored.
        params: dict[str, Any] = {"reveal_personal_emails": "false"}
        if candidate.get("linkedin_url"):
            params["linkedin_url"] = candidate["linkedin_url"]
        else:
            if candidate.get("first_name"):
                params["first_name"] = candidate["first_name"]
            if candidate.get("last_name"):
                params["last_name"] = candidate["last_name"]
            if candidate.get("company_domain"):
                params["domain"] = candidate["company_domain"]
            elif candidate.get("company"):
                params["organization_name"] = candidate["company"]
        if len(params) == 1:
            return []

        data = httpjson.post(f"{BASE}/people/match", headers=_headers(), params=params)
        person = (data or {}).get("person") or {}
        address = norm_email(person.get("email") or "")
        if not address or "email_not_unlocked" in address or address.endswith("@domain.com"):
            return []
        status = str(person.get("email_status") or "").lower()
        confidence = {"verified": 0.95, "likely": 0.7, "guessed": 0.55}.get(status, 0.6)
        return [{"address": address, "confidence": confidence, "source": "apollo"}]


register("search", "apollo")(ApolloSearch)
register("enrich", "apollo")(ApolloEnrich)
