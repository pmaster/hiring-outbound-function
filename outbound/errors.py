"""Errors. One class per thing that can go wrong, so the CLI can report well."""


class OutboundError(Exception):
    """Base class. The CLI catches this and prints the message without a trace."""


class ConfigError(OutboundError):
    """Settings or a role file is missing, unreadable or invalid."""


class ProviderError(OutboundError):
    """A provider call failed."""


class CredentialError(ProviderError):
    """A provider needs an API key that is not set."""


class ComplianceError(OutboundError):
    """The action would break a compliance rule. Never catch and continue."""


class SafetyStop(OutboundError):
    """A guard rail stopped the run. Warm up, caps, draft roles, dry run flags."""
