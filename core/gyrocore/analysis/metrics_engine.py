# GyroCore WU4: adapted from AeroTuner backend/analysis/metrics_engine.py
"""
Central metrics aggregation — single structured output for analysis consumers.

Aggregates noise (noise_model + optional FFT), resonance, propwash, motor
diagnostics, and simple setpoint–gyro tracking metrics.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from gyrocore.analysis.d_effectiveness_analysis import analyze_d_effectiveness
from gyrocore.analysis.multi_axis_fft import per_axis_smoothed_spectra
from gyrocore.analysis.noise_model import compute_noise_score
from gyrocore.analysis.step_response_analysis import analyze_step_response
from gyrocore.analysis.signal import compute_sample_rate, time_us_to_seconds

_AXIS_D_ALIASES: tuple[tuple[str, ...], ...] = (
    ("axisD[0]", "axisd[0]", "axisD_roll", "axis_d_roll", "dterm_roll", "roll_d"),
    ("axisD[1]", "axisd[1]", "axisD_pitch", "axis_d_pitch", "dterm_pitch", "pitch_d"),
    ("axisD[2]", "axisd[2]", "axisD_yaw", "axis_d_yaw", "dterm_yaw", "yaw_d"),
)


def grade_from_score(score: float) -> str:
    """Map 0–100 cleanliness-style score to letter grade."""
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "D"
    if not np.isfinite(s):
        return "D"
    s = max(0.0, min(100.0, s))
    if s >= 90.0:
        return "A"
    if s >= 75.0:
        return "B"
    if s >= 60.0:
        return "C"
    return "D"


def samples_dict_from_normalized_rows(rows: list[dict]) -> dict[str, Any]:
    """
    Build array bundle from parser-normalized sample dicts (gx/gy/gz, t, throttle,
    motors, setpoint_*). Missing fields become NaN-filled columns.
    """
    empty = {
        "gyro": np.zeros((0, 3), dtype=float),
        "setpoint": np.zeros((0, 3), dtype=float),
        "d_term": np.zeros((0, 3), dtype=float),
        "motors": np.zeros((0, 4), dtype=float),
        "throttle": np.zeros((0,), dtype=float),
        "time_us": np.zeros((0,), dtype=float),
    }
    if not rows:
        return empty

    n = len(rows)
    gyro = np.full((n, 3), np.nan, dtype=float)
    sp = np.full((n, 3), np.nan, dtype=float)
    d_term = np.full((n, 3), np.nan, dtype=float)
    motors = np.full((n, 4), np.nan, dtype=float)
    thr = np.full(n, np.nan, dtype=float)
    t_us = np.full(n, np.nan, dtype=float)

    for i, s in enumerate(rows):
        if not isinstance(s, dict):
            continue
        try:
            gyro[i, 0] = float(s.get("gx", np.nan))
            gyro[i, 1] = float(s.get("gy", np.nan))
            gyro[i, 2] = float(s.get("gz", np.nan))
        except (TypeError, ValueError):
            pass
        for j, key in enumerate(("setpoint_roll", "setpoint_pitch", "setpoint_yaw")):
            raw = s.get(key)
            if raw is not None:
                try:
                    sp[i, j] = float(raw)
                except (TypeError, ValueError):
                    pass
        raw_d = s.get("axisD")
        if isinstance(raw_d, (list, tuple)) and len(raw_d) >= 1:
            for j in range(min(3, len(raw_d))):
                if raw_d[j] is None:
                    continue
                try:
                    d_term[i, j] = float(raw_d[j])
                except (TypeError, ValueError):
                    pass
        else:
            for j, aliases in enumerate(_AXIS_D_ALIASES):
                for key in aliases:
                    raw = s.get(key)
                    if raw is None:
                        continue
                    try:
                        d_term[i, j] = float(raw)
                    except (TypeError, ValueError):
                        pass
                    break
        raw_t = s.get("throttle")
        if raw_t is not None:
            try:
                thr[i] = float(raw_t)
            except (TypeError, ValueError):
                pass
        raw_time = s.get("t")
        if raw_time is not None:
            try:
                t_us[i] = float(raw_time)
            except (TypeError, ValueError):
                pass
        m = s.get("motors")
        if isinstance(m, (list, tuple)) and len(m) >= 1:
            for k in range(min(4, len(m))):
                if m[k] is None:
                    continue
                try:
                    motors[i, k] = float(m[k])
                except (TypeError, ValueError):
                    pass

    return {
        "gyro": gyro,
        "setpoint": sp,
        "d_term": d_term,
        "motors": motors,
        "throttle": thr,
        "time_us": t_us,
    }


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
        if np.isfinite(v):
            return v
    except (TypeError, ValueError):
        pass
    return default


def _sanitize_scalar(x: Any, *, lo: float | None = None, hi: float | None = None) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(v):
        return None
    if lo is not None:
        v = max(float(lo), v)
    if hi is not None:
        v = min(float(hi), v)
    return float(v)


def _get_noise_model_dict(analysis: dict[str, Any]) -> dict[str, Any] | None:
    nm = analysis.get("noise_model")
    if isinstance(nm, dict) and nm:
        return nm
    sig = analysis.get("signal")
    if isinstance(sig, dict):
        inner = sig.get("noise_model")
        if isinstance(inner, dict) and inner:
            return inner
    return None


def _fft_vectors(fft_data: dict[str, Any] | None) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(fft_data, dict):
        return np.array([], dtype=float), np.array([], dtype=float)
    f = fft_data.get("merged_freqs")
    p = fft_data.get("merged_spectrum")
    if f is None:
        ff = fft_data.get("freqs")
        if isinstance(ff, list):
            f = np.asarray(ff, dtype=float)
    if p is None:
        pw = fft_data.get("power")
        if isinstance(pw, list):
            p = np.asarray(pw, dtype=float)
    if f is None or p is None:
        return np.array([], dtype=float), np.array([], dtype=float)
    fa = np.asarray(f, dtype=float)
    pa = np.asarray(p, dtype=float)
    if fa.size == 0 or pa.size == 0 or fa.shape != pa.shape:
        return np.array([], dtype=float), np.array([], dtype=float)
    return fa, pa


def _tracking_block(
    gyro: np.ndarray,
    setpoint: np.ndarray,
    time_us: np.ndarray,
) -> dict[str, float]:
    defaults = {
        "score": 50.0,
        "mean_error": 0.0,
        "latency_ms": 0.0,
        "overshoot": 0.0,
        "source": "insufficient_data",
        "computed": False,
        "confidence": 0.0,
    }
    try:
        g = np.asarray(gyro, dtype=float)
        sp = np.asarray(setpoint, dtype=float)
        if g.ndim != 2 or sp.ndim != 2 or g.shape[1] < 1 or sp.shape != g.shape:
            return defaults
        n = int(min(g.shape[0], sp.shape[0]))
        if n < 8:
            return defaults
        g = g[:n]
        sp = sp[:n]
        roll_sp = sp[:, 0]
        roll_g = g[:, 0]
        if not np.any(np.isfinite(roll_sp)):
            return defaults

        err = sp - g
        err = err[np.all(np.isfinite(err), axis=1)]
        if err.size == 0:
            return defaults
        mean_error = float(np.mean(np.abs(err)))
        m_abs = float(np.max(np.abs(sp)))
        if not np.isfinite(m_abs):
            m_abs = 0.0
        max_setpoint = m_abs + 1e-6
        normalized_error = mean_error / max_setpoint
        score = max(0.0, min(100.0, 100.0 - normalized_error * 100.0))

        fs = 500.0
        if time_us.size >= n:
            tu = np.asarray(time_us[:n], dtype=float)
            if np.all(np.isfinite(tu)) and n > 2:
                ts = time_us_to_seconds(tu.tolist())
                fs_c = float(compute_sample_rate(ts))
                if fs_c > 0.0 and np.isfinite(fs_c):
                    fs = fs_c

        latency_ms = 0.0
        m = int(min(roll_sp.size, roll_g.size))
        sp1 = roll_sp[:m]
        g1 = roll_g[:m]
        mask = np.isfinite(sp1) & np.isfinite(g1)
        if np.sum(mask) > 32:
            sp1 = sp1[mask]
            g1 = g1[mask]
            sp_z = sp1 - float(np.mean(sp1))
            g_z = g1 - float(np.mean(g1))
            std_s = float(np.std(sp_z)) + 1e-9
            std_g = float(np.std(g_z)) + 1e-9
            sp_z = sp_z / std_s
            g_z = g_z / std_g
            corr = np.correlate(sp_z, g_z, mode="full")
            lag = int(np.argmax(corr)) - (sp_z.size - 1)
            latency_ms = abs(float(lag)) / fs * 1000.0
        if not np.isfinite(latency_ms):
            latency_ms = 0.0
        latency_ms = max(0.0, min(latency_ms, 100.0))

        overshoot = _overshoot_roll(sp1, g1)

        return {
            "score": float(score),
            "mean_error": float(mean_error),
            "latency_ms": float(latency_ms),
            "overshoot": float(overshoot),
            "source": "computed",
            "computed": True,
            "confidence": 1.0,
        }
    except Exception:
        return defaults


def _per_axis_tracking_quality(gyro: np.ndarray, setpoint: np.ndarray) -> dict[str, float]:
    """
    Per-axis setpoint–gyro quality 0–100 (higher = better tracking).

    Exposed as ``roll_error``, ``pitch_error``, ``yaw_error`` for tuning (same
    semantics as aggregate ``tracking.score``, not raw RMS error).
    """
    defaults = {
        "roll_error": 50.0,
        "pitch_error": 50.0,
        "yaw_error": 50.0,
    }
    try:
        g = np.asarray(gyro, dtype=float)
        sp = np.asarray(setpoint, dtype=float)
        if g.ndim != 2 or sp.ndim != 2 or g.shape != sp.shape or g.shape[1] < 3:
            return defaults
        n = int(min(g.shape[0], sp.shape[0]))
        if n < 8:
            return defaults
        g = g[:n]
        sp = sp[:n]
        out: dict[str, float] = {}
        for i, name in enumerate(("roll", "pitch", "yaw")):
            key = f"{name}_error"
            spc = sp[:, i]
            gc = g[:, i]
            if not np.any(np.isfinite(spc)):
                out[key] = 50.0
                continue
            mask = np.isfinite(spc) & np.isfinite(gc)
            if int(np.sum(mask)) < 8:
                out[key] = 50.0
                continue
            spc = spc[mask]
            gc = gc[mask]
            err = spc - gc
            mean_error = float(np.mean(np.abs(err)))
            m_abs = float(np.max(np.abs(spc)))
            if not np.isfinite(m_abs):
                m_abs = 0.0
            max_setpoint = m_abs + 1e-6
            normalized_error = mean_error / max_setpoint
            score = max(0.0, min(100.0, 100.0 - normalized_error * 100.0))
            out[key] = float(score)
        return out
    except Exception:
        return defaults


def _per_axis_noise_cleanliness(gyro: np.ndarray, time_us: np.ndarray) -> dict[str, float]:
    """
    Per-axis gyro cleanliness 0–100 (higher = cleaner), from HF energy in each axis spectrum.
    """
    defaults = {
        "roll_noise": 50.0,
        "pitch_noise": 50.0,
        "yaw_noise": 50.0,
    }
    try:
        g = np.asarray(gyro, dtype=float)
        tu = np.asarray(time_us, dtype=float)
        if g.ndim != 2 or g.shape[1] < 3:
            return defaults
        n = int(min(g.shape[0], tu.size))
        if n < 32:
            return defaults
        g = g[:n]
        fs = 500.0
        if tu.size >= n and n > 2:
            ts = time_us_to_seconds(tu[:n].tolist())
            fs_c = float(compute_sample_rate(ts))
            if fs_c > 0.0 and np.isfinite(fs_c):
                fs = fs_c
        gx, gy, gz = g[:, 0], g[:, 1], g[:, 2]
        specs = per_axis_smoothed_spectra(gx, gy, gz, fs, remove_dc=True)
        out: dict[str, float] = {}
        for ax_name, key in (
            ("roll", "roll_noise"),
            ("pitch", "pitch_noise"),
            ("yaw", "yaw_noise"),
        ):
            freqs, spec = specs.get(ax_name, (np.array([]), np.array([])))
            if freqs.size == 0 or spec.size == 0:
                out[key] = 50.0
                continue
            raw = compute_noise_score(freqs, spec)
            noisy = float(raw.get("score", 0.0) or 0.0)
            clean = max(0.0, min(100.0, 100.0 - min(100.0, noisy)))
            out[key] = float(clean)
        return out
    except Exception:
        return defaults


def _overshoot_roll(sp: np.ndarray, gy: np.ndarray) -> float:
    if sp.size < 64 or gy.size < 64:
        return 0.0
    n = int(min(sp.size, gy.size))
    sp = sp[:n]
    gy = gy[:n]
    d = np.diff(sp)
    if d.size == 0:
        return 0.0
    sd = float(np.std(d)) + 1e-12
    edges = np.where(np.abs(d) > 2.0 * sd)[0]
    if edges.size == 0:
        return 0.0
    W = min(25, max(5, n // 40))
    vals: list[float] = []
    for idx in edges[: min(50, int(edges.size))]:
        i0 = int(idx) + 1
        i1 = min(n, i0 + W)
        if i1 <= i0:
            continue
        target = float(sp[min(i0, n - 1)])
        seg = gy[i0:i1]
        if seg.size == 0:
            continue
        step = float(d[int(idx)])
        if step > 0:
            ex = float(np.max(seg) - target)
        else:
            ex = float(target - np.min(seg))
        if np.isfinite(ex):
            vals.append(max(0.0, ex))
    if not vals:
        return 0.0
    mn = float(np.mean(vals))
    return mn if np.isfinite(mn) else 0.0


def _noise_block(
    analysis: dict[str, Any],
    fft_data: dict[str, Any] | None,
) -> dict[str, Any]:
    default = {
        "value": 0.0,
        "grade": "A",
        "hf_ratio": 0.0,
        "source": "default",
    }
    try:
        nm = _get_noise_model_dict(analysis)
        if nm is not None:
            raw_noise_score = _safe_float(nm.get("score"), 50.0)
            raw_noise_score = max(0.0, min(100.0, raw_noise_score))
            noise_value = max(0.0, min(100.0, 100.0 - raw_noise_score))
            hf = nm.get("hf_ratio")
            if hf is None:
                hf = nm.get("ratio")
            hf_r = _safe_float(hf, 0.0)
            out = {
                "value": float(noise_value),
                "grade": grade_from_score(noise_value),
                "hf_ratio": float(hf_r),
                "source": "noise_model",
            }
            if nm.get("assessable") is False:
                out["assessable"] = False
                out["confidence"] = "limited"
                out["limited_by"] = nm.get("limited_by")
                out["limit_reasons"] = list(nm.get("limit_reasons") or [])
                out["sample_rate_metadata"] = nm.get("sample_rate_metadata")
            return out

        freqs, spec = _fft_vectors(fft_data)
        if freqs.size > 0:
            out = compute_noise_score(freqs, spec)
            raw_noise_score = max(
                0.0, min(100.0, _safe_float(out.get("score"), 0.0))
            )
            noise_value = max(0.0, min(100.0, 100.0 - raw_noise_score))
            hf_r = _safe_float(out.get("hf_ratio", out.get("ratio")), 0.0)
            return {
                "value": float(noise_value),
                "grade": grade_from_score(noise_value),
                "hf_ratio": float(hf_r),
                "source": "fft_computed",
            }
    except Exception:
        pass
    return default


def _peaks_list(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    raw = analysis.get("fft_peaks")
    if not isinstance(raw, list):
        raw = []
    out: list[dict[str, Any]] = []
    for p in raw[:24]:
        if not isinstance(p, dict):
            continue
        try:
            f = float(p.get("freq", 0.0) or 0.0)
            a = float(p.get("amplitude", 0.0) or 0.0)
            bw = p.get("bandwidth_hz")
            bwf = _safe_float(bw, 0.0) if bw is not None else None
            row = {"freq": float(f), "amplitude": float(a)}
            if bwf is not None and bwf > 0:
                row["bandwidth_hz"] = float(bwf)
            out.append(row)
        except (TypeError, ValueError):
            continue
    return out


def _resonance_block(analysis: dict[str, Any]) -> dict[str, Any]:
    default: dict[str, Any] = {
        "dominant_hz": None,
        "severity": "low",
        "peaks": [],
    }
    try:
        peaks = _peaks_list(analysis)
        dom: float | None = None
        rv2 = analysis.get("resonance_v2_hz")
        if rv2 is not None:
            try:
                v = float(rv2)
                if np.isfinite(v) and v > 0:
                    dom = v
            except (TypeError, ValueError):
                pass
        if dom is None and peaks:
            dom = float(max(peaks, key=lambda x: float(x.get("amplitude", 0.0)))["freq"])

        severity = "low"
        if peaks:
            amps = [float(x.get("amplitude", 0.0)) for x in peaks]
            if amps:
                mx = max(amps)
                med = float(np.median(np.asarray(amps, dtype=float)))
                if mx > med * 4.0 + 1e-12:
                    severity = "high"
                elif mx > med * 2.0 + 1e-12:
                    severity = "medium"
                else:
                    severity = "low"

        if severity not in ("low", "medium", "high"):
            severity = "low"

        return {
            "dominant_hz": dom,
            "severity": severity,
            "peaks": peaks,
        }
    except Exception:
        return default


def _propwash_block(analysis: dict[str, Any]) -> dict[str, Any]:
    default = {"level": "unknown", "confidence": 0.0}
    try:
        pw = analysis.get("propwash")
        if isinstance(pw, dict):
            lvl = pw.get("level")
            level = str(lvl).lower() if lvl is not None else "unknown"
            conf = _safe_float(pw.get("score"), 0.0)
            conf = max(0.0, min(1.0, conf))
            return {"level": level, "confidence": float(conf)}
    except Exception:
        pass
    return default


def _motor_block(analysis: dict[str, Any]) -> dict[str, Any]:
    default = {
        "health": 0.0,
        "imbalance": 0.0,
        "has_desync_risk": False,
    }
    try:
        md = analysis.get("motor_diagnostics")
        if not isinstance(md, dict):
            return default
        motors = md.get("motors")
        if not isinstance(motors, list) or not motors:
            mh = _safe_float(analysis.get("motor_health"), 0.0)
            return {
                "health": max(0.0, min(100.0, mh)),
                "imbalance": 0.0,
                "has_desync_risk": False,
            }

        healths: list[float] = []
        risk = False
        for m in motors:
            if not isinstance(m, dict):
                continue
            h = _safe_float(m.get("health"), 0.0)
            healths.append(max(0.0, min(100.0, h)))
            st = str(m.get("status", "")).lower()
            issues = m.get("issues")
            if st == "bad":
                risk = True
            elif isinstance(issues, list) and issues:
                if st == "warning":
                    risk = True

        if not healths:
            mh = _safe_float(analysis.get("motor_health"), 0.0)
            return {
                "health": max(0.0, min(100.0, mh)),
                "imbalance": 0.0,
                "has_desync_risk": False,
            }

        avg_h = float(np.mean(np.asarray(healths, dtype=float)))
        imb = float(np.std(np.asarray(healths, dtype=float)))
        health = max(0.0, min(avg_h, 100.0))
        imbalance = max(0.0, imb)

        return {
            "health": float(health),
            "imbalance": float(imbalance),
            "has_desync_risk": bool(risk),
        }
    except Exception:
        return default


def _coerce_samples_dict(samples: Any) -> dict[str, Any]:
    if isinstance(samples, dict) and "gyro" in samples:
        out = dict(samples)
        for k in ("gyro", "setpoint", "d_term", "motors", "throttle", "time_us"):
            if k not in out:
                if k == "time_us":
                    out[k] = np.zeros((0,), dtype=float)
                elif k == "throttle":
                    out[k] = np.zeros((0,), dtype=float)
                else:
                    shp = (0, 4) if k == "motors" else (0, 3)
                    out[k] = np.zeros(shp, dtype=float)
        return out
    return {
        "gyro": np.zeros((0, 3), dtype=float),
        "setpoint": np.zeros((0, 3), dtype=float),
        "d_term": np.zeros((0, 3), dtype=float),
        "motors": np.zeros((0, 4), dtype=float),
        "throttle": np.zeros((0,), dtype=float),
        "time_us": np.zeros((0,), dtype=float),
    }


def _sanitize_metrics_for_return(m: dict[str, Any]) -> dict[str, Any]:
    """Ensure key numerics are finite and clamped; keep structure and keys."""
    out = dict(m)
    tr = out.get("tracking")
    if isinstance(tr, dict):
        sanitized_tr = {
            "score": max(0.0, min(100.0, _safe_float(tr.get("score"), 50.0))),
            "mean_error": _safe_float(tr.get("mean_error"), 0.0),
            "latency_ms": max(0.0, min(100.0, _safe_float(tr.get("latency_ms"), 0.0))),
            "overshoot": max(0.0, _safe_float(tr.get("overshoot"), 0.0)),
        }
        if "source" in tr:
            sanitized_tr["source"] = str(tr["source"])
        if "computed" in tr:
            sanitized_tr["computed"] = bool(tr["computed"])
        if "confidence" in tr:
            sanitized_tr["confidence"] = max(0.0, min(1.0, _safe_float(tr.get("confidence"), 0.0)))
        out["tracking"] = sanitized_tr
    nz = out.get("noise")
    if isinstance(nz, dict):
        nv = max(0.0, min(100.0, _safe_float(nz.get("value"), 0.0)))
        gr = nz.get("grade")
        if not isinstance(gr, str):
            gr = grade_from_score(nv)
        out["noise"] = {
            "value": float(nv),
            "grade": gr,
            "hf_ratio": _safe_float(nz.get("hf_ratio"), 0.0),
            "source": nz.get("source", "default"),
        }
    res = out.get("resonance")
    if isinstance(res, dict):
        r2 = dict(res)
        sev = r2.get("severity")
        ss = sev if isinstance(sev, str) else "low"
        if ss not in ("low", "medium", "high"):
            ss = "low"
        r2["severity"] = ss
        out["resonance"] = r2
    pw = out.get("propwash")
    if isinstance(pw, dict):
        out["propwash"] = {
            "level": pw.get("level", "unknown"),
            "confidence": max(0.0, min(1.0, _safe_float(pw.get("confidence"), 0.0))),
        }
    mo = out.get("motor")
    if isinstance(mo, dict):
        out["motor"] = {
            "health": max(0.0, min(100.0, _safe_float(mo.get("health"), 0.0))),
            "imbalance": max(0.0, _safe_float(mo.get("imbalance"), 0.0)),
            "has_desync_risk": bool(mo.get("has_desync_risk", False)),
        }
    rb = out.get("response")
    if isinstance(rb, dict):
        out["response"] = {
            "applied": bool(rb.get("applied", False)),
            "step_response_delay_ms": _sanitize_scalar(rb.get("step_response_delay_ms"), lo=0.0, hi=500.0),
            "rise_time_ms": _sanitize_scalar(rb.get("rise_time_ms"), lo=0.0, hi=800.0),
            "settling_time_ms": _sanitize_scalar(rb.get("settling_time_ms"), lo=0.0, hi=1200.0),
            "overshoot_percent": _sanitize_scalar(rb.get("overshoot_percent"), lo=0.0, hi=250.0),
            "steady_state_tracking_error": _sanitize_scalar(
                rb.get("steady_state_tracking_error"), lo=0.0, hi=500.0
            ),
            "response_quality_score": max(
                0.0, min(100.0, _safe_float(rb.get("response_quality_score"), 0.0))
            ),
            "confidence": max(0.0, min(1.0, _safe_float(rb.get("confidence"), 0.0))),
            "sample_count": max(0, int(_safe_float(rb.get("sample_count"), 0.0))),
            "event_count": max(0, int(_safe_float(rb.get("event_count"), 0.0))),
            "axes": dict(rb.get("axes") or {}) if isinstance(rb.get("axes"), dict) else {},
            "response_summary": dict(rb.get("response_summary") or {})
            if isinstance(rb.get("response_summary"), dict)
            else {},
            "overshoot_summary": dict(rb.get("overshoot_summary") or {})
            if isinstance(rb.get("overshoot_summary"), dict)
            else {},
            "notes": [str(x) for x in rb.get("notes", [])] if isinstance(rb.get("notes"), list) else [],
        }
    db = out.get("d_effectiveness")
    if isinstance(db, dict):
        merged_summary = dict(db.get("summary") or {}) if isinstance(db.get("summary"), dict) else {}
        axis_summary = dict(db.get("axis_summary") or {}) if isinstance(db.get("axis_summary"), dict) else {}
        axes = dict(db.get("axes") or {}) if isinstance(db.get("axes"), dict) else {}
        out["d_effectiveness"] = {
            "applied": bool(db.get("applied", False)),
            "signal_source": str(db.get("signal_source") or "proxy_error_derivative"),
            "d_effectiveness_score": max(
                0.0, min(100.0, _safe_float(db.get("d_effectiveness_score"), 50.0))
            ),
            "d_response_correlation": max(
                0.0, min(1.0, _safe_float(db.get("d_response_correlation"), 0.0))
            ),
            "d_noise_penalty": max(0.0, min(1.0, _safe_float(db.get("d_noise_penalty"), 0.0))),
            "d_heat_risk_bias": max(0.0, min(1.0, _safe_float(db.get("d_heat_risk_bias"), 0.0))),
            "d_utility_estimate": max(0.0, min(1.0, _safe_float(db.get("d_utility_estimate"), 0.0))),
            "d_effectiveness_confidence": max(
                0.0, min(1.0, _safe_float(db.get("d_effectiveness_confidence"), 0.0))
            ),
            "event_count": max(0, int(_safe_float(db.get("event_count"), 0.0))),
            "usable_window_count": max(0, int(_safe_float(db.get("usable_window_count"), 0.0))),
            "summary": merged_summary,
            "axis_summary": axis_summary,
            "axes": axes,
            "notes": [str(x) for x in db.get("notes", [])] if isinstance(db.get("notes"), list) else [],
        }
    return out


def build_metrics(
    samples: dict[str, Any],
    analysis: dict[str, Any],
    fft_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build unified metrics dict. Never raises; always returns the canonical structure.

    ``samples`` must provide numpy arrays: gyro (N,3), setpoint (N,3), motors (N,M),
    throttle (N,), time_us (N,) — use :func:`samples_dict_from_normalized_rows` when
    starting from parsed log rows.
    """
    try:
        bundle = _coerce_samples_dict(samples)
        gyro = np.asarray(bundle.get("gyro"), dtype=float)
        sp = np.asarray(bundle.get("setpoint"), dtype=float)
        tu = np.asarray(bundle.get("time_us"), dtype=float)

        if not isinstance(analysis, dict):
            analysis = {}

        fft_in = fft_data if isinstance(fft_data, dict) else None
        if fft_in is None and isinstance(analysis.get("fft_bundle"), dict):
            fft_in = analysis["fft_bundle"]

        response_block = analyze_step_response(
            bundle,
            analysis.get("segments") if isinstance(analysis, dict) else None,
        )
        d_effectiveness = analyze_d_effectiveness(
            bundle,
            analysis,
            response_analysis=response_block,
            segments=analysis.get("segments") if isinstance(analysis, dict) else None,
        )
        pa_track = _per_axis_tracking_quality(gyro, sp)
        pa_noise = _per_axis_noise_cleanliness(gyro, tu)
        return _sanitize_metrics_for_return(
            {
                "tracking": _tracking_block(gyro, sp, tu),
                "response": response_block,
                "d_effectiveness": d_effectiveness,
                "noise": _noise_block(analysis, fft_in),
                "resonance": _resonance_block(analysis),
                "propwash": _propwash_block(analysis),
                "motor": _motor_block(analysis),
                **pa_track,
                **pa_noise,
            }
        )
    except Exception:
        return _sanitize_metrics_for_return(
            {
                "tracking": {
                    "score": 50.0,
                    "mean_error": 0.0,
                    "latency_ms": 0.0,
                    "overshoot": 0.0,
                    "source": "error_fallback",
                    "computed": False,
                    "confidence": 0.0,
                },
                "response": analyze_step_response({}, None),
                "d_effectiveness": analyze_d_effectiveness({}, None),
                "noise": {
                    "value": 0.0,
                    "grade": "A",
                    "hf_ratio": 0.0,
                    "source": "default",
                },
                "resonance": {
                    "dominant_hz": None,
                    "severity": "low",
                    "peaks": [],
                },
                "propwash": {"level": "unknown", "confidence": 0.0},
                "motor": {
                    "health": 0.0,
                    "imbalance": 0.0,
                    "has_desync_risk": False,
                },
                "roll_error": 50.0,
                "pitch_error": 50.0,
                "yaw_error": 50.0,
                "roll_noise": 50.0,
                "pitch_noise": 50.0,
                "yaw_noise": 50.0,
            }
        )


def validate_metrics_output(metrics: dict) -> dict:
    import math

    def check(value, name):
        if isinstance(value, (int, float)) and not math.isfinite(value):
            return f"{name} is not finite"
        return None

    issues = []

    for section, content in metrics.items():
        if isinstance(content, dict):
            for k, v in content.items():
                err = check(v, f"{section}.{k}")
                if err:
                    issues.append(err)

    return {
        "valid": len(issues) == 0,
        "issues": issues,
    }
