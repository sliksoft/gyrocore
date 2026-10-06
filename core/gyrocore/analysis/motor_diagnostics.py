# GyroCore WU4: adapted from AeroTuner backend/analysis/motor_diagnostics.py
"""
Per-motor diagnostics from motor output time series (no ERPM).

Time-domain roughness/imbalance (legacy) plus optional FFT metrics vs merged gyro
and cross-motor robust outliers — tuned conservative to limit false positives.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from gyrocore.analysis.multi_axis_fft import compute_fft, smooth_spectrum
from gyrocore.analysis._support.hardware_profile import get_hardware_profile

_MIN_ROWS = 24
_MIN_FS_HZ = 200.0
# Conservative gates (higher → fewer flags)
_Z_ROUGH_HF = 2.15
_Z_HARM = 2.0
_Z_GYRO_MISMATCH = 2.25
_HARM_RATIO_FACTOR = 1.72
_IMB_ALERT = 78.0
_NOISE_ALERT = 78.0
_HEALTH_BAD = 52.0
_HEALTH_WARN = 74.0
_HIGH_NOISE_RELATIVE_SCORE_SCALE = 0.45
_HIGH_NOISE_IMB_ALERT = 92.0
_HIGH_NOISE_NOISE_ALERT = 92.0


def _to_normalized_motor_array(rows: list[list[float]]) -> np.ndarray | None:
    if not rows or len(rows) < _MIN_ROWS:
        return None
    try:
        arr = np.asarray(rows, dtype=float)
    except (TypeError, ValueError):
        return None
    if arr.ndim != 2 or arr.shape[1] < 2:
        return None
    if float(np.nanmax(arr)) > 100.0:
        arr = (arr - 1000.0) / 1000.0
    arr = np.clip(arr, 0.0, 1.0)
    if not np.all(np.isfinite(arr)):
        return None
    return arr


def _motor_matrix_from_samples(
    samples: list[dict],
    *,
    n_motors: int = 4,
    min_coverage: float = 0.82,
) -> np.ndarray | None:
    """N×n_motors matrix aligned to *samples* order; forward-fill short gaps."""
    if not samples or len(samples) < _MIN_ROWS:
        return None
    n = len(samples)
    mat = np.full((n, n_motors), np.nan, dtype=float)
    for i, s in enumerate(samples):
        if not isinstance(s, dict):
            continue
        m = s.get("motors")
        if not isinstance(m, (list, tuple)) or len(m) < n_motors:
            continue
        try:
            for j in range(n_motors):
                mat[i, j] = float(m[j])
        except (TypeError, ValueError):
            continue
    valid_row = np.isfinite(mat).all(axis=1)
    if float(np.mean(valid_row.astype(float))) < min_coverage:
        return None
    for j in range(n_motors):
        col = mat[:, j].copy()
        if not np.any(np.isfinite(col)):
            return None
        first = np.where(np.isfinite(col))[0][0]
        last = np.where(np.isfinite(col))[0][-1]
        for i in range(first, last + 1):
            if not np.isfinite(col[i]):
                k = i - 1
                while k >= first and not np.isfinite(col[k]):
                    k -= 1
                col[i] = col[k] if k >= first and np.isfinite(col[k]) else col[first]
        mat[:, j] = col
    if float(np.nanmax(mat)) > 100.0:
        mat = (mat - 1000.0) / 1000.0
    mat = np.clip(mat, 0.0, 1.0)
    if not np.all(np.isfinite(mat)):
        return None
    return mat


def _band_energy(freqs: np.ndarray, spec: np.ndarray, lo: float, hi: float) -> float:
    if freqs.size == 0 or spec.size == 0:
        return 0.0
    m = (freqs >= lo) & (freqs <= hi)
    if not np.any(m):
        return 0.0
    s = np.asarray(spec[m], dtype=float)
    return float(np.sum(np.square(s)))


def _harmonic_excess_ratio(freqs: np.ndarray, spec: np.ndarray, f0: float) -> float:
    """(E2+E3)/E1 in small windows — dimensionless roughness of harmonic ladder."""
    if f0 < 35.0 or f0 > 240.0 or freqs.size == 0:
        return 0.0
    nyq = float(freqs[-1]) if freqs.size else 0.0
    w = max(5.0, 0.045 * f0)

    def win(fc: float) -> float:
        if fc + w > nyq * 0.98:
            return 0.0
        lo, hi = max(15.0, fc - w), min(nyq * 0.98, fc + w)
        return _band_energy(freqs, spec, lo, hi)

    e1 = win(f0)
    e2 = win(2.0 * f0)
    e3 = win(3.0 * f0)
    if e1 < 1e-18:
        return 0.0
    return float((e2 + e3) / (e1 + 1e-18))


def _fundamental_hz(freqs: np.ndarray, spec: np.ndarray) -> float:
    """Dominant line in motor command modulation band."""
    if freqs.size < 4:
        return 0.0
    lo = (freqs >= 40.0) & (freqs <= 220.0)
    if not np.any(lo):
        return 0.0
    sub_f = freqs[lo]
    sub_s = np.asarray(spec[lo], dtype=float)
    i = int(np.argmax(sub_s))
    return float(sub_f[i])


def _robust_peer_z(all_vals: list[float], idx: int) -> float:
    n = len(all_vals)
    if n < 3:
        return 0.0
    others = np.asarray([all_vals[k] for k in range(n) if k != idx], dtype=float)
    med = float(np.median(others))
    mad = float(np.median(np.abs(others - med))) + 1e-12
    scale = 1.4826 * mad
    return float((all_vals[idx] - med) / scale)


def _throttle_activity(arr: np.ndarray) -> float:
    if arr.size == 0:
        return 0.0
    m = float(np.median(arr))
    hi = float(np.mean(arr >= max(0.12, m * 0.35)))
    return float(max(0.0, min(1.0, hi)))


def _confidence_from_context(n_samples: int, throttle_act: float, spectral_ok: bool) -> float:
    base = 0.42 + 0.38 * min(1.0, n_samples / 2500.0) + 0.12 * throttle_act
    if spectral_ok:
        base += 0.08
    return float(max(0.25, min(0.97, base)))


def _hardware_profile_uses_relaxed_relative_motor_noise(
    hardware_class: str | None,
) -> bool:
    profile = get_hardware_profile(hardware_class)
    if profile is None:
        return False
    return bool(
        profile.ducted is True
        or str(profile.noise_expectation).strip().lower() == "high"
    )


def _human_motor_summary(motors_out: list[dict[str, Any]]) -> str:
    """Short, user-facing explanation for API / UI (no raw metrics)."""
    if not motors_out:
        return (
            "No per-motor breakdown was available for this log.\n\n"
            "→ Action:\n"
            "• Re-log with motor debug enabled if your firmware supports it."
        )
    statuses = [str(m.get("status") or "good") for m in motors_out]
    if any(s == "bad" for s in statuses):
        return (
            "Motor correction demand looks elevated in this log.\n\n"
            "→ Possible factors:\n"
            "• Aggressive stick inputs or racing maneuvers\n"
            "• Possible prop or bolt imbalance\n"
            "• Possible vibration or bearing wear\n"
            "• Possible prop mismatch, loose frame parts, or soft mounting\n\n"
            "→ Action:\n"
            "Use a shorter controlled tuning flight to confirm; inspect motors only if imbalance persists."
        )
    if any(s == "warning" for s in statuses):
        return (
            "Some motors look uneven compared with the others.\n\n"
            "→ Action:\n"
            "Balance props, confirm ESC alignment, and re-log before large PID moves."
        )
    return (
        "Motors look evenly behaved in this log.\n\n"
        "→ Action:\n"
        "Keep routine checks on props and bearings; you can tune from this baseline."
    )


def compute_per_motor_diagnostics(
    motor_rows: list[list[float]],
    *,
    samples: list[dict] | None = None,
    spectral_bundle: dict[str, Any] | None = None,
    hardware_class: str | None = None,
    hardware_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Per-motor noise, imbalance, optional spectral issues vs gyro and peers.

    Returns:
        {
          "motors": [{ "id", "health", "noise", "status", "issues", "confidence" }, ...],
          "worst_motor_id": int | None,
        }

    ``health`` / ``noise`` remain 0–100 (legacy). ``status`` is good | warning | bad.
    """
    if hardware_class is None and isinstance(hardware_context, dict):
        hardware_class = hardware_context.get("hardware_class")
    relaxed_relative_noise = _hardware_profile_uses_relaxed_relative_motor_noise(
        hardware_class
    )
    arr_legacy = _to_normalized_motor_array(motor_rows)
    if arr_legacy is None:
        return {
            "motors": [],
            "worst_motor_id": None,
            "summary": _human_motor_summary([]),
        }

    n_motors = int(arr_legacy.shape[1])
    arr = arr_legacy
    if samples:
        mat = _motor_matrix_from_samples(samples, n_motors=n_motors)
        if mat is not None and mat.shape == arr_legacy.shape:
            arr = mat

    n_samples, n_motors = arr.shape

    noise_raw: list[float] = []
    for j in range(n_motors):
        col = arr[:, j]
        d = np.diff(col)
        if d.size == 0:
            noise_raw.append(0.0)
            continue
        mad = float(np.median(np.abs(d)))
        level = float(np.median(np.abs(col)) + 1e-6)
        noise_raw.append(mad / level)

    max_nr = max(noise_raw) if noise_raw else 1e-9
    noise_scores = [min(100.0, 100.0 * (nr / (max_nr + 1e-9))) for nr in noise_raw]

    row_mean = np.mean(arr, axis=1, keepdims=True)
    dev = np.abs(arr - row_mean)
    imb_raw = [float(np.mean(dev[:, j])) for j in range(n_motors)]
    max_ir = max(imb_raw) if imb_raw else 1e-9
    imbalance_scores = [min(100.0, 100.0 * (ir / (max_ir + 1e-9))) for ir in imb_raw]
    scoring_noise_scores = list(noise_scores)
    scoring_imbalance_scores = list(imbalance_scores)
    imb_alert = _IMB_ALERT
    noise_alert = _NOISE_ALERT
    if relaxed_relative_noise:
        scoring_noise_scores = [
            min(100.0, ns * _HIGH_NOISE_RELATIVE_SCORE_SCALE)
            for ns in scoring_noise_scores
        ]
        scoring_imbalance_scores = [
            min(100.0, imb * _HIGH_NOISE_RELATIVE_SCORE_SCALE)
            for imb in scoring_imbalance_scores
        ]
        imb_alert = _HIGH_NOISE_IMB_ALERT
        noise_alert = _HIGH_NOISE_NOISE_ALERT

    motors_out: list[dict[str, Any]] = []
    for j in range(n_motors):
        imb = scoring_imbalance_scores[j]
        ns = scoring_noise_scores[j]
        h = 100.0 - 0.55 * imb - 0.45 * ns
        h = float(max(0.0, min(100.0, h)))
        motors_out.append(
            {
                "id": j + 1,
                "health": round(h, 1),
                "noise": round(ns, 1),
                "status": "good",
                "issues": [],
                "confidence": 0.5,
            }
        )

    throttle_act = _throttle_activity(arr)
    spectral_ok = False
    rough_ratio: list[float] = [0.0] * n_motors
    harm_ratio: list[float] = [0.0] * n_motors
    motor_over_gyro_hf: list[float] = [0.0] * n_motors

    use_spectral = (
        spectral_bundle is not None
        and samples is not None
        and len(samples) == n_samples
    )
    if use_spectral:
        try:
            fs = float(spectral_bundle.get("fs") or 0.0)
            gf = np.asarray(spectral_bundle.get("merged_freqs") or [], dtype=float)
            gs = np.asarray(spectral_bundle.get("merged_spectrum") or [], dtype=float)
        except (TypeError, ValueError):
            fs, gf, gs = 0.0, np.array([]), np.array([])

        if (
            fs >= _MIN_FS_HZ
            and gf.size > 8
            and gs.size == gf.size
            and n_samples >= _MIN_ROWS
        ):
            spectral_ok = True
            gs = smooth_spectrum(gs)
            nyq = float(gf[-1])
            hf_lo, hf_hi = 160.0, min(420.0, nyq * 0.92)
            mid_lo, mid_hi = 45.0, 150.0
            e_gyro_hf = _band_energy(gf, gs, hf_lo, hf_hi) + 1e-18

            for j in range(n_motors):
                col = arr[:, j].astype(float)
                col = col - float(np.mean(col))
                f_m, s_m = compute_fft(col, fs)
                if f_m.size < 8:
                    continue
                s_m = smooth_spectrum(s_m)
                e_hf = _band_energy(f_m, s_m, hf_lo, hf_hi)
                e_mid = _band_energy(f_m, s_m, mid_lo, mid_hi) + 1e-18
                rough_ratio[j] = float(e_hf / e_mid)

                f0 = _fundamental_hz(f_m, s_m)
                harm_ratio[j] = _harmonic_excess_ratio(f_m, s_m, f0) if f0 > 0 else 0.0
                motor_over_gyro_hf[j] = float(e_hf / e_gyro_hf)

    if spectral_ok and n_motors >= 2:
        med_harm = float(np.median([h for h in harm_ratio if h > 0] or [0.0]))
        for j in range(n_motors):
            issues_acc: list[str] = list(motors_out[j]["issues"])
            rz = _robust_peer_z(rough_ratio, j)
            if rz >= _Z_ROUGH_HF and rough_ratio[j] > 0.18:
                issues_acc.append("broadband_noise")

            hz = _robust_peer_z(harm_ratio, j)
            if (
                hz >= _Z_HARM
                and harm_ratio[j] > 0.08
                and med_harm > 0.04
                and harm_ratio[j] > med_harm * _HARM_RATIO_FACTOR
            ):
                issues_acc.append("abnormal_harmonics")

            gz = _robust_peer_z(motor_over_gyro_hf, j)
            if gz >= _Z_GYRO_MISMATCH and motor_over_gyro_hf[j] > 3.2:
                issues_acc.append("motor_gyro_mismatch")

            motors_out[j]["issues"] = list(dict.fromkeys(issues_acc))

    max_imb_i = int(np.argmax(imbalance_scores)) if imbalance_scores else -1
    max_ns_i = int(np.argmax(noise_scores)) if noise_scores else -1
    for j in range(n_motors):
        issues = list(motors_out[j]["issues"])
        if max_imb_i == j and scoring_imbalance_scores[j] >= imb_alert:
            issues.append("imbalance")
        if max_ns_i == j and scoring_noise_scores[j] >= noise_alert:
            issues.append("noise")
        motors_out[j]["issues"] = list(dict.fromkeys(issues))

    for j in range(n_motors):
        conf = _confidence_from_context(n_samples, throttle_act, spectral_ok)
        motors_out[j]["confidence"] = round(conf, 3)
        issues = motors_out[j]["issues"]
        h = float(motors_out[j]["health"])
        if h < _HEALTH_BAD or len(issues) >= 2:
            motors_out[j]["status"] = "bad"
        elif h < _HEALTH_WARN or len(issues) == 1:
            motors_out[j]["status"] = "warning"
        else:
            motors_out[j]["status"] = "good"

    worst_id: int | None = None
    if motors_out:
        _ord = {"bad": 0, "warning": 1, "good": 2}
        rank = sorted(
            range(n_motors),
            key=lambda j: (
                _ord[str(motors_out[j]["status"])],
                float(motors_out[j]["health"]),
                -len(motors_out[j]["issues"]),
            ),
        )
        worst_id = int(motors_out[rank[0]]["id"])

    return {
        "motors": motors_out,
        "worst_motor_id": worst_id,
        "summary": _human_motor_summary(motors_out),
    }
