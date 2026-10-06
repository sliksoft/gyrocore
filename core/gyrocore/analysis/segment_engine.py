# GyroCore WU4: adapted from AeroTuner backend/analysis/segment_engine.py
"""
Multi-signal flight log segmentation for context-aware analysis and tuning.

Uses combined throttle dynamics, setpoint activity, and gyro energy — not
single-threshold rules. Deterministic and numpy-only.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np

# Windowing
_WINDOW = 80
_STEP = 40
_MIN_SEGMENT_SAMPLES = 50
_MOVING_AVG = 15
_GYRO_RMS_WIN = 21

# Type order for deterministic tie-break (earlier wins on equal score)
_TYPE_PRIORITY = (
    "propwash_candidate",
    "punch",
    "maneuver",
    "cruise",
    "hover",
)


def _finite_replace(a: np.ndarray) -> np.ndarray:
    x = np.asarray(a, dtype=float)
    return np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)


def _norm01_series(x: np.ndarray, p_lo: float = 5.0, p_hi: float = 95.0) -> np.ndarray:
    """Map series to ~[0,1] via robust percentiles; deterministic on fixed data."""
    x = _finite_replace(x)
    if x.size == 0:
        return x
    lo = float(np.percentile(x, p_lo))
    hi = float(np.percentile(x, p_hi))
    span = hi - lo
    if span < 1e-12:
        return np.zeros_like(x)
    y = (x - lo) / span
    return np.clip(y, 0.0, 1.0)


def _moving_mean(x: np.ndarray, win: int) -> np.ndarray:
    x = _finite_replace(np.asarray(x, dtype=float).ravel())
    n = x.size
    if n == 0:
        return x
    w = max(1, int(win))
    if w == 1:
        return x.copy()
    k = np.ones(w, dtype=float) / float(w)
    return np.convolve(x, k, mode="same")


def _rolling_rms(x: np.ndarray, win: int) -> np.ndarray:
    """RMS of x over centered window."""
    x = _finite_replace(np.asarray(x, dtype=float).ravel())
    x2 = x * x
    mean_x2 = _moving_mean(x2, win)
    return np.sqrt(np.maximum(mean_x2, 0.0))


def _coerce_samples(samples: dict[str, Any]) -> dict[str, np.ndarray]:
    g = np.asarray(samples.get("gyro"), dtype=float)
    sp = np.asarray(samples.get("setpoint"), dtype=float)
    thr = np.asarray(samples.get("throttle"), dtype=float).ravel()
    tu = np.asarray(samples.get("time_us"), dtype=float).ravel()

    if g.ndim == 1:
        g = g.reshape(-1, 1)
    if g.shape[1] < 3:
        pad = np.zeros((g.shape[0], 3 - g.shape[1]), dtype=float)
        g = np.hstack([g, pad])
    g = g[:, :3]
    n = int(g.shape[0])

    if sp.size == 0:
        sp = np.zeros((n, 3), dtype=float)
    elif sp.ndim == 1:
        sp = np.column_stack([sp, sp, sp]) if sp.shape[0] == n else np.zeros((n, 3), dtype=float)
    else:
        if sp.shape[0] > n:
            sp = sp[:n, :]
        elif sp.shape[0] < n:
            pad_r = np.zeros((n - sp.shape[0], sp.shape[1]), dtype=float)
            sp = np.vstack([sp, pad_r])
        if sp.shape[1] < 3:
            pad = np.zeros((sp.shape[0], 3 - sp.shape[1]), dtype=float)
            sp = np.hstack([sp, pad])
        sp = sp[:, :3]

    if thr.size != n:
        if thr.size > n:
            thr = thr[:n]
        else:
            thr = np.pad(thr, (0, n - thr.size), mode="edge")
    if tu.size != n:
        if tu.size > n:
            tu = tu[:n]
        else:
            tu = np.pad(tu, (0, n - tu.size), mode="edge")

    return {"gyro": g, "setpoint": sp, "throttle": thr, "time_us": tu}


def _compute_features(samples: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """
    Per-sample features, all normalized to [0, 1] where applicable.

    Returns keys used by window scoring (raw + normalized derivatives).
    """
    thr = _finite_replace(samples["throttle"])
    sp = _finite_replace(samples["setpoint"])
    gy = _finite_replace(samples["gyro"])
    tu = _finite_replace(samples["time_us"])

    n = thr.size
    if n < 2:
        z = np.zeros(max(1, n), dtype=float)
        return {
            "throttle_smooth": z[:n],
            "throttle_deriv": z[:n],
            "throttle_deriv_pos": z[:n],
            "throttle_deriv_neg": z[:n],
            "setpoint_mag": z[:n],
            "setpoint_activity": z[:n],
            "gyro_mag": z[:n],
            "gyro_energy": z[:n],
            "throttle_norm": z[:n],
            "deriv_pos_norm": z[:n],
            "deriv_neg_norm": z[:n],
            "sp_act_norm": z[:n],
            "gyro_en_norm": z[:n],
            "deriv_abs_norm": z[:n],
        }

    thr_s = _moving_mean(thr, _MOVING_AVG)
    dt = np.gradient(tu)
    dt = np.where(np.abs(dt) < 1e-6, 1e-6, dt)
    thr_deriv = np.gradient(thr_s) / dt
    thr_deriv = _finite_replace(thr_deriv)

    deriv_pos = np.maximum(thr_deriv, 0.0)
    deriv_neg = np.maximum(-thr_deriv, 0.0)

    sp_mag = np.linalg.norm(sp, axis=1)
    sp_act = _moving_mean(sp_mag, _MOVING_AVG)

    gy_mag = np.linalg.norm(gy, axis=1)
    gy_energy = _rolling_rms(gy_mag, _GYRO_RMS_WIN)

    throttle_norm = _norm01_series(thr_s)
    deriv_pos_norm = _norm01_series(deriv_pos)
    deriv_neg_norm = _norm01_series(deriv_neg)
    sp_act_norm = _norm01_series(sp_act)
    gyro_en_norm = _norm01_series(gy_energy)
    deriv_abs_norm = _norm01_series(np.abs(thr_deriv))

    return {
        "throttle_smooth": thr_s,
        "throttle_deriv": thr_deriv,
        "throttle_deriv_pos": deriv_pos,
        "throttle_deriv_neg": deriv_neg,
        "setpoint_mag": sp_mag,
        "setpoint_activity": sp_act,
        "gyro_mag": gy_mag,
        "gyro_energy": gy_energy,
        "throttle_norm": throttle_norm,
        "deriv_pos_norm": deriv_pos_norm,
        "deriv_neg_norm": deriv_neg_norm,
        "sp_act_norm": sp_act_norm,
        "gyro_en_norm": gyro_en_norm,
        "deriv_abs_norm": deriv_abs_norm,
    }


def _window_means(
    feat: dict[str, np.ndarray], start: int, end: int
) -> dict[str, float]:
    sl = slice(start, end)
    out: dict[str, float] = {}
    for key in (
        "throttle_norm",
        "deriv_pos_norm",
        "deriv_neg_norm",
        "sp_act_norm",
        "gyro_en_norm",
        "deriv_abs_norm",
    ):
        a = feat[key][sl]
        out[key] = float(np.mean(a)) if a.size else 0.0
    return out


def _window_scores(
    m: dict[str, float],
    m_prev: dict[str, float] | None,
    m_next: dict[str, float] | None,
) -> dict[str, float]:
    """
    Soft multi-signal scores in [0, 1] for each segment type.
    Higher = better match for that type.
    """
    a = m["deriv_abs_norm"]
    b = m["deriv_pos_norm"]
    c = m["deriv_neg_norm"]
    d = m["sp_act_norm"]
    e = m["gyro_en_norm"]
    f = m["throttle_norm"]

    # Hover: quiescent command and motion
    hover = (1.0 - a) * (1.0 - d) * (1.0 - e) * (0.4 + 0.6 * (1.0 - f))

    # Cruise: stable throttle, mid band level, low command / vibration
    mid_throttle = float(np.exp(-((f - 0.5) ** 2) / (2.0 * 0.18**2)))
    cruise = (1.0 - a) * (1.0 - d) * (1.0 - e) * (0.35 + 0.65 * mid_throttle)

    # Rising gyro energy vs previous window (punch)
    e_prev = m_prev["gyro_en_norm"] if m_prev is not None else e
    rise = max(0.0, e - e_prev)
    punch = b * (0.3 + 0.7 * e) * (1.0 + rise)

    # Maneuver: aggressive setpoint + gyro regardless of throttle
    maneuver = d * e

    # Propwash candidate: prior window strong throttle drop, this window gyro energy
    c_prev = m_prev["deriv_neg_norm"] if m_prev is not None else 0.0
    e_next = m_next["gyro_en_norm"] if m_next is not None else e
    # Drop then spike: emphasize previous neg derivative and current/next gyro
    propwash = (0.5 * c_prev + 0.5 * c) * (0.5 * e + 0.5 * e_next) * (1.0 - 0.35 * d)

    return {
        "hover": max(0.0, float(hover)),
        "cruise": max(0.0, float(cruise)),
        "punch": max(0.0, float(punch)),
        "maneuver": max(0.0, float(maneuver)),
        "propwash_candidate": max(0.0, float(propwash)),
    }


def _pick_type(scores: dict[str, float]) -> str:
    best = -1.0
    chosen = "hover"
    for t in _TYPE_PRIORITY:
        s = scores.get(t, 0.0)
        if s > best:
            best = s
            chosen = t
    return chosen


def _confidence_from_scores(scores: dict[str, float], chosen: str, n_samples: int) -> float:
    vals = np.array([scores.get(k, 0.0) for k in _TYPE_PRIORITY], dtype=float)
    if vals.size == 0:
        return 0.0
    total = float(np.sum(vals))
    top = float(scores.get(chosen, 0.0))
    if total < 1e-12:
        agreement = 0.0
    else:
        agreement = top / total
    sv = np.sort(vals)[::-1]
    second = float(sv[1]) if sv.size > 1 else 0.0
    margin = top - second if sv.size > 1 else top
    margin_n = margin / (top + 1e-9)
    signal_agreement = 0.5 * agreement + 0.5 * float(np.clip(margin_n, 0.0, 1.0))
    dur = min(1.0, n_samples / 200.0)
    conf = 0.55 * signal_agreement + 0.45 * dur
    return float(np.clip(conf, 0.0, 1.0))


def _merge_windows(
    windows: list[tuple[int, int, str, float]],
    n: int,
    time_us: np.ndarray,
) -> list[dict[str, Any]]:
    if not windows:
        return []

    merged: list[list[Any]] = [[windows[0][0], windows[0][1], windows[0][2], [windows[0][3]]]]
    for s, e, typ, conf in windows[1:]:
        cur = merged[-1]
        if typ == cur[2] and s <= cur[1]:
            cur[1] = max(cur[1], e)
            cur[3].append(conf)
        elif typ == cur[2] and s <= cur[1] + _STEP:
            cur[1] = max(cur[1], e)
            cur[3].append(conf)
        else:
            merged.append([s, e, typ, [conf]])

    segments: list[dict[str, Any]] = []
    tu = _finite_replace(time_us)
    for s, e, typ, confs in merged:
        s = int(max(0, min(s, n - 1)))
        e = int(max(s, min(e - 1, n - 1)))
        if e < s:
            continue
        t0 = float(tu[s]) if tu.size > s else 0.0
        t1 = float(tu[e]) if tu.size > e else t0
        duration_ms = max(0.0, (t1 - t0) / 1000.0)
        conf = float(np.mean(confs)) if confs else 0.0
        segments.append(
            {
                "type": typ,
                "start_idx": s,
                "end_idx": e,
                "duration_ms": duration_ms,
                "confidence": conf,
            }
        )
    return segments


def _sanitize_segments(
    segments: list[dict[str, Any]], n: int, time_us: np.ndarray
) -> list[dict[str, Any]]:
    tu = _finite_replace(time_us)
    out: list[dict[str, Any]] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        typ = seg.get("type")
        if typ not in _TYPE_PRIORITY:
            typ = "cruise"
        try:
            s = int(seg.get("start_idx", 0))
            e = int(seg.get("end_idx", 0))
        except (TypeError, ValueError):
            continue
        s = max(0, min(s, n - 1))
        e = max(0, min(e, n - 1))
        if e < s:
            s, e = e, s
        dur_ms = seg.get("duration_ms", 0.0)
        try:
            dur_ms = float(dur_ms)
        except (TypeError, ValueError):
            dur_ms = 0.0
        if not np.isfinite(dur_ms) or dur_ms < 0.0:
            t0 = float(tu[s]) if tu.size > s else 0.0
            t1 = float(tu[e]) if tu.size > e else t0
            dur_ms = max(0.0, (t1 - t0) / 1000.0)
        try:
            conf = float(seg.get("confidence", 0.0))
        except (TypeError, ValueError):
            conf = 0.0
        if not np.isfinite(conf):
            conf = 0.0
        conf = float(np.clip(conf, 0.0, 1.0))
        out.append(
            {
                "type": typ,
                "start_idx": s,
                "end_idx": e,
                "duration_ms": dur_ms,
                "confidence": conf,
            }
        )
    return out


def _filter_min_length(
    segments: list[dict[str, Any]], n: int, time_us: np.ndarray
) -> list[dict[str, Any]]:
    if not segments:
        return []
    kept: list[dict[str, Any]] = []
    for seg in segments:
        span = int(seg["end_idx"]) - int(seg["start_idx"]) + 1
        if span >= _MIN_SEGMENT_SAMPLES:
            kept.append(seg)
    if kept:
        return kept
    # Merge entire log as single segment if nothing met minimum
    tu = _finite_replace(time_us)
    t0 = float(tu[0]) if tu.size else 0.0
    t1 = float(tu[n - 1]) if n > 0 and tu.size > n - 1 else t0
    return [
        {
            "type": "cruise",
            "start_idx": 0,
            "end_idx": max(0, n - 1),
            "duration_ms": max(0.0, (t1 - t0) / 1000.0),
            "confidence": 0.35,
        }
    ]


def detect_segments(samples: Dict[str, np.ndarray]) -> Dict[str, Any]:
    """
    Segment a flight log using throttle dynamics, setpoint activity, and gyro energy.

    Returns JSON-serializable dict with ``segments`` and ``summary``.
    """
    try:
        bundle = _coerce_samples(samples)
        g = bundle["gyro"]
        n = int(g.shape[0])
        tu = bundle["time_us"]

        if n < 2:
            return {
                "segments": [],
                "summary": {"total_segments": 0, "types_present": []},
            }

        feat = _compute_features(bundle)
        win = min(_WINDOW, n)
        step = max(1, min(_STEP, win // 2))

        window_rows: list[tuple[dict[str, float], int, int]] = []
        s0 = 0
        while s0 + win <= n:
            e0 = s0 + win
            window_rows.append((_window_means(feat, s0, e0), s0, e0))
            s0 += step
        if not window_rows and n > 0:
            window_rows.append((_window_means(feat, 0, n), 0, n))
        elif window_rows and window_rows[-1][2] < n:
            s_tail = max(0, n - win)
            if s_tail != window_rows[-1][1] or window_rows[-1][2] != n:
                window_rows.append((_window_means(feat, s_tail, n), s_tail, n))

        scored_windows: list[tuple[int, int, str, float]] = []
        for i, (means, s, e) in enumerate(window_rows):
            prev_m = window_rows[i - 1][0] if i > 0 else None
            next_m = window_rows[i + 1][0] if i + 1 < len(window_rows) else None
            sc = _window_scores(means, prev_m, next_m)
            typ = _pick_type(sc)
            conf = _confidence_from_scores(sc, typ, e - s)
            scored_windows.append((s, e, typ, conf))

        merged = _merge_windows(scored_windows, n, tu)
        merged = _sanitize_segments(merged, n, tu)
        merged = _filter_min_length(merged, n, tu)
        merged = _sanitize_segments(merged, n, tu)

        types_present = sorted({str(s["type"]) for s in merged})
        return {
            "segments": merged,
            "summary": {
                "total_segments": len(merged),
                "types_present": types_present,
            },
        }
    except Exception:
        return {
            "segments": [],
            "summary": {"total_segments": 0, "types_present": []},
        }
