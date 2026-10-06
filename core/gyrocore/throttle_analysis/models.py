"""Throttle analysis structured results."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class ThrottleBandSpectrum:
    throttle_min: float
    throttle_max: float
    sample_count: int
    usable: bool
    noise_floor_db: list[float | None] = field(default_factory=list)
    peaks: list[dict[str, Any]] = field(default_factory=list)
    spectrum: dict[str, Any] = field(default_factory=dict)  # frequencies/magnitudes (roll)


@dataclass
class ThrottleSpectrogramResult:
    bands: list[ThrottleBandSpectrum]
    num_bands: int
    min_samples_per_band: int
    bands_with_data: int
    contiguous_run_policy: str = "only_contiguous_runs_fft"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ThrottleBandResponse:
    throttle_min: float
    throttle_max: float
    sample_count: int
    usable: bool
    bandwidth_hz: float | None = None
    mean_coherence: float | None = None
    phase_proxy_deg: float | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class ThrottleResponseAnalysis:
    throttle_bands: list[ThrottleBandResponse]
    usable_bands: int
    response_metrics: dict[str, Any]
    bandwidth_evidence: dict[str, Any]
    phase_coherence_evidence: dict[str, Any]
    high_throttle_degradation: bool
    confidence: str
    warnings: list[str]
    tpa_advisory: str  # enum-like advisory, never a TPA value
    provenance: dict[str, Any] = field(default_factory=dict)
    actionable: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["actionable"] = False
        d["tpa_value"] = None
        d["tpa_cli"] = None
        return d
