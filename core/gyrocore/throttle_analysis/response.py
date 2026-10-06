"""Throttle-region response using WU7 Welch TF — advisory TPA only."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from gyrocore.autotune.recommend import compute_mean_coherence, find_bandwidth
from gyrocore.chirp.system_id import welch_transfer_function
from gyrocore.filter_evidence.segments import normalize_throttle

from .constants import (
    DEFAULT_TF_BANDS,
    MIN_TF_RUN_SAMPLES,
    MIN_TF_SAMPLES,
    PROVENANCE,
    TPA_HIGH_THROTTLE_OVERSHOOT_DELTA_PP,
    TPA_TF_MIN_BANDS,
    TPA_VARIANCE_BANDWIDTH_HZ,
    TPA_VARIANCE_PHASE_MARGIN_DEG,
)
from .models import ThrottleBandResponse, ThrottleResponseAnalysis
from .spectrogram import bin_by_throttle, find_contiguous_runs


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = sum(values) / len(values)
    return float((sum((v - m) ** 2 for v in values) / (len(values) - 1)) ** 0.5)


def analyze_throttle_response(
    throttle: Sequence[float] | np.ndarray,
    setpoint_roll: Sequence[float] | np.ndarray,
    gyro_roll: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
    *,
    num_bands: int = DEFAULT_TF_BANDS,
    setpoint_pitch: Sequence[float] | np.ndarray | None = None,
    gyro_pitch: Sequence[float] | np.ndarray | None = None,
) -> ThrottleResponseAnalysis:
    """Reuse WU7 ``welch_transfer_function`` over contiguous throttle-band runs."""
    warnings: list[str] = []
    thr = normalize_throttle(throttle)
    sp = np.asarray(setpoint_roll, dtype=float).reshape(-1)
    gy = np.asarray(gyro_roll, dtype=float).reshape(-1)
    n = int(min(thr.size, sp.size, gy.size))
    if n == 0 or sample_rate_hz <= 0:
        return ThrottleResponseAnalysis(
            throttle_bands=[],
            usable_bands=0,
            response_metrics={},
            bandwidth_evidence={},
            phase_coherence_evidence={},
            high_throttle_degradation=False,
            confidence="low",
            warnings=["no_samples"],
            tpa_advisory="insufficient_evidence",
            provenance=dict(PROVENANCE),
            actionable=False,
        )

    thr, sp, gy = thr[:n], sp[:n], gy[:n]
    # Drop non-finite samples without splicing discontinuous indices into one FFT
    finite = np.isfinite(thr) & np.isfinite(sp) & np.isfinite(gy)
    dropped = int(n - int(np.count_nonzero(finite)))
    if dropped:
        warnings.append(f"dropped_samples:{dropped}")

    bins = bin_by_throttle(thr, num_bands)
    bands: list[ThrottleBandResponse] = []
    bandwidths: list[float] = []
    coherences: list[float] = []

    for b, indices in enumerate(bins):
        tmin = b / num_bands
        tmax = (b + 1) / num_bands
        # Keep only finite indices
        indices = [i for i in indices if finite[i]]
        sample_count = len(indices)
        band = ThrottleBandResponse(
            throttle_min=round(tmin, 3),
            throttle_max=round(tmax, 3),
            sample_count=sample_count,
            usable=False,
        )
        if sample_count < MIN_TF_SAMPLES:
            if b >= num_bands - 2:
                warnings.append("insufficient_high_throttle_samples")
            bands.append(band)
            continue
        runs = find_contiguous_runs(indices, MIN_TF_RUN_SAMPLES)
        if not runs:
            warnings.append(f"band_{b}_discontinuous_runs")
            bands.append(band)
            continue
        start, end = runs[0]
        try:
            tf = welch_transfer_function(sp[start:end], gy[start:end], sample_rate_hz)
            bw = find_bandwidth(tf)
            coh = compute_mean_coherence(tf)
        except ValueError as exc:
            band.warnings.append(str(exc)[:120])
            bands.append(band)
            continue
        band.usable = bool(np.isfinite(bw))
        band.bandwidth_hz = float(bw) if np.isfinite(bw) else None
        band.mean_coherence = float(coh) if np.isfinite(coh) else None
        # Phase proxy: mean phase where coherence is decent
        mask = tf.coherence >= 0.3
        if mask.any():
            band.phase_proxy_deg = float(np.mean(tf.phase_deg[mask]))
        if band.usable and band.bandwidth_hz is not None:
            bandwidths.append(band.bandwidth_hz)
            if band.mean_coherence is not None:
                coherences.append(band.mean_coherence)
        bands.append(band)

    usable = sum(1 for b in bands if b.usable)
    bw_std = _std(bandwidths)
    coh_mean = float(np.mean(coherences)) if coherences else None

    # High-throttle degradation: last usable band bandwidth << first usable
    usable_bands = [b for b in bands if b.usable and b.bandwidth_hz is not None]
    high_deg = False
    low_deg = False
    if len(usable_bands) >= 2:
        low_bw = usable_bands[0].bandwidth_hz or 0.0
        high_bw = usable_bands[-1].bandwidth_hz or 0.0
        if low_bw > 0 and (low_bw - high_bw) >= TPA_HIGH_THROTTLE_OVERSHOOT_DELTA_PP:
            high_deg = True
        if high_bw > 0 and (high_bw - low_bw) >= TPA_HIGH_THROTTLE_OVERSHOOT_DELTA_PP:
            low_deg = True

    if usable < TPA_TF_MIN_BANDS:
        advisory = "insufficient_evidence"
        confidence = "low"
    elif high_deg:
        advisory = "high_throttle_degradation_detected"
        confidence = "medium"
    elif low_deg:
        advisory = "low_throttle_degradation_detected"
        confidence = "medium"
    elif bw_std >= TPA_VARIANCE_BANDWIDTH_HZ:
        advisory = "tpa_review_recommended"
        confidence = "medium"
        warnings.append(f"bandwidth_std_hz:{bw_std:.1f}")
    else:
        advisory = "stable_across_throttle"
        confidence = "high" if usable >= TPA_TF_MIN_BANDS else "medium"

    # Optional pitch axis ignored for metrics but accepted for future parity
    _ = (setpoint_pitch, gyro_pitch, TPA_VARIANCE_PHASE_MARGIN_DEG)

    return ThrottleResponseAnalysis(
        throttle_bands=bands,
        usable_bands=usable,
        response_metrics={"bandwidth_std_hz": round(bw_std, 2), "usable_bands": usable},
        bandwidth_evidence={"per_band_hz": [b.bandwidth_hz for b in bands], "std_hz": round(bw_std, 2)},
        phase_coherence_evidence={"mean_coherence": coh_mean},
        high_throttle_degradation=high_deg,
        confidence=confidence,
        warnings=list(dict.fromkeys(warnings)),
        tpa_advisory=advisory,
        provenance=dict(PROVENANCE),
        actionable=False,
    )
