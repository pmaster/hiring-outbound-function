"""Score a candidate against a role ICP.

The score is a number between 0 and 1 and it is only a router. It decides
which candidates a person looks at, and in what order. It does not decide who
gets an email; a person does that, in `outbound review`.

Every score carries its own breakdown, so a reviewer can see which signal
produced it and argue with the config rather than with the number.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Disqualifier, Role, Signal
from .util import clamp

_REGEX_CACHE: dict[str, re.Pattern[str]] = {}


def _compiled(pattern: str) -> re.Pattern[str]:
    if pattern not in _REGEX_CACHE:
        _REGEX_CACHE[pattern] = re.compile(pattern, re.I)
    return _REGEX_CACHE[pattern]


def _phrase(value: str) -> re.Pattern[str]:
    """Word bounded match for a literal phrase.

    Substring matching is wrong here. "coo" inside "coordinator" scored an
    Operations Coordinator as a COO, which inflated every list. Word
    boundaries stop that. Internal whitespace matches any run of whitespace.
    """
    key = "\x00phrase:" + value
    if key not in _REGEX_CACHE:
        parts = [re.escape(p) for p in value.split()]
        body = r"\s+".join(parts) if parts else re.escape(value)
        _REGEX_CACHE[key] = re.compile(rf"(?<![\w]){body}(?![\w])", re.I)
    return _REGEX_CACHE[key]


def matches_any(text: str, values) -> list[str]:
    """Every phrase in `values` that appears in `text` on word boundaries."""
    if not text:
        return []
    return [v for v in values if v and _phrase(v).search(text)]


@dataclass
class SignalResult:
    key: str
    weight: float
    strength: float
    contribution: float
    detail: str = ""


@dataclass
class ScoreResult:
    score: float
    disqualified: bool = False
    disqualifier: str = ""
    reason: str = ""
    signals: list[SignalResult] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "score": round(self.score, 4),
                "disqualified": self.disqualified,
                "disqualifier": self.disqualifier,
                "reason": self.reason,
                "missing_fields": self.missing_fields,
                "signals": [
                    {
                        "key": s.key,
                        "weight": round(s.weight, 4),
                        "strength": round(s.strength, 4),
                        "contribution": round(s.contribution, 4),
                        "detail": s.detail,
                    }
                    for s in self.signals
                ],
            },
            ensure_ascii=False,
        )

    def top_reasons(self, limit: int = 3) -> list[str]:
        ranked = sorted(self.signals, key=lambda s: s.contribution, reverse=True)
        return [f"{s.key} {s.contribution:+.2f}" for s in ranked[:limit] if s.contribution]

    def worst_reasons(self, limit: int = 3) -> list[str]:
        ranked = sorted(self.signals, key=lambda s: s.contribution)
        return [
            f"{s.key} {s.contribution:+.2f}"
            for s in ranked[:limit]
            if s.contribution <= 0
        ]


def _field_value(profile: dict[str, Any], name: str) -> Any:
    if name in profile:
        return profile[name]
    raw = profile.get("raw")
    if isinstance(raw, dict) and name in raw:
        return raw[name]
    return None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_as_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_as_text(v) for v in value.values())
    return str(value)


def _as_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _ramp(value: float, hard: float, soft: float | None, above: bool) -> float:
    """Full credit past `hard`, linear credit between `soft` and `hard`."""
    if above:
        if value >= hard:
            return 1.0
        if soft is None or soft >= hard:
            return 0.0
        return clamp((value - soft) / (hard - soft))
    if value <= hard:
        return 1.0
    if soft is None or soft <= hard:
        return 0.0
    return clamp((soft - value) / (soft - hard))


def evaluate_signal(signal: Signal, profile: dict[str, Any]) -> tuple[float, str, bool]:
    """Returns (strength 0..1, detail, field_was_missing)."""
    value = _field_value(profile, signal.field)
    missing = value in (None, "", [], {})

    if signal.kind == "present":
        return (0.0 if missing else 1.0), signal.field, False
    if signal.kind == "missing":
        return (1.0 if missing else 0.0), signal.field, False

    if signal.kind in {"any_of", "none_of"}:
        text = _as_text(value)
        hits = matches_any(text, signal.values)
        if signal.kind == "any_of":
            return (1.0 if hits else 0.0), (hits[0] if hits else ""), missing
        return (0.0 if hits else 1.0), (hits[0] if hits else ""), missing

    if signal.kind == "regex_any":
        text = _as_text(value)
        if not text:
            return 0.0, "", True
        hits = [p for p in signal.patterns if _compiled(p).search(text)]
        if not hits:
            return 0.0, "", False
        # One hit is real evidence. Three or more is as much as we credit.
        strength = clamp(0.6 + 0.2 * (len(hits) - 1))
        return strength, ", ".join(hits[:3]), False

    number = _as_number(value)
    if number is None:
        # A numeric signal with no data scores half. Absence of evidence is not
        # evidence of absence, and zeroing it would bury every thin profile.
        return 0.5, "no data", True

    if signal.kind == "range":
        low = signal.minimum if signal.minimum is not None else float("-inf")
        high = signal.maximum if signal.maximum is not None else float("inf")
        if low <= number <= high:
            return 1.0, f"{number:g} in [{low:g}, {high:g}]", False
        if number < low:
            return _ramp(number, low, signal.soft_min, above=True), f"{number:g} below {low:g}", False
        return _ramp(number, high, signal.soft_max, above=False), f"{number:g} above {high:g}", False

    if signal.kind == "min_value":
        hard = signal.minimum if signal.minimum is not None else 0.0
        return _ramp(number, hard, signal.soft_min, above=True), f"{number:g} vs min {hard:g}", False

    if signal.kind == "max_value":
        hard = signal.maximum if signal.maximum is not None else 0.0
        return _ramp(number, hard, signal.soft_max, above=False), f"{number:g} vs max {hard:g}", False

    return 0.0, f"unhandled kind {signal.kind}", False


def evaluate_disqualifier(
    rule: Disqualifier,
    profile: dict[str, Any],
    is_suppressed: Callable[[str, str], bool] | None = None,
    blocked_countries: set[str] | None = None,
    allowed_countries: set[str] | None = None,
) -> bool:
    value = _field_value(profile, rule.field)
    missing = value in (None, "", [], {})

    if rule.kind == "missing":
        return missing
    if rule.kind == "present":
        return not missing
    if rule.kind == "regex_any":
        text = _as_text(value)
        return any(_compiled(p).search(text) for p in rule.patterns)
    if rule.kind == "any_of":
        return bool(matches_any(_as_text(value), rule.values))
    if rule.kind == "country_blocked":
        code = str(value or "").upper()
        if blocked_countries and code in blocked_countries:
            return True
        if allowed_countries is not None:
            # Unknown country is not allowed. Guessing is the expensive direction.
            return code not in allowed_countries
        return False
    if rule.kind == "suppressed":
        if is_suppressed is None or missing:
            return False
        kind = "linkedin" if "linkedin" in rule.field else "email"
        return is_suppressed(kind, _as_text(value))
    return False


def excluded_title(role: Role, profile: dict[str, Any]) -> str:
    """`icp.title_excludes` is a filter, not a comment. This applies it.

    Returns the matched phrase, or "" when the title is acceptable.
    """
    excludes = [str(v).lower() for v in (role.icp.get("title_excludes") or [])]
    if not excludes:
        return ""
    text = " ".join(
        str(profile.get(k) or "") for k in ("title", "headline")
    )
    hits = matches_any(text, excludes)
    return hits[0] if hits else ""


def score_profile(
    role: Role,
    profile: dict[str, Any],
    is_suppressed: Callable[[str, str], bool] | None = None,
    blocked_countries: set[str] | None = None,
    allowed_countries: set[str] | None = None,
) -> ScoreResult:
    bad_title = excluded_title(role, profile)
    if bad_title:
        return ScoreResult(
            score=0.0,
            disqualified=True,
            disqualifier="icp_title_excluded",
            reason=f"title matches icp.title_excludes entry {bad_title!r}",
        )

    for rule in role.disqualifiers:
        if evaluate_disqualifier(
            rule, profile, is_suppressed, blocked_countries, allowed_countries
        ):
            return ScoreResult(
                score=0.0,
                disqualified=True,
                disqualifier=rule.key,
                reason=rule.reason,
            )

    results: list[SignalResult] = []
    missing_fields: list[str] = []
    positive_total = sum(s.weight for s in role.signals if s.weight > 0) or 1.0
    running = 0.0

    for signal in role.signals:
        strength, detail, missing = evaluate_signal(signal, profile)
        contribution = signal.weight * strength / positive_total
        running += contribution
        results.append(
            SignalResult(
                key=signal.key,
                weight=signal.weight,
                strength=strength,
                contribution=contribution,
                detail=detail,
            )
        )
        if missing and signal.field not in missing_fields:
            missing_fields.append(signal.field)

    return ScoreResult(
        score=clamp(running),
        signals=results,
        missing_fields=missing_fields,
    )


def route(score: ScoreResult, settings_scoring: dict[str, Any]) -> str:
    """Which stage a scored candidate lands in."""
    if score.disqualified:
        return "rejected"
    reject_below = float(settings_scoring.get("auto_reject_below", 0.45))
    approve_above = float(settings_scoring.get("auto_approve_above", 0.80))
    require_review = bool(settings_scoring.get("require_hand_review", True))
    if score.score < reject_below:
        return "rejected"
    if score.score >= approve_above and not require_review:
        return "approved"
    return "review"
