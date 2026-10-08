"""Analysis-validity gates for CHIRP system identification (GyroCore hardening).

These gates decide whether an identified transfer function is trustworthy
*as a measurement*. They are not PID / flight safety checks and they never
produce tuning output; any future tuning path still has to pass mechanical
safety -> safe tune / clamps -> final tuning_output_safety -> actionable CLI.

Upstream Betaflight has only one equivalent: ``computeAxisResult`` skips a
segment shorter than ``segmentSize``. The coherence threshold mirrors
``CROSSOVER_COHERENCE_MIN`` (0.5) and the coherence band mirrors
``computeMeanCoherence`` (5-100 Hz) from ``spectral_analysis.ts``; the other
thresholds are GyroCore choices, documented in
``docs/upstream/CHIRP_SYSTEM_ID_PARITY.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

import numpy as np

from .sample_rate import SampleRateEvidence, TimestampSpacing
from .system_id import CROSSOVER_COHERENCE_MIN, SXX_FLOOR, TransferFunction

MIN_WELCH_SEGMENTS = 4
MIN_EXCITATION_RMS = 5.0  # setpoint units (deg/s)
MAX_MISSING_SAMPLE_FRACTION = 0.01
USABLE_COHERENCE_MIN = CROSSOVER_COHERENCE_MIN
MIN_MEAN_BAND_COHERENCE = 0.6
MEAN_COHERENCE_BAND_HZ = (5.0, 100.0)
MIN_USABLE_BINS = 8
NYQUIST_GUARD_FRACTION = 0.9
DEFAULT_ANALYSIS_BAND_HZ = (5.0, 100.0)


class GateSeverity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"


@dataclass(frozen=True)
class QualityGate:
    code: str
    passed: bool
    severity: GateSeverity
    value: float | None
    threshold: float | None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


@dataclass(frozen=True)
class QualityReport:
    gates: tuple[QualityGate, ...]
    usable_mask: np.ndarray
    usable_range_hz: tuple[float, float] | None
    analysis_band_hz: tuple[float, float]
    mean_band_coherence: float | None
    input_rms: float

    @property
    def usable(self) -> bool:
        return all(g.passed for g in self.gates if g.severity is GateSeverity.BLOCKING)

    @property
    def failed(self) -> tuple[str, ...]:
        return tuple(g.code for g in self.gates if not g.passed and g.severity is GateSeverity.BLOCKING)

    @property
    def warnings(self) -> tuple[str, ...]:
        return tuple(g.code for g in self.gates if not g.passed and g.severity is GateSeverity.WARNING)

    def to_dict(self) -> dict[str, Any]:
        return {
            "usable": self.usable,
            "failed_gates": list(self.failed),
            "warning_gates": list(self.warnings),
            "gates": [g.to_dict() for g in self.gates],
            "usable_range_hz": list(self.usable_range_hz) if self.usable_range_hz else None,
            "usable_bin_count": int(self.usable_mask.sum()),
            "analysis_band_hz": list(self.analysis_band_hz),
            "mean_band_coherence": self.mean_band_coherence,
            "input_rms": self.input_rms,
        }


def _gate(code: str, ok: bool, value: float | None, threshold: float | None, detail: str = "", *, warn: bool = False) -> QualityGate:
    return QualityGate(code, bool(ok), GateSeverity.WARNING if warn else GateSeverity.BLOCKING, value, threshold, detail)


def pre_analysis_gates(
    *,
    sample_count: int,
    segment_size: int | None,
    rate: SampleRateEvidence,
    spacing: TimestampSpacing,
) -> list[QualityGate]:
    """Gates decidable before the FFT (sample count, rate, spacing)."""
    gates = [
        _gate(
            "invalid_sample_rate",
            rate.usable and rate.effective_rate_hz is not None and rate.effective_rate_hz > 0,
            rate.effective_rate_hz,
            None,
            rate.status.value,
        ),
        _gate(
            "non_uniform_sampling",
            spacing.uniform,
            spacing.uniform_fraction,
            0.9,
            "timestamp deltas outside +/-10% of the median",
        ),
        _gate(
            "excessive_gaps",
            spacing.missing_fraction <= MAX_MISSING_SAMPLE_FRACTION,
            spacing.missing_fraction,
            MAX_MISSING_SAMPLE_FRACTION,
            f"{spacing.gap_count} gaps, ~{spacing.missing_samples_estimate} samples missing",
        ),
        _gate("timestamp_gaps_present", spacing.gap_count == 0, float(spacing.gap_count), 0.0, warn=True),
        _gate("sample_rate_crosscheck", rate.status.value == "ok", rate.difference_percent, 5.0, rate.status.value, warn=True),
    ]
    if segment_size is not None:
        gates.append(
            _gate(
                "insufficient_samples",
                sample_count >= segment_size,
                float(sample_count),
                float(segment_size),
                "segment shorter than the Welch segment (upstream skips the axis)",
            )
        )
    return gates


def analysis_band(
    chirp_range_hz: tuple[float, float] | None, sample_rate_hz: float
) -> tuple[tuple[float, float], list[QualityGate]]:
    nyquist = sample_rate_hz / 2.0
    gates: list[QualityGate] = []
    if chirp_range_hz is None:
        lo, hi = DEFAULT_ANALYSIS_BAND_HZ
        gates.append(_gate("chirp_band_unknown_default_used", False, None, None, warn=True))
    else:
        lo, hi = chirp_range_hz
        if hi > NYQUIST_GUARD_FRACTION * nyquist:
            gates.append(_gate("chirp_band_near_nyquist", False, hi, NYQUIST_GUARD_FRACTION * nyquist, warn=True))
    hi = min(hi, NYQUIST_GUARD_FRACTION * nyquist)
    return (float(lo), float(hi)), gates


def post_analysis_report(
    *,
    gates: list[QualityGate],
    tf: TransferFunction | None,
    input_signal: np.ndarray,
    band_hz: tuple[float, float],
) -> QualityReport:
    """Add excitation / coherence / usable-range gates once H(f) is available."""
    x = np.asarray(input_signal, dtype=np.float64)
    rms = float(np.sqrt(np.mean((x - x.mean()) ** 2))) if x.size else 0.0
    gates = list(gates)
    gates.append(_gate("insufficient_excitation", rms >= MIN_EXCITATION_RMS, rms, MIN_EXCITATION_RMS, "setpoint RMS"))
    if tf is None:
        return QualityReport(tuple(gates), np.zeros(0, dtype=bool), None, band_hz, None, rms)

    gates.append(
        _gate(
            "insufficient_samples",
            tf.num_segments >= MIN_WELCH_SEGMENTS,
            float(tf.num_segments),
            float(MIN_WELCH_SEGMENTS),
            "too few Welch segments for a meaningful coherence estimate",
        )
    )
    f = tf.frequencies
    sxx_ok = tf.spectra.sxx >= SXX_FLOOR if tf.spectra is not None else np.isfinite(tf.magnitude_db)
    in_band = (f >= band_hz[0]) & (f <= band_hz[1]) & (f > 0) & (f < tf.sample_rate_hz / 2.0)
    coh_lo = max(MEAN_COHERENCE_BAND_HZ[0], band_hz[0])
    coh_hi = min(MEAN_COHERENCE_BAND_HZ[1], band_hz[1])
    if coh_hi <= coh_lo:
        coh_lo, coh_hi = band_hz
    coh_bins = tf.coherence[(f >= coh_lo) & (f <= coh_hi)]
    mean_coh = float(coh_bins.mean()) if coh_bins.size else None
    gates.append(
        _gate(
            "low_coherence",
            mean_coh is not None and mean_coh >= MIN_MEAN_BAND_COHERENCE,
            mean_coh,
            MIN_MEAN_BAND_COHERENCE,
            f"mean coherence over {coh_lo:g}-{coh_hi:g} Hz",
        )
    )
    usable = in_band & sxx_ok & (tf.coherence >= USABLE_COHERENCE_MIN)
    usable_range = (float(f[usable].min()), float(f[usable].max())) if usable.any() else None
    gates.append(
        _gate("unusable_frequency_range", int(usable.sum()) >= MIN_USABLE_BINS, float(usable.sum()), float(MIN_USABLE_BINS))
    )
    return QualityReport(tuple(gates), usable, usable_range, band_hz, mean_coh, rms)


__all__ = [
    "DEFAULT_ANALYSIS_BAND_HZ",
    "GateSeverity",
    "MAX_MISSING_SAMPLE_FRACTION",
    "MEAN_COHERENCE_BAND_HZ",
    "MIN_EXCITATION_RMS",
    "MIN_MEAN_BAND_COHERENCE",
    "MIN_USABLE_BINS",
    "MIN_WELCH_SEGMENTS",
    "NYQUIST_GUARD_FRACTION",
    "QualityGate",
    "QualityReport",
    "USABLE_COHERENCE_MIN",
    "analysis_band",
    "post_analysis_report",
    "pre_analysis_gates",
]
