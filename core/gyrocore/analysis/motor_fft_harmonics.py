# GyroCore WU4: adapted from AeroTuner backend/analysis/motor_fft_harmonics.py
"""
Motor electrical fundamental from merged FFT peaks using harmonic structure.

Input rows use ``frequency_hz`` / ``amplitude`` (``frame_inference_debug`` shape) or
``freq`` / ``amplitude`` (analysis ``fft_peaks`` shape).
"""

from __future__ import annotations

import math
from typing import Any


def _hz_tolerance(target_hz: float) -> float:
    """Hz window for harmonic alignment (scales with frequency)."""
    if not math.isfinite(target_hz) or target_hz <= 0:
        return 5.0
    return max(4.0, min(14.0, 0.028 * target_hz))


def _parse_peak_row(row: Any) -> tuple[float, float] | None:
    if not isinstance(row, dict):
        return None
    raw_f = row.get("frequency_hz")
    if raw_f is None:
        raw_f = row.get("freq")
    try:
        f = float(raw_f)
    except (TypeError, ValueError):
        return None
    try:
        a = float(row.get("amplitude", 0) or 0)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or not math.isfinite(a) or f <= 0 or a < 0:
        return None
    return f, a


def _peak_near(
    target_hz: float,
    peaks: list[tuple[float, float]],
    *,
    exclude_near_hz: float | None = None,
    exclude_tol_hz: float = 0.5,
) -> bool:
    tol = _hz_tolerance(target_hz)
    for pf, _ in peaks:
        if exclude_near_hz is not None and abs(pf - exclude_near_hz) <= exclude_tol_hz:
            continue
        if abs(pf - target_hz) <= tol:
            return True
    return False


def _is_harmonic_of_lower_peak(
    candidate_hz: float,
    peaks: list[tuple[float, float]],
    *,
    freq_min_hz: float,
) -> bool:
    """True if a plausible fundamental exists near f/2 or f/3 (this peak is likely a harmonic)."""
    for div in (2, 3):
        base = candidate_hz / float(div)
        if base < freq_min_hz:
            continue
        tol = _hz_tolerance(base)
        for pf, _ in peaks:
            if abs(pf - base) <= tol:
                return True
    return False


def fft_peaks_indexed_from_signal_analysis(
    signal_analysis: dict[str, Any] | None,
    *,
    limit: int = 32,
) -> list[dict[str, Any]]:
    """Build ``frequency_hz`` / ``amplitude`` rows from ``signal_analysis`` (merged ``fft_peaks`` or legacy arrays)."""
    out: list[dict[str, Any]] = []
    if not isinstance(signal_analysis, dict):
        return out
    fft_peaks = signal_analysis.get("fft_peaks")
    if isinstance(fft_peaks, list) and fft_peaks:
        for i, p in enumerate(fft_peaks):
            if len(out) >= limit:
                break
            if not isinstance(p, dict):
                continue
            try:
                f = float(p.get("freq", 0) or 0)
                a = float(p.get("amplitude", 0) or 0)
            except (TypeError, ValueError):
                continue
            if f <= 0:
                continue
            out.append(
                {
                    "peak_index": i,
                    "frequency_hz": round(f, 3),
                    "amplitude": round(a, 4),
                }
            )
        return out

    pf = signal_analysis.get("peak_frequencies") or []
    pa = signal_analysis.get("peak_amplitudes") or []
    if not isinstance(pf, list):
        return out
    for i, rawf in enumerate(pf):
        if len(out) >= limit:
            break
        try:
            f = float(rawf)
        except (TypeError, ValueError):
            continue
        if f <= 0:
            continue
        try:
            a = float(pa[i]) if isinstance(pa, list) and i < len(pa) else 0.0
        except (TypeError, ValueError):
            a = 0.0
        out.append(
            {
                "peak_index": i,
                "frequency_hz": round(f, 3),
                "amplitude": round(a, 4),
            }
        )
    return out


def estimate_motor_fundamental_from_fft_peaks_indexed(
    fft_peaks_indexed: list[Any] | None,
    *,
    freq_min_hz: float = 35.0,
    freq_max_hz: float = 500.0,
    top_n_candidates: int = 5,
    harmonic_match_weight: float = 1.35,
) -> dict[str, Any]:
    """
    Pick motor fundamental Hz from merged FFT peaks using 2f/3f support and submultiple rejection.

    Returns:
        ``fundamental_hz`` (float or None), ``harmonic_count`` (0–2), ``confidence`` (0..1).
    """
    empty: dict[str, Any] = {
        "fundamental_hz": None,
        "harmonic_count": 0,
        "confidence": 0.0,
    }
    if not isinstance(fft_peaks_indexed, list) or not fft_peaks_indexed:
        return empty

    parsed: list[tuple[float, float]] = []
    for row in fft_peaks_indexed:
        pair = _parse_peak_row(row)
        if pair is None:
            continue
        f, a = pair
        if not (freq_min_hz <= f <= freq_max_hz):
            continue
        parsed.append((f, a))

    if not parsed:
        return empty

    parsed.sort(key=lambda x: -x[1])
    candidates: list[tuple[float, float]] = []
    seen: set[float] = set()
    for f, a in parsed:
        key = round(f, 2)
        if key in seen:
            continue
        seen.add(key)
        candidates.append((f, a))
        if len(candidates) >= top_n_candidates:
            break

    if not candidates:
        return empty

    all_peaks = list(parsed)
    amp_dom = max(a for _, a in all_peaks) + 1e-12

    scored: list[tuple[float, float, int, float, bool]] = []
    for f, a in candidates:
        rejected = _is_harmonic_of_lower_peak(f, all_peaks, freq_min_hz=freq_min_hz)
        m2 = 1 if _peak_near(2.0 * f, all_peaks, exclude_near_hz=f) else 0
        m3 = 1 if _peak_near(3.0 * f, all_peaks, exclude_near_hz=f) else 0
        harmonic_matches = m2 + m3
        score = float(a) + harmonic_match_weight * float(harmonic_matches)
        scored.append((f, a, harmonic_matches, score, rejected))

    viable = [t for t in scored if not t[4]]
    pool = viable if viable else scored

    best = max(pool, key=lambda t: (t[3], t[2], t[1]))
    f_win, a_win, h_count, _, was_rejected = best
    f0 = float(f_win)

    conf = 0.18 + 0.36 * min(2, h_count) / 2.0 + 0.32 * min(1.0, a_win / amp_dom)
    if h_count == 0:
        conf *= 0.62
    if was_rejected and not viable:
        conf *= 0.45
    elif was_rejected:
        conf *= 0.78
    conf = max(0.0, min(1.0, conf))

    return {
        "fundamental_hz": round(f0, 3),
        "harmonic_count": int(h_count),
        "confidence": round(conf, 4),
    }


def validate_motor_fundamental_vs_kv_rpm(
    fundamental_hz: Any,
    kv: Any,
    battery_voltage_v: Any,
    throttle_avg: Any,
    *,
    ratio_min: float = 0.5,
    ratio_max: float = 2.0,
) -> dict[str, Any]:
    """
    Compare harmonic-filtered motor fundamental (Hz) to RPM implied by KV × voltage × throttle.

    ``expected_rpm = KV * battery_voltage * throttle_avg`` (throttle 0..1),
    ``expected_hz = expected_rpm / 60``. ``valid_match`` is true when
    ``ratio = detected_hz / expected_hz`` is in ``[ratio_min, ratio_max]``.
    """
    out: dict[str, Any] = {
        "expected_hz": None,
        "detected_hz": None,
        "ratio": None,
        "valid_match": False,
    }

    fh: float | None = None
    if fundamental_hz is not None:
        try:
            v = float(fundamental_hz)
        except (TypeError, ValueError):
            v = float("nan")
        if math.isfinite(v) and v > 0:
            fh = v
            out["detected_hz"] = round(fh, 3)

    try:
        kv_f = float(kv) if kv is not None else float("nan")
    except (TypeError, ValueError):
        kv_f = float("nan")
    try:
        vbat = float(battery_voltage_v) if battery_voltage_v is not None else float("nan")
    except (TypeError, ValueError):
        vbat = float("nan")
    try:
        thr = float(throttle_avg) if throttle_avg is not None else float("nan")
    except (TypeError, ValueError):
        thr = float("nan")

    if (
        not math.isfinite(kv_f)
        or not math.isfinite(vbat)
        or not math.isfinite(thr)
        or kv_f <= 0
        or vbat <= 0
        or thr < 0
    ):
        return out

    expected_rpm = kv_f * vbat * thr
    if not math.isfinite(expected_rpm) or expected_rpm <= 0:
        return out

    expected_hz = expected_rpm / 60.0
    if not math.isfinite(expected_hz) or expected_hz <= 0:
        return out
    out["expected_hz"] = round(expected_hz, 3)

    if fh is None or fh <= 0:
        return out

    ratio = fh / expected_hz
    if not math.isfinite(ratio) or ratio <= 0:
        return out
    out["ratio"] = round(ratio, 4)
    out["valid_match"] = bool(ratio_min <= ratio <= ratio_max)
    return out


HARMONIC_RATIO_BANDS: tuple[tuple[float, float, int], ...] = (
    (1.8, 2.2, 2),
    (0.45, 0.6, 2),
    (2.8, 3.2, 3),
    (3.8, 4.2, 4),
    (1.0 / 4.2, 1.0 / 3.8, 4),
)

RPM_ALIGNMENT_RATIO_MIN = 0.4
RPM_ALIGNMENT_RATIO_MAX = 2.5


def _rpm_alignment_harmonic_match(ratio: float) -> tuple[bool, int | None]:
    """
    True when ``ratio`` (detected/expected) sits in a known motor-harmonic band.

    Forward bands: detected ≈ n× expected (ratio ≈ n).
    Inverse bands: expected ≈ n× detected (ratio ≈ 1/n) — e.g. KV model at 4× the
    gyro/ERPM fundamental when the dominant line is the 1× mechanical peak.
    """
    rv = float(ratio)
    for lo, hi, harmonic in HARMONIC_RATIO_BANDS:
        if lo <= rv <= hi:
            return True, harmonic
    return False, None


def describe_rpm_harmonic_match_trace(ratio: float | None) -> dict[str, Any]:
    """Logging-only harmonic band evaluation for observability (no behavior change)."""
    if ratio is None:
        return {
            "harmonic_match": False,
            "reason_if_no_match": "ratio_missing",
            "min_ratio_threshold": RPM_ALIGNMENT_RATIO_MIN,
            "max_ratio_threshold": RPM_ALIGNMENT_RATIO_MAX,
        }
    rv = float(ratio)
    matched, harmonic = _rpm_alignment_harmonic_match(rv)
    band_parts: list[str] = []
    nearest_harmonic: int | None = None
    nearest_delta: float | None = None
    for lo, hi, band_h in HARMONIC_RATIO_BANDS:
        band_parts.append(f"{band_h}:{round(lo, 4)}-{round(hi, 4)}")
        mid = (lo + hi) / 2.0
        delta = abs(rv - mid)
        if nearest_delta is None or delta < nearest_delta:
            nearest_delta = delta
            nearest_harmonic = band_h
    out: dict[str, Any] = {
        "ratio": round(rv, 4),
        "harmonic_match": matched,
        "matched_harmonic": harmonic,
        "checked_harmonics": ",".join(band_parts),
        "min_ratio_threshold": RPM_ALIGNMENT_RATIO_MIN,
        "max_ratio_threshold": RPM_ALIGNMENT_RATIO_MAX,
        "nearest_harmonic": nearest_harmonic,
        "nearest_harmonic_delta": round(nearest_delta, 4) if nearest_delta is not None else None,
    }
    if not matched:
        if rv < RPM_ALIGNMENT_RATIO_MIN:
            out["reason_if_no_match"] = "below_min_ratio_threshold"
        elif rv > RPM_ALIGNMENT_RATIO_MAX:
            out["reason_if_no_match"] = "above_max_ratio_threshold"
        else:
            out["reason_if_no_match"] = "outside_harmonic_bands"
    return out


def rpm_alignment_for_merged_gyro_hz(
    merged_hz: Any,
    kv: Any,
    battery_voltage_v: Any,
    throttle_avg: Any,
    throttle_p95: Any = None,
) -> tuple[dict[str, Any], bool]:
    """
    Compare merged gyro line frequency (Hz) to ``KV * battery_voltage * throttle_effective / 60``.

    ``throttle_effective = max(throttle_avg, throttle_p95)`` when ``throttle_p95`` is provided;
    otherwise ``throttle_avg`` only. Mismatch uses ``ratio < 0.4`` or ``ratio > 2.5`` unless
    the ratio sits in a known harmonic band.
    """
    align: dict[str, Any] = {
        "expected_hz": None,
        "detected_hz": None,
        "ratio": None,
        "harmonic_match": False,
        "throttle_used": "avg",
    }

    try:
        ta = float(throttle_avg) if throttle_avg is not None else float("nan")
    except (TypeError, ValueError):
        ta = float("nan")
    tp: float | None = None
    if throttle_p95 is not None:
        try:
            tpv = float(throttle_p95)
        except (TypeError, ValueError):
            tpv = float("nan")
        if math.isfinite(tpv) and tpv >= 0:
            tp = tpv

    if tp is not None and math.isfinite(ta) and ta >= 0:
        throttle_effective = float(max(ta, tp))
        align["throttle_used"] = "p95" if tp >= ta else "avg"
    elif tp is not None:
        throttle_effective = float(tp)
        align["throttle_used"] = "p95"
    elif math.isfinite(ta) and ta >= 0:
        throttle_effective = float(ta)
        align["throttle_used"] = "avg"
    else:
        throttle_effective = float("nan")

    try:
        kv_f = float(kv) if kv is not None else float("nan")
    except (TypeError, ValueError):
        kv_f = float("nan")
    try:
        vbat = float(battery_voltage_v) if battery_voltage_v is not None else float("nan")
    except (TypeError, ValueError):
        vbat = float("nan")

    mh: float | None = None
    if merged_hz is not None:
        try:
            v = float(merged_hz)
        except (TypeError, ValueError):
            v = float("nan")
        if math.isfinite(v) and v > 0:
            mh = v
            align["detected_hz"] = round(mh, 3)

    if (
        not math.isfinite(kv_f)
        or not math.isfinite(vbat)
        or not math.isfinite(throttle_effective)
        or kv_f <= 0
        or vbat <= 0
        or throttle_effective < 0
    ):
        return align, False

    expected_rpm = kv_f * vbat * throttle_effective
    if not math.isfinite(expected_rpm) or expected_rpm <= 0:
        return align, False

    expected_hz = expected_rpm / 60.0
    if not math.isfinite(expected_hz) or expected_hz <= 0:
        return align, False
    align["expected_hz"] = round(expected_hz, 3)

    if mh is None or mh <= 0:
        return align, False

    ratio = mh / expected_hz
    if not math.isfinite(ratio) or ratio <= 0:
        return align, False
    rv = float(ratio)
    align["ratio"] = round(rv, 4)

    harmonic_match, _matched = _rpm_alignment_harmonic_match(rv)
    align["harmonic_match"] = harmonic_match

    mismatch = (rv < RPM_ALIGNMENT_RATIO_MIN or rv > RPM_ALIGNMENT_RATIO_MAX) and not harmonic_match
    return align, mismatch
