"""Filter group-delay estimator — EXACT_PARITY port of FPVPIDlab GroupDelayEstimator."""

from __future__ import annotations

import math
from typing import Any, Mapping

from .constants import (
    FILTER_LATENCY_BUDGET_DEFAULT_DTERM_MS,
    FILTER_LATENCY_BUDGET_DEFAULT_GYRO_MS,
    GROUP_DELAY_REFERENCE_HZ,
)
from .models import GroupDelayEstimate


def pt1_group_delay(cutoff_hz: float, freq_hz: float) -> float:
    if cutoff_hz <= 0:
        return 0.0
    wc = 2.0 * math.pi * cutoff_hz
    w = 2.0 * math.pi * freq_hz
    return wc / (wc * wc + w * w)


def biquad_group_delay(cutoff_hz: float, freq_hz: float, q: float = math.sqrt(0.5)) -> float:
    if cutoff_hz <= 0:
        return 0.0
    w0 = 2.0 * math.pi * cutoff_hz
    w = 2.0 * math.pi * freq_hz
    w0sq = w0 * w0
    wsq = w * w
    num = (w0 / q) * (w0sq + wsq)
    denom = (w0sq - wsq) * (w0sq - wsq) + ((w0 * w) / q) * ((w0 * w) / q)
    if denom == 0:
        return 0.0
    return num / denom


def notch_group_delay(notch_hz: float, freq_hz: float, q: float = 3.0) -> float:
    if notch_hz <= 0:
        return 0.0
    w0 = 2.0 * math.pi * notch_hz
    w = 2.0 * math.pi * freq_hz
    w0sq = w0 * w0
    wsq = w * w
    bw = w0 / q
    return (bw * (w0sq + wsq)) / ((w0sq - wsq) * (w0sq - wsq) + bw * bw * wsq)


def _f(settings: Mapping[str, Any], *keys: str, default: float = 0.0) -> float:
    for key in keys:
        if key in settings and settings[key] is not None:
            try:
                return float(settings[key])
            except (TypeError, ValueError):
                continue
    return default


def estimate_group_delay(
    settings: Mapping[str, Any],
    reference_hz: float = GROUP_DELAY_REFERENCE_HZ,
    *,
    gyro_budget_ms: float = FILTER_LATENCY_BUDGET_DEFAULT_GYRO_MS,
    dterm_budget_ms: float = FILTER_LATENCY_BUDGET_DEFAULT_DTERM_MS,
) -> GroupDelayEstimate:
    filters: list[dict[str, Any]] = []
    gyro_total_s = 0.0
    dterm_total_s = 0.0

    gyro_dyn_min = _f(settings, "gyro_lpf1_dyn_min_hz")
    gyro_static = _f(settings, "gyro_lpf1_static_hz")
    effective_gyro = gyro_dyn_min if gyro_dyn_min > 0 else gyro_static
    if effective_gyro > 0:
        delay = pt1_group_delay(effective_gyro, reference_hz)
        gyro_total_s += delay
        filters.append({"type": "gyro_lpf1", "cutoff_hz": effective_gyro, "delay_ms": delay * 1000})

    gyro_lpf2 = _f(settings, "gyro_lpf2_static_hz")
    if gyro_lpf2 > 0:
        delay = pt1_group_delay(gyro_lpf2, reference_hz)
        gyro_total_s += delay
        filters.append({"type": "gyro_lpf2", "cutoff_hz": gyro_lpf2, "delay_ms": delay * 1000})

    notch_min = _f(settings, "dyn_notch_min_hz")
    notch_max = _f(settings, "dyn_notch_max_hz")
    if notch_min > 0 and notch_max > 0:
        center = (notch_min + notch_max) / 2.0
        q = _f(settings, "dyn_notch_q", default=300.0)
        actual_q = q / 100.0 if q > 10 else q
        count = int(_f(settings, "dyn_notch_count", default=3.0) or 3)
        delay = notch_group_delay(center, reference_hz, actual_q) * count
        gyro_total_s += delay
        filters.append({"type": "dyn_notch", "cutoff_hz": center, "delay_ms": delay * 1000})

    dterm_dyn_min = _f(settings, "dterm_lpf1_dyn_min_hz")
    dterm_static = _f(settings, "dterm_lpf1_static_hz")
    effective_dterm = dterm_dyn_min if dterm_dyn_min > 0 else dterm_static
    if effective_dterm > 0:
        delay = pt1_group_delay(effective_dterm, reference_hz)
        dterm_total_s += delay
        filters.append({"type": "dterm_lpf1", "cutoff_hz": effective_dterm, "delay_ms": delay * 1000})

    dterm_lpf2 = _f(settings, "dterm_lpf2_static_hz")
    if dterm_lpf2 > 0:
        delay = pt1_group_delay(dterm_lpf2, reference_hz)
        dterm_total_s += delay
        filters.append({"type": "dterm_lpf2", "cutoff_hz": dterm_lpf2, "delay_ms": delay * 1000})

    gyro_ms = round(gyro_total_s * 1000, 2)
    dterm_ms = round(dterm_total_s * 1000, 2)
    gyro_over = gyro_ms > gyro_budget_ms
    dterm_over = dterm_ms > dterm_budget_ms
    warning = None
    if gyro_over:
        warning = (
            f"Gyro filter chain adds {gyro_ms:.1f}ms at {reference_hz} Hz — "
            f"over the {gyro_budget_ms:.1f}ms latency budget."
        )
    return GroupDelayEstimate(
        reference_hz=reference_hz,
        gyro_total_ms=gyro_ms,
        dterm_total_ms=dterm_ms,
        gyro_budget_ms=gyro_budget_ms,
        dterm_budget_ms=dterm_budget_ms,
        gyro_over_budget=gyro_over,
        dterm_over_budget=dterm_over,
        filters=filters,
        warning=warning,
    )
