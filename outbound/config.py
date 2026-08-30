"""Load and validate settings and role files.

Settings live in `config/settings.toml`. Roles live in `config/roles/*.toml`.
Secrets never live in either; they come from the environment or `.env`.
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
ROLES_DIR = CONFIG_DIR / "roles"

PLACEHOLDER = re.compile(r"CHANGEME|NEEDS_PETER", re.I)

VALID_SIGNAL_KINDS = {
    "any_of",
    "none_of",
    "regex_any",
    "range",
    "min_value",
    "max_value",
    "present",
    "missing",
}
VALID_DISQUALIFIER_KINDS = {
    "missing",
    "present",
    "country_blocked",
    "suppressed",
    "regex_any",
    "any_of",
}


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"missing file: {path}")
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc


def load_dotenv(path: Path | None = None) -> dict[str, str]:
    """Read `.env` into a dict. Does not overwrite a variable already set.

    Deliberately small: `KEY=value`, `#` comments, optional `export `, and
    optional surrounding quotes. No interpolation.
    """
    env_path = path or (REPO_ROOT / ".env")
    loaded: dict[str, str] = {}
    if not env_path.exists():
        return loaded
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if not key:
            continue
        loaded[key] = value
        os.environ.setdefault(key, value)
    return loaded


def secret(name: str, required: bool = False) -> str:
    """Read a secret from the environment. Never from a config file."""
    value = os.environ.get(name, "").strip()
    if required and not value:
        from .errors import CredentialError

        raise CredentialError(
            f"{name} is not set. Put it in .env or export it. See .env.example."
        )
    return value


@dataclass(frozen=True)
class Signal:
    key: str
    weight: float
    kind: str
    field: str
    values: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    soft_min: float | None = None
    soft_max: float | None = None

    @property
    def is_penalty(self) -> bool:
        return self.weight < 0


@dataclass(frozen=True)
class Disqualifier:
    key: str
    kind: str
    field: str
    reason: str
    values: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class Search:
    name: str
    titles: tuple[str, ...] = ()
    geo: tuple[str, ...] = ()
    headcount: tuple[str, ...] = ()
    seniority: tuple[str, ...] = ()
    keywords: str = ""
    target: int = 200


@dataclass
class Role:
    key: str
    title: str
    status: str
    seats: int
    seniority: str
    employment: str
    comp: str
    comp_in_email: bool
    jd_url: str
    one_liner: str
    sender: str
    template_dir: str
    daily_cap: int
    target_list_size: int
    icp: dict[str, Any] = field(default_factory=dict)
    signals: list[Signal] = field(default_factory=list)
    disqualifiers: list[Disqualifier] = field(default_factory=list)
    searches: list[Search] = field(default_factory=list)
    booking_questions: list[str] = field(default_factory=list)
    path: Path | None = None
    comp_confidence: str = "unknown"

    @property
    def is_live(self) -> bool:
        return self.status == "live"

    def placeholders(self) -> list[str]:
        """Fields still holding CHANGEME or NEEDS_PETER. Blocks sending."""
        found = []
        for name in ("comp", "jd_url", "title", "one_liner"):
            value = getattr(self, name, "")
            if isinstance(value, str) and PLACEHOLDER.search(value):
                found.append(f"role.{name} = {value!r}")
        return found


@dataclass
class Settings:
    raw: dict[str, Any]
    path: Path | None = None

    def section(self, name: str) -> dict[str, Any]:
        value = self.raw.get(name)
        if not isinstance(value, dict):
            raise ConfigError(f"settings is missing the [{name}] section")
        return value

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # Convenience accessors used all over the codebase.
    @property
    def db_path(self) -> Path:
        return REPO_ROOT / str(self.get("storage.db_path", "data/outbound.db"))

    @property
    def outbox_dir(self) -> Path:
        return REPO_ROOT / str(self.get("storage.outbox_dir", "data/outbox"))

    @property
    def export_dir(self) -> Path:
        return REPO_ROOT / str(self.get("storage.export_dir", "data/exports"))

    def placeholders(self) -> list[str]:
        found: list[str] = []

        def walk(node: Any, trail: str) -> None:
            if isinstance(node, dict):
                for key, value in node.items():
                    walk(value, f"{trail}.{key}" if trail else key)
            elif isinstance(node, str) and PLACEHOLDER.search(node):
                found.append(f"{trail} = {node!r}")

        walk(self.raw, "")
        return found


def _as_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


def _parse_signal(item: dict[str, Any], role_key: str, index: int) -> Signal:
    key = str(item.get("key") or f"signal_{index}")
    kind = str(item.get("kind") or "").strip()
    if kind not in VALID_SIGNAL_KINDS:
        raise ConfigError(
            f"{role_key}: signal {key!r} has kind {kind!r}. "
            f"Valid kinds: {', '.join(sorted(VALID_SIGNAL_KINDS))}"
        )
    field_name = str(item.get("field") or "").strip()
    if not field_name:
        raise ConfigError(f"{role_key}: signal {key!r} has no field")
    patterns = _as_tuple(item.get("patterns"))
    for pattern in patterns:
        try:
            re.compile(pattern, re.I)
        except re.error as exc:
            raise ConfigError(
                f"{role_key}: signal {key!r} pattern {pattern!r} is not a valid regex: {exc}"
            ) from exc
    if kind == "regex_any" and not patterns:
        raise ConfigError(f"{role_key}: signal {key!r} is regex_any with no patterns")
    values = _as_tuple(item.get("values"))
    if kind in {"any_of", "none_of"} and not values:
        raise ConfigError(f"{role_key}: signal {key!r} is {kind} with no values")
    return Signal(
        key=key,
        weight=float(item.get("weight", 0.0)),
        kind=kind,
        field=field_name,
        values=tuple(v.lower() for v in values),
        patterns=patterns,
        minimum=_maybe_float(item.get("min")),
        maximum=_maybe_float(item.get("max")),
        soft_min=_maybe_float(item.get("soft_min")),
        soft_max=_maybe_float(item.get("soft_max")),
    )


def _maybe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_disqualifier(item: dict[str, Any], role_key: str, index: int) -> Disqualifier:
    key = str(item.get("key") or f"disqualifier_{index}")
    kind = str(item.get("kind") or "").strip()
    if kind not in VALID_DISQUALIFIER_KINDS:
        raise ConfigError(
            f"{role_key}: disqualifier {key!r} has kind {kind!r}. "
            f"Valid kinds: {', '.join(sorted(VALID_DISQUALIFIER_KINDS))}"
        )
    patterns = _as_tuple(item.get("patterns"))
    for pattern in patterns:
        try:
            re.compile(pattern, re.I)
        except re.error as exc:
            raise ConfigError(
                f"{role_key}: disqualifier {key!r} pattern {pattern!r} is invalid: {exc}"
            ) from exc
    return Disqualifier(
        key=key,
        kind=kind,
        field=str(item.get("field") or ""),
        reason=str(item.get("reason") or "no reason given"),
        values=tuple(v.lower() for v in _as_tuple(item.get("values"))),
        patterns=patterns,
    )


def _booking_questions(data: dict[str, Any]) -> list[str]:
    """Read the screener questions.

    They live in `[booking] questions = [...]`. A bare `booking_questions`
    key placed after a table gets absorbed into that table by TOML, which is
    how the first version of these files shipped with no questions at all, so
    both older spellings are still accepted.
    """
    booking = data.get("booking")
    if isinstance(booking, dict) and booking.get("questions"):
        return [str(q) for q in booking["questions"]]
    role_block = data.get("role")
    if isinstance(role_block, dict) and role_block.get("booking_questions"):
        return [str(q) for q in role_block["booking_questions"]]
    return [str(q) for q in data.get("booking_questions", []) or []]


def validate_comp_gate(role: "Role", where: str) -> None:
    """The comp-confidence gate. Runs at parse time AND after settings
    overrides, because status, comp_confidence and comp_in_email are all
    overridable and a settings.toml that flips a draft role live (or claims
    high confidence for a guess) must not slip a guessed salary into email 1.
    An email cannot be recalled and the band is the first thing a senior
    operator reads, so a wrong number is a retraction to a named person we
    were trying to impress.
    """
    if role.comp_confidence not in {"high", "medium", "low", "unknown"}:
        raise ConfigError(
            f"{where}: role.comp_confidence is {role.comp_confidence!r}. "
            f"Use high, medium, low or unknown. It comes from docs/COMP.md."
        )
    if role.is_live and role.comp_in_email and role.comp_confidence != "high":
        raise ConfigError(
            f"{where}: role is live and puts comp in email 1, but "
            f"comp_confidence is {role.comp_confidence!r}. Only a band "
            f"sourced from a document Peter wrote may be emailed. Get the "
            f"number, or set status = \"draft\"."
        )


def load_role(path: Path) -> Role:
    data = _read_toml(path)
    block = data.get("role")
    if not isinstance(block, dict):
        raise ConfigError(f"{path}: missing the [role] section")
    key = str(block.get("key") or path.stem)
    role = Role(
        key=key,
        title=str(block.get("title") or key),
        status=str(block.get("status") or "draft").lower(),
        seats=int(block.get("seats", 1)),
        seniority=str(block.get("seniority") or ""),
        employment=str(block.get("employment") or ""),
        comp=str(block.get("comp") or "NEEDS_PETER"),
        comp_in_email=bool(block.get("comp_in_email", True)),
        comp_confidence=str(block.get("comp_confidence") or "unknown").lower(),
        jd_url=str(block.get("jd_url") or ""),
        one_liner=str(block.get("one_liner") or ""),
        sender=str(block.get("sender") or "recruiting"),
        template_dir=str(block.get("template_dir") or key),
        daily_cap=int(block.get("daily_cap", 18)),
        target_list_size=int(block.get("target_list_size", 300)),
        icp=data.get("icp") if isinstance(data.get("icp"), dict) else {},
        booking_questions=_booking_questions(data),
        path=path,
    )
    if role.status not in {"live", "draft", "paused", "closed"}:
        raise ConfigError(
            f"{path}: role.status is {role.status!r}. Use live, draft, paused or closed."
        )
    validate_comp_gate(role, str(path))
    role.signals = [
        _parse_signal(item, key, i) for i, item in enumerate(data.get("signal", []))
    ]
    role.disqualifiers = [
        _parse_disqualifier(item, key, i)
        for i, item in enumerate(data.get("disqualifier", []))
    ]
    role.searches = [
        Search(
            name=str(item.get("name") or f"search_{i}"),
            titles=_as_tuple(item.get("titles")),
            geo=_as_tuple(item.get("geo")),
            headcount=_as_tuple(item.get("headcount")),
            seniority=_as_tuple(item.get("seniority")),
            keywords=str(item.get("keywords") or ""),
            target=int(item.get("target", 200)),
        )
        for i, item in enumerate(data.get("search", []))
    ]
    positive = sum(s.weight for s in role.signals if s.weight > 0)
    if positive <= 0:
        raise ConfigError(f"{path}: the role has no positive scoring signals")
    return role


def load_roles(roles_dir: Path | None = None) -> dict[str, Role]:
    directory = roles_dir or ROLES_DIR
    if not directory.exists():
        raise ConfigError(f"missing roles directory: {directory}")
    roles: dict[str, Role] = {}
    for path in sorted(directory.glob("*.toml")):
        role = load_role(path)
        if role.key in roles:
            raise ConfigError(
                f"two role files use key {role.key!r}: "
                f"{roles[role.key].path} and {path}"
            )
        roles[role.key] = role
    if not roles:
        raise ConfigError(f"no role files found in {directory}")
    return roles


def load_settings(path: Path | None = None) -> Settings:
    settings_path = path or (CONFIG_DIR / "settings.toml")
    if not settings_path.exists():
        example = CONFIG_DIR / "settings.example.toml"
        raise ConfigError(
            f"missing {settings_path}. Copy the example first:\n"
            f"    cp {example.relative_to(REPO_ROOT)} "
            f"{settings_path.relative_to(REPO_ROOT)}"
        )
    data = _read_toml(settings_path)
    for required in ("identity", "sending", "booking", "compliance", "scoring", "providers"):
        if required not in data:
            raise ConfigError(f"{settings_path} is missing the [{required}] section")
    return Settings(raw=data, path=settings_path)


OVERRIDABLE = {
    "title", "status", "comp", "jd_url", "one_liner", "sender", "daily_cap",
    "seats", "employment", "comp_in_email", "comp_confidence",
    "target_list_size", "template_dir",
}


def apply_overrides(roles: dict[str, Role], settings: "Settings") -> list[str]:
    """Let settings.toml override a few role fields.

    Comp changes, and it is the one field nobody wants in a committed file.
    Keep the role files generic and put the numbers in settings.toml, which
    is gitignored.

        [role_overrides.head-of-operations]
        comp    = "$180k to $220k"
        jd_url  = "https://example.com/roles/hoo"
    """
    applied: list[str] = []
    overrides = settings.get("role_overrides", {}) or {}
    if not isinstance(overrides, dict):
        raise ConfigError("[role_overrides] must be a table of role keys")
    for role_key, fields in overrides.items():
        if role_key not in roles:
            raise ConfigError(
                f"[role_overrides.{role_key}] refers to a role that does not exist. "
                f"Known roles: {', '.join(sorted(roles))}"
            )
        if not isinstance(fields, dict):
            raise ConfigError(f"[role_overrides.{role_key}] must be a table")
        for name, value in fields.items():
            if name not in OVERRIDABLE:
                raise ConfigError(
                    f"[role_overrides.{role_key}] cannot override {name!r}. "
                    f"Overridable: {', '.join(sorted(OVERRIDABLE))}"
                )
            current = getattr(roles[role_key], name)
            setattr(roles[role_key], name, type(current)(value) if current is not None else value)
            applied.append(f"{role_key}.{name}")
    return applied


def load_all(
    settings_path: Path | None = None, roles_dir: Path | None = None
) -> tuple["Settings", dict[str, Role]]:
    """The one entry point. Loads .env, settings and roles, applies overrides."""
    load_dotenv()
    settings = load_settings(settings_path)
    roles = load_roles(roles_dir)
    apply_overrides(roles, settings)
    # Overrides can flip status/comp_confidence/comp_in_email, so re-run the
    # comp gate on the final state, not just the on-disk state.
    for key, role in roles.items():
        validate_comp_gate(role, f"[role_overrides.{key}] (after settings)")
    return settings, roles


def get_role(roles: dict[str, Role], key: str) -> Role:
    if key in roles:
        return roles[key]
    matches = [k for k in roles if k.startswith(key)]
    if len(matches) == 1:
        return roles[matches[0]]
    raise ConfigError(
        f"unknown role {key!r}. Known roles: {', '.join(sorted(roles))}"
    )
