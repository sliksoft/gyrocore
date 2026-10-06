# GyroCore WU4: adapted from AeroTuner backend/analysis/erpm_analysis.py
"""
ERPM → motor electrical frequency (Hz) and simple harmonic summary for RPM filter hints.
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

ERPM_SCALE_THRESHOLD = 10000.0
ERPM_SCALE_AMBIGUOUS_LOW = 9500.0
ERPM_SCALE_AMBIGUOUS_HIGH = 10500.0


def normalize_erpm_for_sample(raw: Any) -> list[float | None]:
    """Normalize parser or legacy ERPM shapes to [motor1..motor4]."""
    return _normalize_erpm_row(raw)


def _normalize_erpm_row(raw: Any) -> list[float | None]:
    """Ensure [m1..m4] with float or None."""
    if raw is None:
        return [None, None, None, None]
    if isinstance(raw, bool):
        return [None, None, None, None]
    if isinstance(raw, (int, float)):
        v = float(raw)
        if not math.isfinite(v):
            return [None, None, None, None]
        return [v, v, v, v]
    if isinstance(raw, (list, tuple)):
        out: list[float | None] = []
        for i in range(4):
            if i >= len(raw) or raw[i] is None:
                out.append(None)
            else:
                try:
                    fv = float(raw[i])
                    out.append(fv if math.isfinite(fv) else None)
                except (TypeError, ValueError):
                    out.append(None)
        return out
    return [None, None, None, None]


def _raw_erpm_values_for_motor(samples: list[dict], motor_index: int) -> list[float]:
    """Positive finite ERPM samples for one motor (parser units, often eRPM/100 from Betaflight)."""
    vals: list[float] = []
    for s in samples:
        if not isinstance(s, dict):
            continue
        row = _normalize_erpm_row(s.get("erpm"))
        v = row[motor_index]
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv) and fv > 0:
            vals.append(fv)
    return vals


def _hz_series_for_motor(samples: list[dict], motor_index: int) -> list[float]:
    """
    Electrical Hz from ERPM via hz = ERPM_electrical / 60.

    Betaflight blackbox often stores **eRPM / 100**. If the per-motor mean raw value
    is below 10_000, treat the series as scaled and multiply by 100 before /60.
    Means >= 10_000 are left unchanged (already full electrical RPM).
    """
    raw_vals = _raw_erpm_values_for_motor(samples, motor_index)
    if not raw_vals:
        return []

    mean_raw = sum(raw_vals) / len(raw_vals)
    erpm_scale = 100.0 if mean_raw < ERPM_SCALE_THRESHOLD else 1.0

    out: list[float] = []
    for i, v in enumerate(raw_vals):
        v_corrected = v * erpm_scale
        if i == 0:
            logger.debug("ERPM RAW: %s", v)
            logger.debug("ERPM SCALED: %s", v_corrected)
        hz = v_corrected / 60.0
        if math.isfinite(hz) and hz > 0:
            out.append(hz)
    return out


def _mean(vals: list[float]) -> float | None:
    if not vals:
        return None
    return float(sum(vals) / len(vals))


def _variance(vals: list[float], mean_hz: float) -> float:
    if len(vals) < 2:
        return 0.0
    m = mean_hz
    return float(sum((x - m) ** 2 for x in vals) / len(vals))


def _coefficient_of_variation(vals: list[float]) -> float | None:
    m = _mean(vals)
    if m is None or m <= 0 or len(vals) < 2:
        return None
    var = _variance(vals, m)
    std = math.sqrt(max(0.0, var))
    return std / m


def _erpm_availability_metadata(samples: list[dict]) -> dict[str, Any]:
    """
    Row counts, coverage, and scale labels mirroring ``_hz_series_for_motor`` (first motor with data).

    Does not alter frequency conversion math.
    """
    if not samples:
        return {
            "erpm_sample_count": 0,
            "erpm_rows_with_erpm": 0,
            "erpm_sample_coverage": 0.0,
            "erpm_scale_assumption": "unknown",
            "erpm_scale_reason": "no_erpm_samples",
            "heuristic_warnings": [],
        }
    rows_with_any = 0
    for s in samples:
        if not isinstance(s, dict):
            continue
        row = _normalize_erpm_row(s.get("erpm"))
        if any(x is not None and x > 0 for x in row):
            rows_with_any += 1
    coverage = rows_with_any / max(1, len(samples))
    assumption = "unknown"
    reason = "no_erpm_samples"
    for mi in range(4):
        raw_vals = _raw_erpm_values_for_motor(samples, mi)
        if not raw_vals:
            continue
        mean_raw = sum(raw_vals) / len(raw_vals)
        if ERPM_SCALE_AMBIGUOUS_LOW <= mean_raw <= ERPM_SCALE_AMBIGUOUS_HIGH:
            assumption = "ambiguous"
            reason = "mean_raw_near_10000_boundary"
        elif mean_raw < ERPM_SCALE_THRESHOLD:
            assumption = "div100"
            reason = "mean_raw_below_10000"
        else:
            assumption = "full"
            reason = "mean_raw_at_or_above_10000"
        break
    heuristic_warnings: list[str] = []
    if assumption == "div100":
        heuristic_warnings.append(
            "ERPM scale heuristic applied: mean raw ERPM below 10,000, so values were "
            "multiplied by 100 (Betaflight eRPM/100 storage convention)."
        )
    elif assumption == "ambiguous":
        heuristic_warnings.append(
            "ERPM scale is ambiguous near the 10,000 threshold; confidence should be treated conservatively."
        )
    return {
        "erpm_sample_count": len(samples),
        "erpm_rows_with_erpm": rows_with_any,
        "erpm_sample_coverage": round(float(coverage), 4),
        "erpm_scale_assumption": assumption,
        "erpm_scale_reason": reason,
        "heuristic_warnings": heuristic_warnings,
    }


def _valid_hz(val: float | None) -> float | None:
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def analyze_erpm(samples: list[dict]) -> dict[str, Any]:
    """
    Per-motor average electrical Hz from ERPM, harmonics 1x–3x, pooled dominant frequency,
    and a simple confidence score (stable ERPM → higher).
    """
    empty_row: list[float | None] = [None, None, None]
    empty: dict[str, Any] = {
        "motor_frequencies_hz": [None, None, None, None],
        "harmonics_hz": [list(empty_row), list(empty_row), list(empty_row), list(empty_row)],
        "dominant_frequency": None,
        "confidence": 0.0,
    }
    if not samples:
        empty.update(_erpm_availability_metadata([]))
        return empty

    motor_hz: list[float | None] = [None, None, None, None]
    harmonics_hz: list[list[float | None]] = [
        list(empty_row),
        list(empty_row),
        list(empty_row),
        list(empty_row),
    ]

    for mi in range(4):
        series = _hz_series_for_motor(samples, mi)
        avg = _mean(series)
        av = _valid_hz(avg)
        motor_hz[mi] = av
        if av is not None:
            h1 = _valid_hz(av)
            h2 = _valid_hz(2.0 * av)
            h3 = _valid_hz(3.0 * av)
            harmonics_hz[mi] = [h1, h2, h3]
        else:
            harmonics_hz[mi] = [None, None, None]

    valid_avgs = [h for h in motor_hz if h is not None and h > 0]
    if not valid_avgs:
        out_empty = {
            "motor_frequencies_hz": motor_hz,
            "harmonics_hz": harmonics_hz,
            "dominant_frequency": None,
            "confidence": 0.0,
        }
        out_empty.update(_erpm_availability_metadata(samples))
        return out_empty

    dominant = float(sum(valid_avgs) / len(valid_avgs))

    # Sample coverage: fraction of rows with at least one motor ERPM
    rows_with_any = 0
    for s in samples:
        if not isinstance(s, dict):
            continue
        row = _normalize_erpm_row(s.get("erpm"))
        if any(x is not None and x > 0 for x in row):
            rows_with_any += 1
    coverage = rows_with_any / max(1, len(samples))

    cvs: list[float] = []
    for mi in range(4):
        series = _hz_series_for_motor(samples, mi)
        cv = _coefficient_of_variation(series)
        if cv is not None:
            cvs.append(cv)

    mean_cv = sum(cvs) / len(cvs) if cvs else 1.0
    # Low CV → high stability factor; cap CV contribution
    stability = 1.0 / (1.0 + 3.0 * min(mean_cv, 2.0))
    coverage_factor = min(1.0, coverage * 2.0) if coverage < 0.5 else 1.0
    confidence = max(0.0, min(1.0, stability * coverage_factor * (len(valid_avgs) / 4.0)))

    out = {
        "motor_frequencies_hz": motor_hz,
        "harmonics_hz": harmonics_hz,
        "dominant_frequency": dominant,
        "confidence": round(confidence, 4),
    }
    out.update(_erpm_availability_metadata(samples))
    return out
