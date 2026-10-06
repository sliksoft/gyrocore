"""Before/after verification result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ConvergenceStatus = Literal[
    "IMPROVING",
    "CONVERGED",
    "REGRESSED",
    "INCOMPARABLE",
    "INSUFFICIENT_EVIDENCE",
]


@dataclass
class FlightSnapshot:
    """Comparable measurement bundle extracted from GyroCore results."""

    craft_name: str | None = None
    target: str | None = None
    betaflight_version: str | None = None
    pid_profile: int | None = None
    sample_rate_hz: float | None = None
    quality_score: float | None = None
    noise_floor_db: dict[str, float] = field(default_factory=dict)
    resonance_severity: float | None = None
    saturation_fraction: float | None = None
    system_id_quality: str | None = None
    bandwidth_hz: dict[str, float] = field(default_factory=dict)
    mean_coherence: dict[str, float] = field(default_factory=dict)
    throttle_min: float | None = None
    throttle_max: float | None = None
    tune_values: dict[str, float] = field(default_factory=dict)
    peaks_hz: list[float] = field(default_factory=list)


@dataclass
class VerificationResult:
    comparable: bool
    reasons: list[str]
    improved_metrics: list[str]
    degraded_metrics: list[str]
    unchanged_metrics: list[str]
    confidence: str
    overall_status: ConvergenceStatus
    evidence: dict[str, Any]
    rollback_advisory: bool = False
    similarity_score: float | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    actionable: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["actionable"] = False
        d["auto_rollback"] = False
        d["rollback_cli"] = None
        return d
