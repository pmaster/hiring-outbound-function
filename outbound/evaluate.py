"""Shared logic for the AI evaluation stage.

The evaluation stage is a second, richer screen that sits after scoring. The
heuristic scorer is a cheap router: it reads regexes and ranks. The evaluator
reads the whole profile against the role the way a person would, returns a fit
verdict with reasons, and drafts the one specific personal note the first email
needs. That draft is what lets the list move without a person writing a note
for every candidate by hand.

Two providers implement it. `dryrun` reuses the heuristic score and the
evidence the scorer already found, so the whole flow runs and tests offline
with no API key. `anthropic` calls a model. The interface between them is a
plain dict, documented in `providers.EvaluateProvider`.
"""

from __future__ import annotations

from typing import Any

from .config import Role


def build_brief(role: Role) -> dict[str, Any]:
    """A compact, provider-agnostic description of what this seat wants.

    Passed to the evaluator as the standard against which a profile is judged.
    Everything here is already in the role config; this just gathers it.
    """
    icp = role.icp or {}
    return {
        "role_key": role.key,
        "title": role.title,
        "one_liner": role.one_liner,
        "seniority": role.seniority,
        "employment": role.employment,
        "titles_wanted": list(icp.get("titles") or []),
        "titles_excluded": list(icp.get("title_excludes") or []),
        "seniority_wanted": list(icp.get("seniority") or []),
        "company_headcount": list(icp.get("company_headcount") or []),
        "min_years_experience": icp.get("min_years_experience"),
        "keywords_any": list(icp.get("keywords_any") or []),
        "industries_prefer": list(icp.get("industries_prefer") or []),
        "geo": list(icp.get("geo") or []),
        "must_haves": list(icp.get("must_haves") or []),
        "nice_to_haves": list(icp.get("nice_to_haves") or []),
        # The named positive signals, so the model weighs what the config weighs.
        "positive_signals": [s.key for s in role.signals if s.weight > 0],
        "hard_disqualifiers": [d.reason for d in role.disqualifiers],
    }


def candidate_summary(profile: dict[str, Any], max_chars: int = 4000) -> str:
    """The profile text an evaluator reads, trimmed to a sane size."""
    parts = []
    for label, key in (
        ("Name", "full_name"), ("Title", "title"), ("Company", "company"),
        ("Location", "location"), ("Country", "country"),
        ("Years experience", "years_experience"),
        ("Months in current role", "months_in_current_role"),
    ):
        value = profile.get(key)
        if value not in (None, "", []):
            parts.append(f"{label}: {value}")
    text = str(profile.get("profile_text") or "").strip()
    if text:
        parts.append("Profile:\n" + text)
    out = "\n".join(parts)
    return out[:max_chars]



def note_from_evidence(profile: dict[str, Any]) -> str:
    """A clean, deterministic note for the OFFLINE provider.

    It frames real fields from this profile (title, company). It is a
    placeholder, not the specific opener the design wants: the offline provider
    never emails a real person, and the anthropic provider writes the real note
    by reading the profile. Keeping this plain and lint-safe is the point;
    dressing a fragment up as a specific detail would be the generic line the
    whole design fights.
    """
    title = str(profile.get("title") or "").strip()
    company = str(profile.get("company") or "").strip()
    if title and company:
        return f"Your work as {title} at {company} is why I am writing."
    if title:
        return f"Your track as {title} is why I am writing."
    if company:
        return f"Your work at {company} is why I am writing."
    return "Your background is a close match for what this seat needs."


def route_verdict(
    fit: float, verdict: str, disqualify: bool,
    approve_at: float, reject_below: float,
) -> str:
    """Turn an evaluator verdict into a funnel decision.

    Returns 'approve', 'reject' or 'review'. 'review' means a person still
    looks: the evaluator was not confident enough to decide either way.
    """
    if disqualify:
        return "reject"
    verdict = (verdict or "").lower()
    if verdict == "strong" and fit >= approve_at:
        return "approve"
    if verdict == "weak" or fit < reject_below:
        return "reject"
    return "review"
