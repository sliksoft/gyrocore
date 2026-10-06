# GyroCore WU4: adapted from AeroTuner backend/analysis/quality_engine.py
"""
Pre-analysis flight log quality evaluation.

Combines duration, stick/throttle/gyro activity, and approximate behavior
diversity into a single score with human-readable issues and warnings.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np


def _to_finite_1d(x: np.ndarray) -> np.ndarray:
    a = np.asarray(x, dtype=np.float64).reshape(-1)
    return np.nan_to_num(a, nan=0.0, posinf=0.0, neginf=0.0)


def _row_norm_xyz(data: np.ndarray) -> np.ndarray:
    """L2 norm per row for (N, 3)."""
    m = np.asarray(data, dtype=np.float64)
    if m.ndim != 2 or m.shape[1] != 3:
        return np.zeros(0, dtype=np.float64)
    return np.sqrt(np.sum(m * m, axis=1))


def _align_samples(samples: Dict[str, np.ndarray]) -> Tuple[int, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Sanitize and align gyro, setpoint, throttle, time_us to common length.
    Returns (n, gyro (N,3), setpoint (N,3), throttle (N,), time_us (N,)).
    """
    gyro = np.asarray(samples.get("gyro", np.zeros((0, 3))), dtype=np.float64)
    sp = np.asarray(samples.get("setpoint", np.zeros((0, 3))), dtype=np.float64)
    thr = _to_finite_1d(np.asarray(samples.get("throttle", np.zeros(0)), dtype=np.float64))
    tu = _to_finite_1d(np.asarray(samples.get("time_us", np.zeros(0)), dtype=np.float64))

    if gyro.ndim != 2 or gyro.shape[1] != 3:
        gyro = np.zeros((0, 3), dtype=np.float64)
    if sp.ndim != 2 or sp.shape[1] != 3:
        sp = np.zeros((0, 3), dtype=np.float64)

    gyro = np.nan_to_num(gyro, nan=0.0, posinf=0.0, neginf=0.0)
    sp = np.nan_to_num(sp, nan=0.0, posinf=0.0, neginf=0.0)

    lengths = [gyro.shape[0], sp.shape[0], thr.size, tu.size]
    n = int(min(lengths)) if lengths else 0
    if n == 0:
        return 0, gyro[:0], sp[:0], thr[:0], tu[:0]

    return n, gyro[:n], sp[:n], thr[:n], tu[:n]


def _duration_seconds(time_us: np.ndarray) -> float:
    if time_us.size < 2:
        return 0.0
    span = float(time_us[-1] - time_us[0]) / 1e6
    return max(0.0, span)


def _normalize_activity_rms(mag: np.ndarray) -> float:
    """Map RMS of magnitude signal to ~[0, 1] using robust in-log scaling."""
    if mag.size == 0:
        return 0.0
    m = np.abs(mag)
    rms = float(np.sqrt(np.mean(m * m)))
    peak = float(np.percentile(m, 99.0))
    scale = max(peak, float(np.median(m)) + 1e-6, 1e-6)
    # Typical sinusoid: rms/peak ~ 0.707; cap at 1.
    return float(np.clip(rms / scale, 0.0, 1.0))


def _throttle_variation(throttle: np.ndarray) -> float:
    if throttle.size < 2:
        return 0.0
    t = throttle.astype(np.float64, copy=False)
    p95 = float(np.percentile(t, 95.0))
    p5 = float(np.percentile(t, 5.0))
    span = p95 - p5
    std_t = float(np.std(t))
    # Combine range and relative std for hover vs active throttle.
    combined = 0.6 * span + 0.4 * min(1.0, std_t * 4.0)
    return float(np.clip(combined, 0.0, 1.0))


def _duration_score(duration_s: float) -> float:
    """Rises smoothly from short logs toward plateau (seconds scale)."""
    # 0 at ~0s, ~50 near 20s, approaches 100 by ~90s+
    x = duration_s / 45.0
    s = 100.0 * (1.0 - np.exp(-np.clip(x, 0.0, 12.0)))
    return float(np.clip(s, 0.0, 100.0))


def _quadratic_bump(x: float, center: float, half_width: float) -> float:
    """Smooth 0..1 bump peaking at center."""
    if half_width <= 0:
        return 0.0
    u = (x - center) / half_width
    if u < -1.0 or u > 1.0:
        return 0.0
    return float(1.0 - u * u)


def _gyro_jitter_index(gyro_mag: np.ndarray) -> float:
    """Higher when high-frequency content dominates magnitude (rough noise proxy)."""
    if gyro_mag.size < 8:
        return 0.0
    d1 = np.abs(np.diff(gyro_mag))
    if d1.size == 0:
        return 0.0
    d2 = np.abs(np.diff(gyro_mag, n=2))
    m = float(np.median(np.abs(gyro_mag)) + 1e-6)
    j1 = float(np.median(d1) / m)
    j2 = float(np.median(d2) / m) if d2.size else 0.0
    raw = 0.65 * j1 + 0.35 * j2
    # Soft squash to [0, 1]; tuned so clean logs stay low.
    return float(np.clip(raw / (raw + 2.5), 0.0, 1.0))


def _segment_diversity(
    setpoint_mag: np.ndarray,
    gyro_mag: np.ndarray,
    throttle: np.ndarray,
    time_us: np.ndarray,
) -> float:
    """
    Approximate behavior diversity without segment_engine.

    Labels windows as hover-like, punch-like (rapid throttle / stick transients),
    or maneuver-like (sustained high setpoint). Score uses entropy of dominant
    labels plus presence of multiple types.
    """
    n = setpoint_mag.size
    if n < 30:
        return 0.0

    n_seg = int(np.clip(n // 120, 5, 24))
    edges = np.linspace(0, n, n_seg + 1, dtype=int)

    g_sp = float(np.percentile(setpoint_mag, 60.0))
    g_gy = float(np.percentile(gyro_mag, 60.0))

    thr_all = np.abs(np.diff(throttle.astype(np.float64)))
    sp_all = np.abs(np.diff(setpoint_mag))
    thr_thr = float(np.percentile(thr_all, 85.0)) if thr_all.size else 0.0
    sp_thr = float(np.percentile(sp_all, 90.0)) if sp_all.size else 0.0

    dominant: List[int] = []
    for k in range(n_seg):
        a, b = int(edges[k]), int(edges[k + 1])
        if b - a < 3:
            continue
        s_slice = setpoint_mag[a:b]
        g_slice = gyro_mag[a:b]
        th_slice = throttle[a:b]
        t_slice = time_us[a:b].astype(np.float64) / 1e6

        ms = float(np.mean(s_slice))
        mg = float(np.mean(g_slice))
        dth = np.abs(np.diff(th_slice))
        dsp = np.abs(np.diff(s_slice))
        max_dth = float(np.max(dth)) if dth.size else 0.0
        max_dsp = float(np.max(dsp)) if dsp.size else 0.0

        hover_score = 1.0 if (ms < 0.45 * max(g_sp, 1e-6) and mg < 0.45 * max(g_gy, 1e-6)) else 0.0
        punch_score = 1.0 if (max_dth > max(thr_thr, 1e-9) or max_dsp > max(sp_thr, 1e-9)) else 0.0
        maneuver_score = 1.0 if (ms > g_sp or mg > g_gy) else 0.0

        scores = (hover_score, punch_score, maneuver_score)
        dominant.append(int(np.argmax(scores)))

    if not dominant:
        return 0.0

    counts = np.bincount(np.asarray(dominant, dtype=int), minlength=3).astype(np.float64)
    p = counts / max(float(np.sum(counts)), 1.0)
    p = p[p > 0]
    ent = -float(np.sum(p * np.log(p + 1e-15)))
    ent_norm = ent / float(np.log(3.0))
    present = float(np.sum(counts > 0)) / 3.0
    mix = 1.0 - float(np.max(counts) / max(float(np.sum(counts)), 1.0))

    return float(np.clip(0.45 * ent_norm + 0.35 * present + 0.20 * mix, 0.0, 1.0))


def _grade_from_score(score: float) -> str:
    if score >= 85.0:
        return "A"
    if score >= 70.0:
        return "B"
    if score >= 50.0:
        return "C"
    return "D"


def evaluate_quality(samples: Dict[str, np.ndarray]) -> Dict[str, Any]:
    """
    Evaluate whether a flight log is suitable for downstream analysis.

    Returns score 0–100, letter grade, ``status`` (ok | low_confidence | low_quality),
    ``ready`` (True only when status is ok, for backward compatibility), issues,
    warnings, and normalized metric summaries.
    """
    empty = {
        "score": 0.0,
        "grade": "D",
        "status": "low_quality",
        "ready": False,
        "issues": ["No valid samples in log"],
        "warnings": [],
        "metrics": {
            "duration_s": 0.0,
            "stick_activity": 0.0,
            "throttle_variation": 0.0,
            "gyro_activity": 0.0,
            "segment_diversity": 0.0,
        },
    }

    n, gyro, sp, throttle, time_us = _align_samples(samples)
    if n < 2:
        return empty

    setpoint_mag = _row_norm_xyz(sp)
    gyro_mag = _row_norm_xyz(gyro)
    if setpoint_mag.size != n or gyro_mag.size != n:
        return empty

    duration_s = _duration_seconds(time_us)
    stick_activity = _normalize_activity_rms(setpoint_mag)
    throttle_var = _throttle_variation(throttle)
    gyro_activity = _normalize_activity_rms(gyro_mag)
    diversity = _segment_diversity(setpoint_mag, gyro_mag, throttle, time_us)

    jitter = _gyro_jitter_index(gyro_mag)

    duration_sc = _duration_score(duration_s)
    stick_sc = 100.0 * stick_activity
    throttle_sc = 100.0 * throttle_var

    motion_bump = _quadratic_bump(gyro_activity, center=0.42, half_width=0.55)
    gyro_motion_sc = 100.0 * motion_bump
    gyro_sc = gyro_motion_sc * (1.0 - 0.55 * jitter)
    gyro_sc = float(np.clip(gyro_sc, 0.0, 100.0))

    diversity_sc = 100.0 * diversity

    score = (
        duration_sc * 0.20
        + stick_sc * 0.25
        + throttle_sc * 0.20
        + gyro_sc * 0.20
        + diversity_sc * 0.15
    )
    score = float(np.clip(score, 0.0, 100.0))

    grade = _grade_from_score(score)
    if score >= 60.0:
        status = "ok"
    elif score >= 50.0:
        status = "low_confidence"
    else:
        status = "low_quality"
    ready = status == "ok"

    issues: List[str] = []
    warnings: List[str] = []

    if duration_s < 12.0:
        issues.append("Flight duration too short for reliable analysis")
    elif duration_s < 25.0:
        warnings.append("Flight duration is on the short side for robust tuning")

    if stick_activity < 0.12:
        issues.append("Very low stick activity (no maneuvers detected)")
    elif stick_activity < 0.22:
        warnings.append("Stick activity is low; log may be mostly cruise or hover")

    if throttle_var < 0.14:
        warnings.append("Limited throttle range used")
    if diversity < 0.30:
        warnings.append("Low segment diversity (few distinct flight behaviors)")

    if gyro_activity < 0.08 and duration_s >= 12.0:
        issues.append("Very low gyro activity (aircraft may be static or log unusable)")

    if jitter > 0.72:
        issues.append("Gyro signal appears excessively noisy or glitchy")
    elif jitter > 0.45:
        warnings.append("Elevated gyro roughness; check vibrations or logging issues")

    if not np.isfinite(score):
        score = 0.0
        grade = "D"
        status = "low_quality"
        ready = False
        issues.append("Quality score computation produced non-finite values")

    return {
        "score": float(score),
        "grade": grade,
        "status": status,
        "ready": bool(ready),
        "issues": issues,
        "warnings": warnings,
        "metrics": {
            "duration_s": float(duration_s),
            "stick_activity": float(stick_activity),
            "throttle_variation": float(throttle_var),
            "gyro_activity": float(gyro_activity),
            "segment_diversity": float(diversity),
        },
    }
