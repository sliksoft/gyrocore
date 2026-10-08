"""Structured filter-evidence results (non-actionable)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class FlightSegment:
    start_index: int
    end_index: int
    duration_seconds: float
    average_throttle: float
    min_throttle: float
    max_throttle: float
    kind: str = "steady"  # steady | sweep | entire


@dataclass
class SpectralPeak:
    frequency_hz: float
    magnitude_db: float
    prominence_db: float
    peak_type: str  # frame_resonance | motor_harmonic | electrical | unknown


@dataclass
class FilterCandidate:
    """Non-actionable filter candidate — never authorized CLI."""

    actionable: bool = False
    gyro_lpf1_hz: float | None = None
    dterm_lpf1_hz: float | None = None
    dynamic_lowpass_recommended: bool | None = None
    rationale: str = ""
    settings: dict[str, float] = field(default_factory=dict)


@dataclass
class GroupDelayEstimate:
    reference_hz: float
    gyro_total_ms: float
    dterm_total_ms: float
    gyro_budget_ms: float
    dterm_budget_ms: float
    gyro_over_budget: bool
    dterm_over_budget: bool
    filters: list[dict[str, Any]] = field(default_factory=list)
    proposed_gyro_total_ms: float | None = None
    proposed_dterm_total_ms: float | None = None
    warning: str | None = None


@dataclass
class FilterEvidenceResult:
    selected_segments: list[FlightSegment]
    noise_floor_db: dict[str, float]
    overall_noise_level: str  # low | medium | high | unknown
    peaks: list[SpectralPeak]
    throttle_dependent_noise: dict[str, Any]
    current_filter_state: dict[str, Any]
    filter_candidate: FilterCandidate
    current_group_delay: GroupDelayEstimate | None
    proposed_group_delay: GroupDelayEstimate | None
    confidence: str
    warnings: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    actionable: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["actionable"] = False
        d["filter_candidate"]["actionable"] = False
        return d
