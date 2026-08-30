"""Anthropic evaluator. Judges one profile against a role brief with a model.

Standard library only: the call is one JSON POST through httpjson, the same
path every other adapter uses. It returns the structured verdict documented in
providers.EvaluateProvider.

The model is asked for strict JSON and nothing else. Models still wrap it in
prose or a code fence sometimes, so the parser pulls the first JSON object out
rather than trusting the whole body to parse.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .. import httpjson
from ..config import secret
from ..errors import ProviderError
from ..evaluate import candidate_summary
from . import register

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM = (
    "You are a hiring screener for a small, fast trading firm. You judge one "
    "candidate profile against one role brief and return a strict JSON verdict. "
    "Be skeptical and concrete. High intelligence is necessary but not "
    "sufficient: a strong pedigree with no relevant operating track is a maybe, "
    "not a strong. Reward a real track of building and running the thing the "
    "role needs. The personal_note is the single most specific true detail from "
    "THIS profile, one sentence, at most 28 words, plain English, no em dash, "
    "no flattery, written as the opening line of a cold email from the founder. "
    "Never invent a detail that is not in the profile. Return JSON only."
)

SCHEMA_HINT = (
    '{"fit": <0..1 float>, "verdict": "strong|maybe|weak", '
    '"reasons": ["short evidence", ...], '
    '"personal_note": "one specific sentence", '
    '"disqualify": <bool>, "disqualify_reason": "<why, or empty>"}'
)


class AnthropicEvaluate:
    name = "anthropic"

    def __init__(self, settings: Any):
        self.settings = settings
        section = settings.section("evaluation") if settings else {}
        self.model = str(section.get("model") or DEFAULT_MODEL)
        self.max_tokens = int(section.get("max_tokens") or 700)

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": secret("ANTHROPIC_API_KEY", required=True),
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

    def _prompt(self, brief: dict[str, Any], candidate: dict[str, Any]) -> str:
        evidence = candidate.get("_evidence") or []
        return (
            "ROLE BRIEF (JSON):\n"
            + json.dumps(brief, ensure_ascii=False, indent=2)
            + "\n\nCANDIDATE PROFILE:\n"
            + candidate_summary(candidate)
            + (
                "\n\nSIGNALS THE SCORER ALREADY MATCHED:\n- "
                + "\n- ".join(str(e) for e in evidence)
                if evidence else ""
            )
            + "\n\nReturn JSON only, exactly this shape:\n"
            + SCHEMA_HINT
        )

    def evaluate(self, brief: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        data = httpjson.post(
            API_URL,
            headers=self._headers(),
            body={
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": SYSTEM,
                "messages": [{"role": "user", "content": self._prompt(brief, candidate)}],
            },
        )
        text = _text_from_response(data)
        verdict = _parse_verdict(text)
        return _normalize(verdict)


def _text_from_response(data: Any) -> str:
    if not isinstance(data, dict):
        raise ProviderError("anthropic evaluate: unexpected response shape")
    blocks = data.get("content") or []
    parts = [b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise ProviderError("anthropic evaluate: empty response")
    return text


def _parse_verdict(text: str) -> dict[str, Any]:
    # Strip a ```json fence if present, then pull the first {...} object.
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start = text.find("{")
        end = text.rfind("}")
        candidate = text[start : end + 1] if start != -1 and end > start else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ProviderError(f"anthropic evaluate: could not parse JSON verdict: {exc}") from exc


def _normalize(v: dict[str, Any]) -> dict[str, Any]:
    try:
        fit = float(v.get("fit"))
    except (TypeError, ValueError):
        fit = 0.0
    fit = max(0.0, min(1.0, fit))
    verdict = str(v.get("verdict") or "").lower().strip()
    if verdict not in ("strong", "maybe", "weak"):
        verdict = "strong" if fit >= 0.7 else "weak" if fit < 0.45 else "maybe"
    reasons = v.get("reasons") or []
    if isinstance(reasons, str):
        reasons = [reasons]
    reasons = [str(r).strip() for r in reasons if str(r).strip()][:5]
    return {
        "fit": round(fit, 4),
        "verdict": verdict,
        "reasons": reasons,
        "personal_note": str(v.get("personal_note") or "").strip(),
        "disqualify": bool(v.get("disqualify")),
        "disqualify_reason": str(v.get("disqualify_reason") or "").strip(),
    }


register("evaluate", "anthropic")(AnthropicEvaluate)
