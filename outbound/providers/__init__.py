"""Provider adapters.

Seven stages, seven interfaces. Every adapter is a small class with one job
and no knowledge of the rest of the pipeline. `dryrun` implements them all
with no network, which is why the whole thing runs out of the box.

Register a new adapter by adding it to REGISTRY at the bottom of this file.
"""

from __future__ import annotations

from typing import Any, Protocol

from ..errors import ConfigError


class SearchProvider(Protocol):
    name: str

    def search(self, spec: dict[str, Any], limit: int) -> list[dict[str, Any]]:
        """Return raw profile payloads. Normalisation happens elsewhere."""


class EnrichProvider(Protocol):
    name: str

    def find_email(self, candidate: dict[str, Any]) -> list[dict[str, Any]]:
        """Return [{address, confidence, source}] best first. May be empty."""


class VerifyProvider(Protocol):
    name: str

    def verify(self, address: str) -> str:
        """Return valid, invalid, risky, catch_all or unknown."""


class EvaluateProvider(Protocol):
    name: str

    def evaluate(self, brief: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
        """Judge one profile against a role brief.

        Returns a dict with:
          fit               float 0..1, how well the profile matches
          verdict           "strong", "maybe" or "weak"
          reasons           list[str], short, the evidence for the verdict
          personal_note     str, the one specific detail for line one of email
          disqualify        bool, a hard non-fit the score cannot see
          disqualify_reason str, why, when disqualify is true
        """


class SendProvider(Protocol):
    name: str

    def send(self, message: dict[str, Any]) -> str:
        """Send one message. Return a provider id."""


class RepliesProvider(Protocol):
    name: str

    def fetch_replies(self, since: str | None = None) -> list[dict[str, Any]]:
        """Return [{from_address, subject, body, date}] for inbound mail."""


class BookingProvider(Protocol):
    name: str

    def list_bookings(self, since: str | None = None) -> list[dict[str, Any]]:
        """Return [{provider_id, attendee_name, attendee_email, start_at, answers}]."""

    def cancel(self, provider_id: str, reason: str) -> bool:
        """Cancel one booking."""


def build(kind: str, name: str, settings: Any) -> Any:
    """Instantiate one adapter by name."""
    from . import (  # noqa: F401  imported for side effect of registration
        apify,
        apollo,
        calcom,
        calendly,
        anthropic_eval,
        dryrun,
        findymail,
        imap_replies,
        instantly,
        manual,
        millionverifier,
        neverbounce,
        prospeo,
        rocketreach,
        smartlead,
        smtp_sender,
        zerobounce,
    )

    table = REGISTRY.get(kind)
    if table is None:
        raise ConfigError(f"unknown provider stage {kind!r}")
    if name in ("none", "", None):
        return None
    factory = table.get(name)
    if factory is None:
        raise ConfigError(
            f"unknown {kind} provider {name!r}. "
            f"Available: {', '.join(sorted(table)) or 'none'}"
        )
    return factory(settings)


REGISTRY: dict[str, dict[str, Any]] = {
    "search": {},
    "enrich": {},
    "verify": {},
    "evaluate": {},
    "send": {},
    "booking": {},
    "replies": {},
}


def register(kind: str, name: str):
    """Decorator used by each adapter module."""

    def wrap(factory):
        REGISTRY.setdefault(kind, {})[name] = factory
        return factory

    return wrap
