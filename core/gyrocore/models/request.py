"""Explicit Core analysis request boundary.

Justified by donor contracts currently hidden in AeroTuner sessions:

- ``session["parsed"]["samples"]`` / BBL path via upload+decode
- ``uploaded_cli_dump_text`` / ``parsed["tuning"]``
- ``firmware`` meta from headers/CLI
- ``user_inputs.hardware`` + style/goals (full_analyze_hardware_gate)
- flight / embedded-log selection on analyze start

No ``session_id``, job IDs, ownership, or HTTP types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..errors import InvalidInputError


@dataclass(frozen=True)
class FirmwareContext:
    """
    Firmware / board metadata used for Betaflight support classification.

    Donor sources: blackbox headers + CLI meta
    (``backend.services.firmware_metadata``, ``betaflight_version_support``).
    """

    firmware: str | None = None
    board_name: str | None = None
    manufacturer_id: str | None = None
    extra: Mapping[str, str] = field(default_factory=dict)

    def as_legacy_meta(self) -> dict[str, str]:
        out: dict[str, str] = {}
        if self.firmware:
            out["firmware"] = self.firmware
        if self.board_name:
            out["board_name"] = self.board_name
        if self.manufacturer_id:
            out["manufacturer_id"] = self.manufacturer_id
        for key, value in self.extra.items():
            if value is not None and str(value).strip():
                out[str(key)] = str(value)
        return out


@dataclass(frozen=True)
class HardwareContext:
    """
    User-confirmed hardware inputs required by the donor full-analyze gate.

    Inner payload stays Mapping-compatible with ``user_inputs["hardware"]``.
    """

    payload: Mapping[str, Any] = field(default_factory=dict)

    def as_legacy_hardware(self) -> dict[str, Any]:
        return dict(self.payload)


@dataclass(frozen=True)
class FlightSelection:
    """Explicit flight / embedded-log selection (replaces session-side mutations)."""

    selected_flight_index: int | None = None
    selected_embedded_log_index: int | None = None
    flight_selection_mode: str = "auto"


@dataclass(frozen=True)
class AnalyzeOptions:
    """
    Analysis/tuning options that are not craft identity.

    ``ai_enabled`` defaults False to match WU0 deterministic oracle policy.
    """

    ai_enabled: bool = False
    style: str | None = None
    goals: tuple[str, ...] = field(default_factory=tuple)
    goal_profile: str | None = None
    problems: tuple[str, ...] = field(default_factory=tuple)
    # Escape hatch for additional wizard fields without schema explosion.
    extra_user_inputs: Mapping[str, Any] = field(default_factory=dict)

    def as_legacy_user_inputs(
        self,
        *,
        hardware: HardwareContext | None = None,
    ) -> dict[str, Any]:
        out: dict[str, Any] = dict(self.extra_user_inputs)
        if hardware is not None:
            out["hardware"] = hardware.as_legacy_hardware()
        if self.style is not None:
            out["style"] = self.style
        if self.goals:
            out["goals"] = list(self.goals)
        if self.goal_profile is not None:
            out["goal_profile"] = self.goal_profile
        if self.problems:
            out["problems"] = list(self.problems)
        return out


@dataclass(frozen=True)
class AnalyzeRequest:
    """
    Future-compatible Core analyze request.

    Exactly one of ``bbl_path`` or ``samples`` should be provided for a full
    analysis once the engine is migrated. WU1 only validates the boundary.
    """

    bbl_path: str | None = None
    samples: Sequence[Mapping[str, Any]] | None = None
    cli_text: str | None = None
    firmware: FirmwareContext = field(default_factory=FirmwareContext)
    hardware: HardwareContext = field(default_factory=HardwareContext)
    flight: FlightSelection = field(default_factory=FlightSelection)
    options: AnalyzeOptions = field(default_factory=AnalyzeOptions)

    def __post_init__(self) -> None:
        has_bbl = bool(self.bbl_path and str(self.bbl_path).strip())
        has_samples = self.samples is not None
        if has_bbl and has_samples:
            raise InvalidInputError(
                "Provide either bbl_path or samples, not both"
            )
        if not has_bbl and not has_samples:
            raise InvalidInputError(
                "AnalyzeRequest requires bbl_path or samples"
            )
        if has_bbl:
            object.__setattr__(self, "bbl_path", str(self.bbl_path).strip())

    @property
    def has_cli(self) -> bool:
        return bool(self.cli_text and str(self.cli_text).strip())

    def legacy_user_inputs(self) -> dict[str, Any]:
        return self.options.as_legacy_user_inputs(hardware=self.hardware)
