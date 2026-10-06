# GyroCore WU4: adapted from AeroTuner backend/analysis/precap_spectral_features.py
"""
Pre-cap dense window extraction for tuning-critical spectral/RPM evidence.

Computes compact spectral features from a contiguous dense window of the
full (pre-cap) blackbox log, BEFORE the 20k evenly-spaced subsample cap.
These features supplement capped-window analysis for phase2 signal path,
resonance detection, and RPM alignment — they do NOT replace the main
FFT/resonance pipeline and do NOT change any safety gate thresholds.

Only activated when original_sample_count > MAX_PARSED_SAMPLES (spill).
Falls back safely to {"available": False} on any error or identity mismatch.

Window selection (v2): activity-based sliding-window scoring that evaluates
up to PRECAP_MAX_EVALUATED_WINDOWS candidate positions ranked by gyro/throttle/
ERPM activity. Falls back to skip-first-10% when no window reaches
PRECAP_ACTIVITY_SCORE_MIN.
"""

from __future__ import annotations

import csv
import logging
import math
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

PRECAP_WINDOW_TARGET = 6000
PRECAP_WINDOW_MIN = 128
PRECAP_SKIP_FRACTION = 0.10          # fallback: skip first N% of rows (arm/idle zone)
PRECAP_MAX_SCAN_ROWS = 200_000        # cap on valid rows collected for activity scan
PRECAP_MAX_EVALUATED_WINDOWS = 30     # cap on scored candidate windows
PRECAP_WINDOW_STRIDE_MIN = 1000       # minimum stride between candidate windows
PRECAP_ACTIVITY_SCORE_MIN = 0.20      # minimum score to prefer activity window over fallback
_PRECAP_VERSION = "precap_v1"

_NAN = float("nan")


# ---------------------------------------------------------------------------
# Minimal row parser — only t, gx, gy, gz, throttle, erpm
# ---------------------------------------------------------------------------

def _read_float(row: list[str], idx: int | None) -> float | None:
    if idx is None or len(row) <= idx:
        return None
    try:
        val = row[idx].strip()
        return float(val) if val else None
    except (ValueError, TypeError):
        return None


def _build_minimal_row_parser(headers: list[str]):
    """Return (parse_fn, ok) where parse_fn(row_number, line) → dict | None."""
    from gyrocore.parse.blackbox_csv import (
        find_index,
        find_time_column_index,
        GYRO_ALIASES,
        GYRO_Y_ALIASES,
        GYRO_Z_ALIASES,
        THROTTLE_ALIASES,
        ERPM_SINGLE_ALIASES,
        ERPM_MOTOR_ALIASES,
    )

    gx_i = find_index(headers, GYRO_ALIASES)
    gy_i = find_index(headers, GYRO_Y_ALIASES)
    gz_i = find_index(headers, GYRO_Z_ALIASES)
    if gx_i is None or gy_i is None or gz_i is None:
        return None, False

    t_i = find_time_column_index(headers)
    thr_i = find_index(headers, THROTTLE_ALIASES)
    erpm_s_i = find_index(headers, ERPM_SINGLE_ALIASES)
    erpm_m_idxs: list[int | None] = [find_index(headers, grp) for grp in ERPM_MOTOR_ALIASES]

    max_req = max(i for i in (gx_i, gy_i, gz_i) if i is not None)

    def _parse_row(row_number: int, line: str) -> dict | None:
        if "," not in line:
            return None
        try:
            row = next(csv.reader([line]))
        except Exception:
            return None
        if len(row) <= max_req:
            return None
        gx = _read_float(row, gx_i)
        gy = _read_float(row, gy_i)
        gz = _read_float(row, gz_i)
        if gx is None or gy is None or gz is None:
            return None

        t_val: int | float = row_number
        if t_i is not None and len(row) > t_i:
            try:
                raw = row[t_i].strip()
                if raw:
                    t_val = int(float(raw))
            except (ValueError, TypeError):
                pass

        throttle = _read_float(row, thr_i)

        erpm: list[float | None] | None = None
        if erpm_s_i is not None:
            v = _read_float(row, erpm_s_i)
            if v is not None:
                erpm = [v, v, v, v]
        elif any(mi is not None for mi in erpm_m_idxs):
            vals: list[float | None] = [_read_float(row, mi) for mi in erpm_m_idxs]
            if any(v is not None for v in vals):
                erpm = vals

        return {"t": t_val, "gx": gx, "gy": gy, "gz": gz, "throttle": throttle, "erpm": erpm}

    return _parse_row, True


# ---------------------------------------------------------------------------
# Activity scoring for a window candidate
# ---------------------------------------------------------------------------

def _score_window_candidate(
    compact_rows: list,
    start: int,
    end: int,
    gyro_idle_threshold: float,
    thr_idle_threshold: float,
) -> tuple[float, dict]:
    """Score candidate window [start:end] from compact_rows.

    Each compact_rows item is an 8-tuple:
      (t_val, gyro_mag, throttle_f, has_erpm, gx, gy, gz, erpm_raw)

    Scoring weights (sub-scores in [0, 1]):
      gyro activity     0.45  (dominant: is the drone flying?)
      throttle activity 0.25  (above idle; neutral 0.5 when no throttle column)
      ERPM coverage     0.15  (motor RPM data present)
      timestamp quality 0.10  (penalise large gaps)
      valid density     0.05  (window near target size)

    Returns (total_score, sub_scores_dict).
    """
    n = end - start
    if n < PRECAP_WINDOW_MIN:
        return 0.0, {}

    gyro_active = 0
    thr_active = 0
    thr_present = 0
    erpm_count = 0
    t_list: list[float] = []

    for i in range(start, end):
        row = compact_rows[i]
        t_val, gyro_mag, throttle_f, has_erpm = row[0], row[1], row[2], row[3]
        if gyro_mag > gyro_idle_threshold:
            gyro_active += 1
        if not math.isnan(throttle_f):
            thr_present += 1
            if not math.isnan(thr_idle_threshold) and throttle_f > thr_idle_threshold:
                thr_active += 1
        if has_erpm:
            erpm_count += 1
        if math.isfinite(t_val):
            t_list.append(t_val)

    gyro_activity_score = gyro_active / n
    throttle_activity_score = (thr_active / thr_present) if thr_present > 0 else 0.5
    erpm_coverage_score = erpm_count / n

    # Timestamp quality: penalise max gap relative to median monotone gap
    if len(t_list) >= 2:
        pos_diffs = sorted(
            t_list[j + 1] - t_list[j]
            for j in range(len(t_list) - 1)
            if t_list[j + 1] > t_list[j]
        )
        if pos_diffs:
            median_dt = pos_diffs[len(pos_diffs) // 2]
            max_dt = pos_diffs[-1]
            if median_dt > 0:
                ratio = max_dt / median_dt
                timestamp_quality_score = 1.0 / (1.0 + ratio / 10.0)
            else:
                timestamp_quality_score = 0.5
        else:
            timestamp_quality_score = 0.5  # row_number fallback — constant gaps
    else:
        timestamp_quality_score = 0.3

    valid_density = min(1.0, n / PRECAP_WINDOW_TARGET)

    total = (
        0.45 * gyro_activity_score
        + 0.25 * throttle_activity_score
        + 0.15 * erpm_coverage_score
        + 0.10 * timestamp_quality_score
        + 0.05 * valid_density
    )

    return total, {
        "gyro_activity_score": round(gyro_activity_score, 4),
        "throttle_activity_score": round(throttle_activity_score, 4),
        "erpm_coverage_score": round(erpm_coverage_score, 4),
        "timestamp_quality_score": round(timestamp_quality_score, 4),
    }


# ---------------------------------------------------------------------------
# Dense window extraction
# ---------------------------------------------------------------------------

def extract_dense_window_from_lines(
    data_lines: list[str],
    headers: list[str],
    *,
    total_count: int,
    target_size: int = PRECAP_WINDOW_TARGET,
) -> tuple[list[dict], dict[str, Any]]:
    """Extract a contiguous dense window from raw CSV data lines.

    Pass 1 parses up to PRECAP_MAX_SCAN_ROWS rows into compact 8-tuples
    (no full dicts) and tracks global gyro/throttle stats for normalised
    activity thresholds.

    Pass 2 evaluates up to PRECAP_MAX_EVALUATED_WINDOWS candidate windows
    with an adaptive stride, scores each by gyro/throttle/ERPM activity,
    and selects the best.  Falls back to skip-first-10% when the best score
    is below PRECAP_ACTIVITY_SCORE_MIN.

    Full dict materialisation happens only for the winning window.

    Returns (window_samples, window_metadata).
    """
    parse_row, has_gyro = _build_minimal_row_parser(headers)
    if not has_gyro or parse_row is None:
        return [], {
            "error": "no_gyro_columns",
            "selection_method": "skip_idle_edges",
            "window_selection_strategy": "fallback_skip_10_percent",
        }

    # ---- Pass 1: compact row collection ----
    # 8-tuple: (t_val, gyro_mag, throttle_f, has_erpm, gx, gy, gz, erpm_raw)
    compact_rows: list = []
    global_gyro_max = 0.0
    global_thr_min = math.inf
    global_thr_max = -math.inf

    for row_number, line in enumerate(data_lines, start=1):
        if len(compact_rows) >= PRECAP_MAX_SCAN_ROWS:
            break
        s = parse_row(row_number, line)
        if s is None:
            continue

        gx = float(s["gx"])
        gy = float(s["gy"])
        gz = float(s["gz"])
        gyro_mag = math.sqrt(gx * gx + gy * gy + gz * gz)

        thr = s.get("throttle")
        throttle_f: float = float(thr) if thr is not None else _NAN

        erpm = s.get("erpm")
        has_erpm: bool = isinstance(erpm, (list, tuple)) and any(v is not None for v in erpm)

        t_val = float(s["t"])

        compact_rows.append((t_val, gyro_mag, throttle_f, has_erpm, gx, gy, gz, erpm))

        if gyro_mag > global_gyro_max:
            global_gyro_max = gyro_mag
        if not math.isnan(throttle_f):
            if throttle_f < global_thr_min:
                global_thr_min = throttle_f
            if throttle_f > global_thr_max:
                global_thr_max = throttle_f

    n_valid = len(compact_rows)
    if n_valid < PRECAP_WINDOW_MIN:
        return [], {
            "error": "too_few_valid_samples",
            "total_count": total_count,
            "selection_method": "skip_idle_edges",
            "window_selection_strategy": "fallback_skip_10_percent",
            "window_score": 0.0,
            "evaluated_window_count": 0,
            "fallback_reason": "too_few_samples",
        }

    # ---- Activity thresholds (relative to log-global stats) ----
    gyro_idle_threshold = max(0.5, 0.05 * global_gyro_max)
    if math.isfinite(global_thr_min) and math.isfinite(global_thr_max):
        thr_range = global_thr_max - global_thr_min
        thr_idle_threshold = global_thr_min + 0.10 * thr_range
    else:
        thr_idle_threshold = _NAN  # no throttle column

    # ---- Pass 2: score candidate windows ----
    actual_window = min(target_size, n_valid)
    stride = max(PRECAP_WINDOW_STRIDE_MIN, n_valid // PRECAP_MAX_EVALUATED_WINDOWS)

    best_score = -1.0
    best_start = -1
    best_sub: dict = {}
    evaluated_count = 0

    pos = 0
    while pos + actual_window <= n_valid and evaluated_count < PRECAP_MAX_EVALUATED_WINDOWS:
        score, sub = _score_window_candidate(
            compact_rows, pos, pos + actual_window,
            gyro_idle_threshold, thr_idle_threshold,
        )
        if score > best_score:
            best_score = score
            best_start = pos
            best_sub = sub
        pos += stride
        evaluated_count += 1

    # ---- Select window ----
    fallback_reason: str | None = None
    if best_start >= 0 and best_score >= PRECAP_ACTIVITY_SCORE_MIN:
        strategy = "activity_score"
        win_start = best_start
    else:
        strategy = "fallback_skip_10_percent"
        win_start = max(0, int(n_valid * PRECAP_SKIP_FRACTION))
        fallback_reason = (
            f"low_activity_score:{best_score:.3f}" if best_start >= 0 else "no_window_found"
        )
        # Re-score fallback window so metadata has meaningful sub-scores
        fb_end = min(win_start + actual_window, n_valid)
        _fb_score, best_sub = _score_window_candidate(
            compact_rows, win_start, fb_end,
            gyro_idle_threshold, thr_idle_threshold,
        )
        if _fb_score > best_score:
            best_score = _fb_score

    win_end = min(win_start + actual_window, n_valid)

    # ---- Materialise winning window as full dicts ----
    window_samples: list[dict] = []
    for i in range(win_start, win_end):
        t_v, _gm, thr_f, _he, gx, gy, gz, erpm = compact_rows[i]
        window_samples.append({
            "t": t_v,
            "gx": gx,
            "gy": gy,
            "gz": gz,
            "throttle": None if math.isnan(thr_f) else thr_f,
            "erpm": erpm,
        })

    meta: dict[str, Any] = {
        # Backward-compatible keys (unchanged names)
        "total_count": total_count,
        "window_start_row": win_start,
        "window_end_row": win_end,
        "window_size": len(window_samples),
        "selection_method": strategy,
        "skip_fraction": PRECAP_SKIP_FRACTION,
        # New diagnostic keys
        "window_selection_strategy": strategy,
        "window_score": round(best_score, 4) if best_score >= 0 else None,
        "evaluated_window_count": evaluated_count,
        "fallback_reason": fallback_reason,
        **best_sub,
    }
    return window_samples, meta


# ---------------------------------------------------------------------------
# Spectral peak extraction from the dense window
# ---------------------------------------------------------------------------

def _compute_gyro_spectral_peaks(
    window_samples: list[dict],
    sample_rate_hz: float,
    max_peaks: int = 8,
) -> list[dict[str, Any]]:
    """Dominant FFT peaks from the dense window gyro axes.

    Uses the same per_axis_smoothed_spectra + detect_resonance_peaks path as
    the main pipeline so peak positions are directly comparable.
    """
    try:
        from gyrocore.analysis.multi_axis_fft import per_axis_smoothed_spectra
        from gyrocore.analysis.resonance_v2 import detect_resonance_peaks
    except ImportError:
        return []

    gx = np.asarray([float(s.get("gx", 0.0)) for s in window_samples], dtype=float)
    gy = np.asarray([float(s.get("gy", 0.0)) for s in window_samples], dtype=float)
    gz = np.asarray([float(s.get("gz", 0.0)) for s in window_samples], dtype=float)

    if gx.size < 64:
        return []

    axes_spectra = per_axis_smoothed_spectra(gx, gy, gz, fs=sample_rate_hz, remove_dc=False)

    all_peaks: list[dict[str, Any]] = []

    for axis_name, (freqs, spectrum) in axes_spectra.items():
        fq = np.asarray(freqs, dtype=float)
        sp = np.asarray(spectrum, dtype=float)
        if fq.size == 0 or not bool(np.any(sp)):
            continue
        try:
            peaks = detect_resonance_peaks(fq, sp)
            for p in peaks or []:
                if not isinstance(p, dict):
                    continue
                freq = float(p.get("freq", 0.0) or 0.0)
                if freq < 5.0 or freq > sample_rate_hz / 2.0:
                    continue
                all_peaks.append({
                    "freq_hz": round(freq, 2),
                    "amplitude": round(float(p.get("amplitude", 0.0) or 0.0), 4),
                    "axis": axis_name,
                })
        except Exception as exc:
            logger.debug("precap FFT failed axis=%s: %s", axis_name, exc)

    # Deduplicate: keep highest-amplitude peak per 3-Hz bin
    all_peaks.sort(key=lambda p: -p["amplitude"])
    unique: list[dict[str, Any]] = []
    seen_hz: list[float] = []
    for p in all_peaks:
        if any(abs(p["freq_hz"] - h) < 3.0 for h in seen_hz):
            continue
        unique.append(p)
        seen_hz.append(p["freq_hz"])
        if len(unique) >= max_peaks:
            break

    return unique


# ---------------------------------------------------------------------------
# ERPM → Hz summary from the dense window
# ---------------------------------------------------------------------------

def _compute_erpm_hz_summary(window_samples: list[dict]) -> dict[str, Any]:
    """Convert raw eRPM values in the dense window to electrical Hz summary."""
    raw_vals: list[float] = []
    for s in window_samples:
        erpm_row = s.get("erpm")
        if not isinstance(erpm_row, (list, tuple)):
            continue
        for v in erpm_row:
            if v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fv) and fv > 0:
                raw_vals.append(fv)

    if not raw_vals:
        return {"available": False}

    mean_raw = sum(raw_vals) / len(raw_vals)
    scale = 100.0 if mean_raw < 10000.0 else 1.0
    hz_vals = [
        v * scale / 60.0
        for v in raw_vals
        if math.isfinite(v * scale / 60.0) and v * scale / 60.0 > 0
    ]

    if not hz_vals:
        return {"available": False}

    mean_hz = sum(hz_vals) / len(hz_vals)
    hz_sorted = sorted(hz_vals)
    mid = len(hz_sorted) // 2
    median_hz = hz_sorted[mid]

    return {
        "available": True,
        "mean_hz": round(mean_hz, 2),
        "median_hz": round(median_hz, 2),
        "sample_count": len(hz_vals),
        "erpm_scale_used": scale,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_precap_spectral_features(
    window_samples: list[dict],
    *,
    log_index: int | None,
    original_count: int,
    window_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Compute compact spectral/RPM features from a pre-cap dense window.

    Returns a feature dict with ``available=True`` on success; falls back
    to ``available=False`` on any exception.
    """
    if not window_samples:
        return get_fallback_precap_features("empty_window")

    try:
        from gyrocore.analysis.signal import compute_sample_rate, time_us_to_seconds

        time_s = time_us_to_seconds([float(s.get("t", 0.0)) for s in window_samples])
        sample_rate_hz = float(compute_sample_rate(time_s))
        quality_flags: list[str] = []
        if not math.isfinite(sample_rate_hz) or sample_rate_hz < 50:
            sample_rate_hz = 1000.0
            quality_flags.append("sample_rate_fallback")

        gyro_peaks = _compute_gyro_spectral_peaks(window_samples, sample_rate_hz)
        erpm_summary = _compute_erpm_hz_summary(window_samples)

        if not gyro_peaks:
            quality_flags.append("no_gyro_peaks_detected")

        # Flag low-activity window (activity score below a warn threshold)
        window_score = window_metadata.get("window_score")
        if isinstance(window_score, float) and window_score < 0.30:
            quality_flags.append("low_activity_window")

        return {
            "available": True,
            "source": "pre_cap_dense",
            "version": _PRECAP_VERSION,
            "log_index": log_index,
            "raw_sample_count": original_count,
            "spectral_sample_count": len(window_samples),
            "source_kind": "high_rate_slice",
            "window_metadata": window_metadata,
            "sample_rate_hz": round(sample_rate_hz, 2),
            "nyquist_hz": round(sample_rate_hz / 2.0, 2),
            "gyro_spectral_peaks": gyro_peaks,
            "erpm_motor_hz_summary": erpm_summary,
            "motor_poles": None,
            "pole_pairs": None,
            "quality_flags": quality_flags,
            "fallback_reasons": [],
        }
    except Exception as exc:
        logger.warning("compute_precap_spectral_features failed: %s", exc)
        return get_fallback_precap_features(f"exception:{type(exc).__name__}")


def get_fallback_precap_features(reason: str) -> dict[str, Any]:
    """Null-object precap features (safe fallback when extraction fails)."""
    return {
        "available": False,
        "source": "fallback",
        "version": _PRECAP_VERSION,
        "log_index": None,
        "fallback_reason": reason,
        "gyro_spectral_peaks": [],
        "erpm_motor_hz_summary": {"available": False},
        "quality_flags": [],
        "fallback_reasons": [reason],
    }


def validate_precap_identity(
    precap_features: dict[str, Any] | None,
    selected_log_index: int | None,
    *,
    decoded_log_index: int | None = None,
) -> tuple[bool, str | None]:
    """Check whether pre-cap features match the selected embedded log index.

    Returns (is_valid, failure_reason).

    ``stored_idx`` is the log_index bound at parse time (None when upload
    called parse_blackbox_csv without log_index).  ``selected_log_index``
    is what the caller wants to analyse.  ``decoded_log_index`` is what
    session["parsed"]["decoded_embedded_log_index"] says was actually decoded.

    Rules:
    - If stored_idx is not None: must equal selected_log_index.
    - If stored_idx is None and selected_log_index is None: single-log → valid.
    - If stored_idx is None and selected_log_index is not None: the features
      came from upload-time parse (no log_index tag).  Safe only when
      decoded_log_index matches selected_log_index (both refer to same log).
      If decoded_log_index is unknown: reject to avoid multi-log cross-use.
    """
    if not isinstance(precap_features, dict):
        return False, "precap_not_a_dict"
    if not precap_features.get("available"):
        return False, "precap_unavailable:{}".format(
            precap_features.get("fallback_reason", "unknown")
        )
    stored_idx = precap_features.get("log_index")

    if stored_idx is not None:
        if selected_log_index is None or int(stored_idx) == int(selected_log_index):
            return True, None
        return False, f"log_index_mismatch:{stored_idx}!={selected_log_index}"

    # stored_idx is None (upload-time parse, log_index not tagged)
    if selected_log_index is None:
        return True, None  # single-log session

    # Multi-log: validate via decoded_log_index (the log actually decoded)
    if decoded_log_index is not None:
        if int(decoded_log_index) == int(selected_log_index):
            return True, None
        return False, f"decoded_log_mismatch:{decoded_log_index}!={selected_log_index}"

    return False, "stored_log_index_unknown_multi_log"
