"""Typed views over donor mechanical / tuning_output_safety dicts.

Algorithms remain in AeroTuner until later WUs. These types make the
actionable-CLI invariant explicit without rewriting gate logic.

Donor sources:
- ``backend.services.mechanical_safety_gate.build_mechanical_safety_gate``
- ``backend.routes.analyze._build_tuning_output_safety``
- ``backend.services.tuning_output_safety``
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


class TuningOutputSafetyStatus(str, Enum):
    """
    Final tuning output safety status values observed on the production path.

    Donor statuses include at least: actionable, limited, blocked, plus
    fail-safe / diagnostic variants.
    """

    ACTIONABLE = "actionable"
    LIMITED = "limited"
    BLOCKED = "blocked"
    DIAGNOSTIC = "diagnostic"
    UNKNOWN = "unknown"
    SNAPSHOT_PARTIAL = "snapshot_partial"

    @classmethod
    def from_legacy(cls, value: Any) -> TuningOutputSafetyStatus:
        text = str(value or "").strip().lower()
        for member in cls:
            if member.value == text:
                return member
        if text in {"diagnostic_only"}:
            return cls.DIAGNOSTIC
        if text in {"actionable_warning"}:
            return cls.ACTIONABLE
        return cls.UNKNOWN


@dataclass(frozen=True)
class MechanicalSafetyView:
    """Minimal mechanical gate projection (legacy-dict compatible)."""

    mechanical_block: bool = False
    mechanical_limited: bool = False
    mechanical_caution: bool = False
    mechanical_outcome: str = ""
    status: str = ""
    reasons: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    limited_reasons: tuple[str, ...] = ()
    raw: Mapping[str, Any] | None = None

    @classmethod
    def from_legacy(cls, payload: Mapping[str, Any] | None) -> MechanicalSafetyView:
        data = dict(payload) if isinstance(payload, Mapping) else {}
        return cls(
            mechanical_block=bool(data.get("mechanical_block")),
            mechanical_limited=bool(data.get("mechanical_limited")),
            mechanical_caution=bool(data.get("mechanical_caution")),
            mechanical_outcome=str(data.get("mechanical_outcome") or ""),
            status=str(
                data.get("severity")
                or data.get("recommended_action")
                or data.get("mechanical_outcome")
                or data.get("status")
                or ""
            ),
            reasons=_string_tuple(data.get("reasons")),
            blocking_reasons=_string_tuple(data.get("blocking_reasons")),
            limited_reasons=_string_tuple(data.get("limited_reasons")),
            raw=data or None,
        )


@dataclass(frozen=True)
class TuningOutputSafetyView:
    """
    Final output-safety gate view.

    Invariant (enforced by helpers, not algorithms):
    actionable CLI exposure requires ``cli_actionable is True`` and a present status.
    """

    status: TuningOutputSafetyStatus = TuningOutputSafetyStatus.UNKNOWN
    cli_actionable: bool | None = None
    cli_availability: str = ""
    present: bool = False
    blocking_reasons: tuple[str, ...] = ()
    hard_block_reasons: tuple[str, ...] = ()
    diagnostic_reasons: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    mechanical: MechanicalSafetyView = MechanicalSafetyView()
    raw: Mapping[str, Any] | None = None

    @classmethod
    def from_legacy(cls, payload: Mapping[str, Any] | None) -> TuningOutputSafetyView:
        data = dict(payload) if isinstance(payload, Mapping) else {}
        present = bool(data) or bool(data.get("present"))
        mech_raw = data.get("mechanical")
        if not isinstance(mech_raw, Mapping):
            mech_raw = None
        cli_actionable = data.get("cli_actionable")
        if cli_actionable is not None:
            cli_actionable = bool(cli_actionable)
        return cls(
            status=TuningOutputSafetyStatus.from_legacy(data.get("status")),
            cli_actionable=cli_actionable,
            cli_availability=str(data.get("cli_availability") or ""),
            present=present,
            blocking_reasons=_string_tuple(data.get("blocking_reasons")),
            hard_block_reasons=_string_tuple(data.get("hard_block_reasons")),
            diagnostic_reasons=_string_tuple(data.get("diagnostic_reasons")),
            reasons=_string_tuple(data.get("reasons")),
            mechanical=MechanicalSafetyView.from_legacy(mech_raw),
            raw=data or None,
        )

    def allows_actionable_cli(self) -> bool:
        return actionable_cli_allowed(self)


def actionable_cli_allowed(safety: TuningOutputSafetyView | Mapping[str, Any] | None) -> bool:
    """
    Return True only when final tuning output safety explicitly allows paste-ready CLI.

    Missing safety fails closed.
    """
    if isinstance(safety, TuningOutputSafetyView):
        view = safety
    elif isinstance(safety, Mapping):
        view = TuningOutputSafetyView.from_legacy(safety)
    else:
        return False
    if not view.present:
        return False
    if view.cli_actionable is not True:
        return False
    if view.status in {
        TuningOutputSafetyStatus.BLOCKED,
        TuningOutputSafetyStatus.DIAGNOSTIC,
        TuningOutputSafetyStatus.UNKNOWN,
    }:
        return False
    return True


def _string_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(x).strip() for x in value if str(x).strip())
