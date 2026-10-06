# GyroCore WU4: adapted from AeroTuner backend/analysis/resonance_v2.py
"""
Lightweight FFT peak detection for resonance classification.

Used on merged spectra and on per-axis spectra (roll/pitch/yaw) in the analyze pipeline.

Peaks may be annotated with ``type`` (``motor`` | ``frame``) and ``harmonic_order`` when
ERPM-derived motor electrical frequency is available (fundamental Hz = ERPM / 60).
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from gyrocore.analysis.erpm_units import resolve_pole_pairs, to_mechanical_hz

_PEAK_FREQ_MIN = 30.0
_PEAK_FREQ_MAX = 500.0
_MAX_PEAKS = 6

# Minimum ERPM analysis confidence before labeling peaks as motor harmonics (reduces false positives).
_ERPM_CONFIDENCE_MIN = 0.12
# Harmonics n·f0 while n·f0 stays in the peak search band.
_MAX_HARMONIC_ORDER = 24

PEAK_TYPE_MOTOR = "motor"
PEAK_TYPE_FRAME = "frame"


def _try_positive_hz(val: Any) -> float | None:
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def motor_fundamentals_hz(
    erpm_analysis: dict | None,
    *,
    motor_poles: Any = None,
    pole_pairs: Any = None,
) -> list[float]:
    """Per-motor mechanical fundamentals (Hz) for gyro-FFT peak annotation."""
    if not isinstance(erpm_analysis, dict):
        return []
    resolved_pp = resolve_pole_pairs(
        motor_poles=motor_poles if motor_poles is not None else erpm_analysis.get("motor_poles"),
        pole_pairs=pole_pairs if pole_pairs is not None else erpm_analysis.get("pole_pairs"),
    )
    out: list[float] = []
    for x in erpm_analysis.get("motor_frequencies_mechanical_hz") or []:
        v = _try_positive_hz(x)
        if v is not None:
            out.append(v)
    if out:
        return out
    for x in erpm_analysis.get("motor_frequencies_hz") or []:
        v = to_mechanical_hz(x, pole_pairs=resolved_pp, already_mechanical_hz=False)
        if v is not None and v > 0:
            out.append(float(v))
    if not out:
        v = _try_positive_hz(erpm_analysis.get("dominant_frequency_mechanical_hz"))
        if v is not None:
            out.append(v)
    if not out:
        v = to_mechanical_hz(
            erpm_analysis.get("dominant_frequency"),
            pole_pairs=resolved_pp,
            already_mechanical_hz=False,
        )
        if v is not None and v > 0:
            out.append(float(v))
    return out


def build_motor_harmonic_reference_lines(
    erpm_analysis: dict | None,
    *,
    motor_poles: Any = None,
    pole_pairs: Any = None,
) -> list[tuple[float, int]]:
    """
    Expected motor harmonic frequencies (Hz) and harmonic order n (peak ≈ n × f0).

    Lines are deduplicated when closer than 1 Hz, keeping the lower harmonic order.
    """
    f0s = motor_fundamentals_hz(
        erpm_analysis,
        motor_poles=motor_poles,
        pole_pairs=pole_pairs,
    )
    if not f0s:
        return []
    raw: list[tuple[float, int]] = []
    for f0 in f0s:
        for n in range(1, _MAX_HARMONIC_ORDER + 1):
            hz = n * f0
            if _PEAK_FREQ_MIN < hz < _PEAK_FREQ_MAX:
                raw.append((float(hz), int(n)))
    raw.sort(key=lambda t: t[0])
    merged: list[tuple[float, int]] = []
    for hz, n in raw:
        if merged and abs(hz - merged[-1][0]) < 1.0:
            if n < merged[-1][1]:
                merged[-1] = (hz, n)
            continue
        merged.append((hz, n))
    return merged


def harmonic_match_tolerance_hz(expected_hz: float) -> float:
    """Absolute window (Hz) for matching a peak to an expected harmonic; within ~5–10 Hz spec."""
    e = abs(expected_hz)
    if not math.isfinite(e) or e <= 0:
        return 8.0
    return max(5.0, min(10.0, 0.025 * e))


def classify_peak_against_motor_harmonics(
    peak_hz: float,
    reference_lines: list[tuple[float, int]],
) -> tuple[str, int | None]:
    """
    Return (PEAK_TYPE_MOTOR, n) if peak aligns with a reference harmonic, else (PEAK_TYPE_FRAME, None).
    Chooses the reference with smallest frequency error; ties break on lower harmonic order.
    """
    if not reference_lines or not math.isfinite(peak_hz):
        return PEAK_TYPE_FRAME, None
    best: tuple[float, int, float] | None = None  # error, order, ref_hz
    for ref_hz, order in reference_lines:
        tol = harmonic_match_tolerance_hz(ref_hz)
        err = abs(peak_hz - ref_hz)
        if err <= tol:
            cand = (err, order, ref_hz)
            if best is None:
                best = cand
            elif err < best[0]:
                best = cand
            elif err == best[0] and order < best[1]:
                best = cand
    if best is None:
        return PEAK_TYPE_FRAME, None
    return PEAK_TYPE_MOTOR, int(best[1])


def annotate_peaks_with_erpm(
    peaks: list[dict[str, Any]],
    erpm_analysis: dict | None,
    *,
    motor_poles: Any = None,
    pole_pairs: Any = None,
) -> list[dict[str, Any]]:
    """
    Add ``type`` (``motor`` | ``frame``) and ``harmonic_order`` (int or null) to each peak dict.

    Without ERPM or below confidence threshold, all peaks are ``frame`` with null harmonic order.
    Preserves existing keys (``freq``, ``amplitude``, ``bandwidth_hz``).
    """
    refs: list[tuple[float, int]] = []
    if isinstance(erpm_analysis, dict):
        conf = float(erpm_analysis.get("confidence") or 0.0)
        if conf >= _ERPM_CONFIDENCE_MIN:
            refs = build_motor_harmonic_reference_lines(
                erpm_analysis,
                motor_poles=motor_poles,
                pole_pairs=pole_pairs,
            )
    out: list[dict[str, Any]] = []
    for p in peaks:
        d = dict(p)
        f = float(d.get("freq", 0.0) or 0.0)
        ptype, ho = classify_peak_against_motor_harmonics(f, refs)
        d["type"] = ptype
        d["harmonic_order"] = ho
        out.append(d)
    return out


def _bandwidth_half_max(
    freqs: np.ndarray,
    spectrum: np.ndarray,
    peak_i: int,
) -> float:
    """Width (Hz) between outermost bins still ≥ 50% of peak amplitude."""
    peak_amp = float(spectrum[peak_i])
    freq = float(freqs[peak_i])
    if peak_amp <= 0 or not math.isfinite(peak_amp):
        return max(1.0, abs(freq) * 0.2)
    half = peak_amp * 0.5
    n = len(spectrum)
    i = peak_i
    while i > 0 and spectrum[i - 1] >= half:
        i -= 1
    left_bound = i
    j = peak_i
    while j < n - 1 and spectrum[j + 1] >= half:
        j += 1
    right_bound = j
    bw = float(freqs[right_bound]) - float(freqs[left_bound])
    if not math.isfinite(bw) or bw <= 0:
        return max(1.0, abs(freq) * 0.2)
    return bw


def detect_resonance_peaks(
    freqs: np.ndarray,
    spectrum: np.ndarray,
    threshold_multiplier: float = 3.0,
) -> list[dict[str, Any]]:
    """
    Local maxima above threshold; each peak includes estimated FWHM-style bandwidth (Hz).

    Returns up to six peaks in (_PEAK_FREQ_MIN, _PEAK_FREQ_MAX), sorted by amplitude (desc).
    """
    freqs = np.asarray(freqs, dtype=float)
    spectrum = np.asarray(spectrum, dtype=float)
    if freqs.size < 3 or spectrum.size < 3 or freqs.shape != spectrum.shape:
        return []

    avg = np.mean(spectrum)
    threshold = avg * threshold_multiplier

    raw_indices: list[int] = []
    for i in range(1, len(spectrum) - 1):
        if spectrum[i] > threshold:
            if spectrum[i] > spectrum[i - 1] and spectrum[i] > spectrum[i + 1]:
                raw_indices.append(i)

    candidates: list[dict[str, Any]] = []
    for i in raw_indices:
        f = float(freqs[i])
        if not (_PEAK_FREQ_MIN < f < _PEAK_FREQ_MAX):
            continue
        amp = float(spectrum[i])
        bw = _bandwidth_half_max(freqs, spectrum, i)
        if not math.isfinite(bw) or bw <= 0:
            bw = abs(f) * 0.2
        candidates.append(
            {
                "freq": f,
                "amplitude": amp,
                "bandwidth_hz": float(bw),
            }
        )

    candidates.sort(key=lambda x: x["amplitude"], reverse=True)
    return candidates[:_MAX_PEAKS]


def classify_resonance(peaks: list[Any], erpm_analysis: dict | None = None) -> float | None:
    """
    Dominant resonance frequency (Hz) for frame / notch targeting.

    When ERPM confidence is sufficient, prefers the strongest **frame** peak so motor
    harmonics do not drive static notch center. Falls back to the strongest peak overall.
    """
    if not peaks:
        return None
    dict_peaks: list[dict[str, Any]] = []
    for p in peaks:
        if isinstance(p, dict):
            dict_peaks.append(dict(p))
        elif isinstance(p, (list, tuple)) and len(p) >= 1:
            try:
                fq = float(p[0])
            except (TypeError, ValueError):
                continue
            try:
                aq = float(p[1]) if len(p) > 1 and p[1] is not None else 0.0
            except (TypeError, ValueError):
                aq = 0.0
            dict_peaks.append({"freq": fq, "amplitude": aq})
    if not dict_peaks:
        return None
    annotated = annotate_peaks_with_erpm(dict_peaks, erpm_analysis)
    conf_ok = (
        isinstance(erpm_analysis, dict)
        and float(erpm_analysis.get("confidence") or 0.0) >= _ERPM_CONFIDENCE_MIN
        and bool(build_motor_harmonic_reference_lines(erpm_analysis))
    )
    annotated.sort(key=lambda x: float(x.get("amplitude", 0.0)), reverse=True)
    if conf_ok:
        frames = [p for p in annotated if p.get("type") != PEAK_TYPE_MOTOR]
        if frames:
            return round(float(frames[0]["freq"]), 1)
    main = annotated[0]
    return round(float(main.get("freq", 0.0)), 1)
