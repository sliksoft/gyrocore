"""Stable / throttle-sweep segment selection — port of FPVPIDlab SegmentSelector."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .constants import (
    GYRO_STEADY_MAX_STD,
    SEGMENT_MIN_DURATION_S,
    SEGMENT_WINDOW_DURATION_S,
    SWEEP_MAX_DURATION_S,
    SWEEP_MAX_RESIDUAL,
    SWEEP_MIN_DURATION_S,
    SWEEP_MIN_THROTTLE_RANGE,
    THROTTLE_MAX_HOVER,
    THROTTLE_MIN_FLIGHT,
    YAW_STEADY_MULTIPLIER,
)
from .models import FlightSegment


def normalize_throttle(values: Sequence[float] | np.ndarray) -> np.ndarray:
    """Map raw throttle (µs or 0–1) to 0–1."""
    arr = np.asarray(values, dtype=float).reshape(-1)
    if arr.size == 0:
        return arr
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return np.zeros_like(arr)
    mx = float(np.nanmax(finite))
    if mx > 2.0:  # RC µs style
        return np.clip((arr - 1000.0) / 1000.0, 0.0, 1.0)
    return np.clip(arr, 0.0, 1.0)


def _std(values: np.ndarray, start: int, end: int) -> float:
    sl = values[start:end]
    if sl.size < 2:
        return 0.0
    return float(np.std(sl))


def find_steady_segments(
    throttle: Sequence[float] | np.ndarray,
    gyro_roll: Sequence[float] | np.ndarray,
    gyro_pitch: Sequence[float] | np.ndarray,
    gyro_yaw: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
) -> list[FlightSegment]:
    thr = normalize_throttle(throttle)
    gr = np.asarray(gyro_roll, dtype=float).reshape(-1)
    gp = np.asarray(gyro_pitch, dtype=float).reshape(-1)
    gy = np.asarray(gyro_yaw, dtype=float).reshape(-1)
    n = int(min(thr.size, gr.size, gp.size, gy.size))
    if n == 0 or sample_rate_hz <= 0:
        return []
    thr, gr, gp, gy = thr[:n], gr[:n], gp[:n], gy[:n]
    min_samples = max(1, int(SEGMENT_MIN_DURATION_S * sample_rate_hz))
    window = min(max(1, int(SEGMENT_WINDOW_DURATION_S * sample_rate_hz)), n)
    half = window // 2
    mask = np.zeros(n, dtype=np.uint8)
    for i in range(n):
        t = float(thr[i])
        if t < THROTTLE_MIN_FLIGHT or t > THROTTLE_MAX_HOVER:
            continue
        w0, w1 = max(0, i - half), min(n, i + half)
        if (
            _std(gr, w0, w1) <= GYRO_STEADY_MAX_STD
            and _std(gp, w0, w1) <= GYRO_STEADY_MAX_STD
            and _std(gy, w0, w1) <= GYRO_STEADY_MAX_STD * YAW_STEADY_MULTIPLIER
        ):
            mask[i] = 1
    return _mask_to_segments(mask, thr, sample_rate_hz, min_samples, kind="steady")


def find_throttle_sweep_segments(
    throttle: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
) -> list[FlightSegment]:
    """Monotonic throttle sweeps across a wide range (FPVPIDlab findThrottleSweepSegments)."""
    thr = normalize_throttle(throttle)
    n = int(thr.size)
    if n == 0 or sample_rate_hz <= 0:
        return []
    min_samples = max(1, int(SWEEP_MIN_DURATION_S * sample_rate_hz))
    max_samples = max(min_samples, int(SWEEP_MAX_DURATION_S * sample_rate_hz))
    segments: list[FlightSegment] = []
    i = 0
    while i < n:
        if thr[i] < THROTTLE_MIN_FLIGHT:
            i += 1
            continue
        j = i + 1
        while j < n and (j - i) < max_samples:
            j += 1
        length = j - i
        if length >= min_samples:
            window = thr[i:j]
            x = np.arange(length, dtype=float)
            try:
                slope, intercept = np.polyfit(x, window, 1)
                residual = float(np.mean(np.abs(window - (slope * x + intercept))))
            except (TypeError, ValueError, np.linalg.LinAlgError):
                residual = 1.0
                slope = 0.0
            thr_range = float(np.max(window) - np.min(window))
            if thr_range >= SWEEP_MIN_THROTTLE_RANGE and residual <= SWEEP_MAX_RESIDUAL and abs(slope) > 1e-6:
                segments.append(
                    FlightSegment(
                        start_index=i,
                        end_index=j,
                        duration_seconds=length / sample_rate_hz,
                        average_throttle=float(np.mean(window)),
                        min_throttle=float(np.min(window)),
                        max_throttle=float(np.max(window)),
                        kind="sweep",
                    )
                )
                i = j
                continue
        i += max(1, min_samples // 4)
    segments.sort(key=lambda s: s.duration_seconds, reverse=True)
    return segments


def _mask_to_segments(
    mask: np.ndarray,
    thr: np.ndarray,
    sample_rate_hz: float,
    min_samples: int,
    *,
    kind: str,
) -> list[FlightSegment]:
    segments: list[FlightSegment] = []
    n = int(mask.size)
    seg_start = -1
    for i in range(n + 1):
        is_set = i < n and mask[i] == 1
        if is_set and seg_start == -1:
            seg_start = i
        elif not is_set and seg_start != -1:
            length = i - seg_start
            if length >= min_samples:
                window = thr[seg_start:i]
                segments.append(
                    FlightSegment(
                        start_index=seg_start,
                        end_index=i,
                        duration_seconds=length / sample_rate_hz,
                        average_throttle=float(np.mean(window)),
                        min_throttle=float(np.min(window)),
                        max_throttle=float(np.max(window)),
                        kind=kind,
                    )
                )
            seg_start = -1
    segments.sort(key=lambda s: s.duration_seconds, reverse=True)
    return segments


def select_analysis_segments(
    throttle: Sequence[float] | np.ndarray,
    gyro_roll: Sequence[float] | np.ndarray,
    gyro_pitch: Sequence[float] | np.ndarray,
    gyro_yaw: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
    *,
    max_segments: int = 5,
) -> tuple[list[FlightSegment], list[str]]:
    warnings: list[str] = []
    sweeps = find_throttle_sweep_segments(throttle, sample_rate_hz)
    steady = find_steady_segments(throttle, gyro_roll, gyro_pitch, gyro_yaw, sample_rate_hz)
    chosen = sweeps if sweeps else steady
    if not chosen:
        thr = normalize_throttle(throttle)
        n = int(thr.size)
        if n > 0:
            warnings.append("insufficient_stable_segment: analyzing entire flight")
            chosen = [
                FlightSegment(
                    start_index=0,
                    end_index=n,
                    duration_seconds=n / max(sample_rate_hz, 1e-9),
                    average_throttle=float(np.mean(thr)),
                    min_throttle=float(np.min(thr)),
                    max_throttle=float(np.max(thr)),
                    kind="entire",
                )
            ]
        else:
            warnings.append("insufficient_stable_segment: no samples")
    return chosen[:max_segments], warnings
