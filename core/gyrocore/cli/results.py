"""Authorized / preview / denial CLI results. Tokens block unauthorized construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from gyrocore.cli.settings import FIRMWARE_CLI_PROVENANCE
from gyrocore.safety.results import FinalSafeTuneResult
from gyrocore.safety.types import SafetyCheck, StageBypassError, _require_token

_ACTIONABLE_TOKEN = object()
_PREVIEW_TOKEN = object()
_DENIAL_TOKEN = object()

KIND_ACTIONABLE = "gyrocore_actionable_tune_bundle"
KIND_PREVIEW = "gyrocore_tune_cli_preview"
KIND_DENIAL = "gyrocore_tune_cli_denial"


@dataclass(frozen=True)
class ActionableTuneBundle:
    """Paste-ready apply/rollback pair. Constructible only via ``authorize_cli``."""

    apply_cli: str
    rollback_cli: str
    source_profile: int
    target_profile: int
    profile_command_required: bool
    current_values: Mapping[str, int]
    target_values: Mapping[str, int]
    changed_settings: Mapping[str, int]
    unchanged_settings: tuple[str, ...]
    warnings: tuple[str, ...]
    verification_expectations: Mapping[str, Any]
    safety_provenance: Mapping[str, Any]
    firmware_provenance: Mapping[str, Any]
    bundle_id: str
    checks: tuple[SafetyCheck, ...]
    final: FinalSafeTuneResult
    _token: object = field(default=None, repr=False, compare=False)

    kind: str = field(default=KIND_ACTIONABLE, init=False)
    authorized: bool = field(default=True, init=False)
    actionable: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        _require_token(self._token, _ACTIONABLE_TOKEN, "ActionableTuneBundle")
        if not isinstance(self.final, FinalSafeTuneResult):
            raise StageBypassError("ActionableTuneBundle requires FinalSafeTuneResult")
        object.__setattr__(self, "kind", KIND_ACTIONABLE)
        object.__setattr__(self, "authorized", True)
        object.__setattr__(self, "actionable", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "authorized": True,
            "actionable": True,
            "apply_cli": self.apply_cli,
            "rollback_cli": self.rollback_cli,
            "source_profile": self.source_profile,
            "target_profile": self.target_profile,
            "profile_command_required": self.profile_command_required,
            "current_values": dict(self.current_values),
            "target_values": dict(self.target_values),
            "changed_settings": dict(self.changed_settings),
            "unchanged_settings": list(self.unchanged_settings),
            "warnings": list(self.warnings),
            "verification_expectations": dict(self.verification_expectations),
            "safety_provenance": dict(self.safety_provenance),
            "firmware_provenance": dict(self.firmware_provenance),
            "bundle_id": self.bundle_id,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass(frozen=True)
class TuneCliPreview:
    """WARN inspection output. Not paste-ready."""

    preview_cli: str
    reasons: tuple[str, ...]
    current_values: Mapping[str, int]
    target_values: Mapping[str, int]
    changed_settings: Mapping[str, int]
    final: FinalSafeTuneResult
    _token: object = field(default=None, repr=False, compare=False)

    kind: str = field(default=KIND_PREVIEW, init=False)
    authorized: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_token(self._token, _PREVIEW_TOKEN, "TuneCliPreview")
        object.__setattr__(self, "kind", KIND_PREVIEW)
        object.__setattr__(self, "authorized", False)
        object.__setattr__(self, "actionable", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "authorized": False,
            "actionable": False,
            "preview_cli": self.preview_cli,
            "reasons": list(self.reasons),
            "current_values": dict(self.current_values),
            "target_values": dict(self.target_values),
            "changed_settings": dict(self.changed_settings),
            "notice": "WARN preview only. Not paste-ready. No save.",
        }


@dataclass(frozen=True)
class TuneCliDenial:
    """BLOCK / fail-closed denial. No apply/preview CLI fields."""

    blocked_reasons: tuple[str, ...]
    diagnostic_values: Mapping[str, Any]
    final_status: str
    _token: object = field(default=None, repr=False, compare=False)

    kind: str = field(default=KIND_DENIAL, init=False)
    authorized: bool = field(default=False, init=False)
    actionable: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_token(self._token, _DENIAL_TOKEN, "TuneCliDenial")
        object.__setattr__(self, "kind", KIND_DENIAL)
        object.__setattr__(self, "authorized", False)
        object.__setattr__(self, "actionable", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "authorized": False,
            "actionable": False,
            "blocked_reasons": list(self.blocked_reasons),
            "diagnostic_values": dict(self.diagnostic_values),
            "final_status": self.final_status,
            "notice": "BLOCK: diagnostic data only. No apply CLI.",
        }


@dataclass(frozen=True)
class CliAuthorizationResult:
    status: str
    bundle: ActionableTuneBundle | None = None
    preview: TuneCliPreview | None = None
    denial: TuneCliDenial | None = None

    @property
    def authorized(self) -> bool:
        return self.status == "authorized" and self.bundle is not None and self.bundle.authorized

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "authorized": self.authorized,
            "bundle": self.bundle.to_dict() if self.bundle else None,
            "preview": self.preview.to_dict() if self.preview else None,
            "denial": self.denial.to_dict() if self.denial else None,
        }


def make_actionable_bundle(**kwargs: Any) -> ActionableTuneBundle:
    return ActionableTuneBundle(_token=_ACTIONABLE_TOKEN, **kwargs)


def make_preview(**kwargs: Any) -> TuneCliPreview:
    return TuneCliPreview(_token=_PREVIEW_TOKEN, **kwargs)


def make_denial(**kwargs: Any) -> TuneCliDenial:
    return TuneCliDenial(_token=_DENIAL_TOKEN, **kwargs)


__all__ = [
    "ActionableTuneBundle",
    "CliAuthorizationResult",
    "FIRMWARE_CLI_PROVENANCE",
    "KIND_ACTIONABLE",
    "KIND_DENIAL",
    "KIND_PREVIEW",
    "TuneCliDenial",
    "TuneCliPreview",
    "make_actionable_bundle",
    "make_denial",
    "make_preview",
]
