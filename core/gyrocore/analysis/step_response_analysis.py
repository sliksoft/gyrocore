# GyroCore WU4: adapted from AeroTuner backend/analysis/step_response_analysis.py
"""
Step-response and overshoot analysis from setpoint/gyro traces.

Deterministic, event-based, and intentionally conservative: low-quality windows reduce
confidence rather than forcing precise-looking numbers.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

_AXES: tuple[str, ...] = ("roll", "pitch", "yaw")
_ACTIVE_SEGMENT_TYPES = frozenset({"maneuver", "punch", "propwash_candidate"})


def _finite_1d(x: Any) -> np.ndarray:
    return np.nan_to_num(np.asarray(x, dtype=float).reshape(-1), nan=0.0, posinf=0.0, neginf=0.0)


def _finite_2d(x: Any) -> np.ndarray:
    arr = np.asarray(x, dtype=float)
    if arr.ndim != 2:
        return np.zeros((0, 3), dtype=float)
    return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)


def _moving_mean(x: np.ndarray, win: int) -> np.ndarray:
    a = _finite_1d(x)
    if a.size == 0:
        return a
    w = max(1, int(win))
    if w == 1:
        return a.copy()
    k = np.ones(w, dtype=float) / float(w)
    return np.convolve(a, k, mode="same")


def _moving_std(x: np.ndarray, win: int) -> np.ndarray:
    a = _finite_1d(x)
    if a.size == 0:
        return a
    mean = _moving_mean(a, win)
    mean2 = _moving_mean(a * a, win)
    var = np.maximum(0.0, mean2 - mean * mean)
    return np.sqrt(var)


def _weighted_mean_or_none(values: list[float], weights: list[float]) -> float | None:
    if not values:
        return None
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = np.isfinite(v) & np.isfinite(w) & (w > 0.0)
    if not np.any(mask):
        mask = np.isfinite(v)
        if not np.any(mask):
            return None
        return float(np.mean(v[mask]))
    return float(np.average(v[mask], weights=w[mask]))


def _sanitize_scalar(value: Any, *, lo: float | None = None, hi: float | None = None) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(out):
        return None
    if lo is not None:
        out = max(float(lo), out)
    if hi is not None:
        out = min(float(hi), out)
    return float(out)


def _dt_ms(time_us: np.ndarray) -> float:
    tu = _finite_1d(time_us)
    if tu.size < 2:
        return 2.0
    diff = np.diff(tu)
    diff = diff[np.isfinite(diff) & (diff > 0.0)]
    if diff.size == 0:
        return 2.0
    dt = float(np.median(diff) / 1000.0)
    if not np.isfinite(dt) or dt <= 0.0:
        return 2.0
    return max(0.25, min(dt, 20.0))


def _allowed_mask(segments: Mapping[str, Any] | None, n: int, margin: int) -> np.ndarray:
    mask = np.ones(n, dtype=bool)
    if not isinstance(segments, Mapping):
        return mask
    raw = segments.get("segments")
    if not isinstance(raw, list):
        return mask
    filtered = [seg for seg in raw if isinstance(seg, Mapping) and seg.get("type") in _ACTIVE_SEGMENT_TYPES]
    if not filtered:
        return mask
    out = np.zeros(n, dtype=bool)
    for seg in filtered:
        try:
            s = int(seg.get("start_idx", 0))
            e = int(seg.get("end_idx", 0))
        except (TypeError, ValueError):
            continue
        s = max(0, min(n - 1, s - margin))
        e = max(0, min(n - 1, e + margin))
        if e < s:
            s, e = e, s
        out[s : e + 1] = True
    if np.any(out):
        return out
    return mask


def _overshoot_severity(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 20.0:
        return "high"
    if value >= 8.0:
        return "medium"
    return "low"


def _default_axis(sample_count: int) -> dict[str, Any]:
    return {
        "step_response_delay_ms": None,
        "rise_time_ms": None,
        "settling_time_ms": None,
        "overshoot_percent": None,
        "steady_state_tracking_error": None,
        "response_quality_score": 0.0,
        "confidence": 0.0,
        "sample_count": int(max(0, sample_count)),
        "event_count": 0,
        "notes": ["insufficient_response_events"],
    }


def _event_quality(
    *,
    delay_ms: float | None,
    rise_ms: float | None,
    settling_ms: float | None,
    overshoot_percent: float | None,
    steady_state_error: float | None,
    target_amp: float,
) -> float:
    score = 100.0
    amp = max(25.0, abs(float(target_amp)))
    if delay_ms is not None:
        score -= min(18.0, float(delay_ms) * 0.35)
    else:
        score -= 14.0
    if rise_ms is not None:
        score -= min(22.0, float(rise_ms) * 0.18)
    else:
        score -= 16.0
    if settling_ms is not None:
        score -= min(24.0, float(settling_ms) * 0.10)
    else:
        score -= 20.0
    if overshoot_percent is not None:
        score -= min(24.0, float(max(0.0, overshoot_percent)) * 0.8)
    if steady_state_error is not None:
        score -= min(18.0, (float(steady_state_error) / amp) * 90.0)
    return float(max(0.0, min(100.0, score)))


def _event_confidence(
    *,
    amp: float,
    pre_std: float,
    post_std: float,
    quality_score: float,
    delay_ms: float | None,
    rise_ms: float | None,
) -> float:
    denom = max(15.0, abs(float(amp)))
    plateau = 1.0 - min(1.0, (pre_std + post_std) / max(10.0, denom * 0.9))
    amp_score = min(1.0, abs(float(amp)) / 180.0)
    detect_score = 1.0 if delay_ms is not None and rise_ms is not None else 0.45
    quality = max(0.0, min(1.0, float(quality_score) / 100.0))
    conf = 0.18 + 0.32 * amp_score + 0.22 * plateau + 0.18 * quality + 0.10 * detect_score
    return float(max(0.0, min(1.0, conf)))


def _extract_candidates(
    sp: np.ndarray,
    allowed_mask: np.ndarray,
    *,
    dt_ms: float,
    pre_win: int,
    plateau_offset: int,
    plateau_win: int,
    eval_win: int,
) -> list[dict[str, Any]]:
    n = int(sp.size)
    if n < pre_win + plateau_offset + plateau_win + 4:
        return []
    smooth = _moving_mean(sp, max(3, int(round(8.0 / max(dt_ms, 0.25)))))
    dsp = np.abs(np.diff(smooth))
    if dsp.size == 0:
        return []
    deriv_med = float(np.median(dsp))
    deriv_p95 = float(np.percentile(dsp, 95.0))
    span = float(np.percentile(np.abs(smooth), 95.0))
    deriv_threshold = max(6.0, deriv_med * 6.0, deriv_p95 * 0.55, span * 0.03)
    raw = np.where(dsp >= deriv_threshold)[0] + 1
    if raw.size == 0:
        return []

    min_gap = max(plateau_win, int(round(30.0 / max(dt_ms, 0.25))))
    grouped: list[int] = []
    group: list[int] = []
    for idx in raw.tolist():
        if not group or idx - group[-1] <= max(2, min_gap // 3):
            group.append(int(idx))
            continue
        best = max(group, key=lambda i: float(dsp[min(max(i - 1, 0), dsp.size - 1)]))
        grouped.append(int(best))
        group = [int(idx)]
    if group:
        best = max(group, key=lambda i: float(dsp[min(max(i - 1, 0), dsp.size - 1)]))
        grouped.append(int(best))

    abs_floor = max(18.0, span * 0.08, deriv_threshold * 1.6)
    out: list[dict[str, Any]] = []
    last_idx = -min_gap
    for idx in grouped:
        if idx - last_idx < min_gap:
            continue
        if idx < pre_win or idx + plateau_offset + plateau_win >= n or idx + eval_win >= n:
            continue
        if not bool(allowed_mask[idx]):
            continue
        pre = smooth[idx - pre_win : idx]
        post = smooth[idx + plateau_offset : idx + plateau_offset + plateau_win]
        if pre.size == 0 or post.size == 0:
            continue
        pre_mean = float(np.mean(pre))
        post_mean = float(np.mean(post))
        amp = float(post_mean - pre_mean)
        if abs(amp) < abs_floor:
            continue
        pre_std = float(np.std(pre))
        post_std = float(np.std(post))
        if pre_std > max(6.0, abs(amp) * 0.35):
            continue
        if post_std > max(8.0, abs(amp) * 0.50):
            continue
        out.append(
            {
                "idx": int(idx),
                "pre_mean": pre_mean,
                "post_mean": post_mean,
                "amp": amp,
                "pre_std": pre_std,
                "post_std": post_std,
            }
        )
        last_idx = int(idx)
    return out


def _analyze_event(
    sp: np.ndarray,
    gy: np.ndarray,
    idx: int,
    *,
    dt_ms: float,
    pre_win: int,
    plateau_offset: int,
    plateau_win: int,
    eval_win: int,
    settle_hold: int,
) -> dict[str, Any] | None:
    n = int(min(sp.size, gy.size))
    if idx < pre_win or idx + plateau_offset + plateau_win >= n or idx + eval_win >= n:
        return None
    pre_target = float(np.mean(sp[idx - pre_win : idx]))
    target = float(np.mean(sp[idx + plateau_offset : idx + plateau_offset + plateau_win]))
    pre_gyro = float(np.mean(gy[idx - pre_win : idx]))
    target_amp = float(target - pre_gyro)
    if abs(target_amp) < max(15.0, abs(target - pre_target) * 0.6):
        return None

    sign = 1.0 if target_amp >= 0.0 else -1.0
    response = gy[idx : idx + eval_win]
    if response.size < max(settle_hold + 2, 12):
        return None
    prog = sign * (response - pre_gyro)
    target_abs = abs(target_amp)
    if target_abs < 1e-6:
        return None

    t10_idx = np.where(prog >= 0.10 * target_abs)[0]
    t90_idx = np.where(prog >= 0.90 * target_abs)[0]
    delay_ms = float(t10_idx[0] * dt_ms) if t10_idx.size else None
    rise_ms = None
    if t10_idx.size and t90_idx.size and int(t90_idx[0]) >= int(t10_idx[0]):
        rise_ms = float((int(t90_idx[0]) - int(t10_idx[0])) * dt_ms)

    if sign > 0.0:
        overshoot = float(max(0.0, np.max(response) - target) / target_abs * 100.0)
    else:
        overshoot = float(max(0.0, target - np.min(response)) / target_abs * 100.0)

    steady_start = max(settle_hold, int(round(eval_win * 0.65)))
    steady_slice = response[steady_start:]
    if steady_slice.size == 0:
        steady_slice = response[-max(settle_hold, 1) :]
    steady_state_error = float(abs(np.mean(steady_slice) - target))

    tol = max(8.0, target_abs * 0.10)
    abs_err = np.abs(response - target)
    settle_idx = None
    for i in range(0, max(1, abs_err.size - settle_hold + 1)):
        if np.max(abs_err[i : i + settle_hold]) <= tol:
            settle_idx = int(i)
            break
    settling_ms = float(settle_idx * dt_ms) if settle_idx is not None else None

    quality_score = _event_quality(
        delay_ms=delay_ms,
        rise_ms=rise_ms,
        settling_ms=settling_ms,
        overshoot_percent=overshoot,
        steady_state_error=steady_state_error,
        target_amp=target_abs,
    )

    return {
        "event_idx": int(idx),
        "start_idx": int(idx),
        "end_idx": int(min(n - 1, idx + eval_win - 1)),
        "step_response_delay_ms": delay_ms,
        "rise_time_ms": rise_ms,
        "settling_time_ms": settling_ms,
        "overshoot_percent": overshoot,
        "steady_state_tracking_error": steady_state_error,
        "response_quality_score": quality_score,
        "confidence": _event_confidence(
            amp=target_abs,
            pre_std=float(np.std(sp[idx - pre_win : idx])),
            post_std=float(np.std(sp[idx + plateau_offset : idx + plateau_offset + plateau_win])),
            quality_score=quality_score,
            delay_ms=delay_ms,
            rise_ms=rise_ms,
        ),
        "target_amplitude": target_abs,
    }


def _aggregate_axis(events: list[dict[str, Any]], sample_count: int) -> dict[str, Any]:
    if not events:
        return _default_axis(sample_count)

    weights = [
        max(0.05, float(ev.get("confidence", 0.0)) * max(1.0, float(ev.get("target_amplitude", 1.0))))
        for ev in events
    ]
    values = {
        "step_response_delay_ms": [],
        "rise_time_ms": [],
        "settling_time_ms": [],
        "overshoot_percent": [],
        "steady_state_tracking_error": [],
        "response_quality_score": [],
    }
    for ev in events:
        for key in values:
            val = ev.get(key)
            if val is not None:
                values[key].append((float(val), float(max(0.05, ev.get("confidence", 0.0)))))

    def _agg(key: str, lo: float | None = None, hi: float | None = None) -> float | None:
        pairs = values[key]
        if not pairs:
            return None
        vals = [v for v, _ in pairs]
        ws = [w for _, w in pairs]
        return _sanitize_scalar(_weighted_mean_or_none(vals, ws), lo=lo, hi=hi)

    conf = float(np.mean([max(0.0, min(1.0, float(ev.get("confidence", 0.0)))) for ev in events]))
    conf = float(max(0.0, min(1.0, 0.20 + 0.45 * min(1.0, len(events) / 4.0) + 0.35 * conf)))
    out = {
        "step_response_delay_ms": _agg("step_response_delay_ms", lo=0.0, hi=500.0),
        "rise_time_ms": _agg("rise_time_ms", lo=0.0, hi=800.0),
        "settling_time_ms": _agg("settling_time_ms", lo=0.0, hi=1200.0),
        "overshoot_percent": _agg("overshoot_percent", lo=0.0, hi=250.0),
        "steady_state_tracking_error": _agg("steady_state_tracking_error", lo=0.0, hi=500.0),
        "response_quality_score": float(max(0.0, min(100.0, _agg("response_quality_score", lo=0.0, hi=100.0) or 0.0))),
        "confidence": conf,
        "sample_count": int(max(0, sample_count)),
        "event_count": int(len(events)),
        "event_windows": [
            {
                "start_idx": int(ev.get("start_idx", ev.get("event_idx", 0)) or 0),
                "end_idx": int(ev.get("end_idx", ev.get("event_idx", 0)) or 0),
                "event_idx": int(ev.get("event_idx", ev.get("start_idx", 0)) or 0),
                "overshoot_percent": _sanitize_scalar(ev.get("overshoot_percent"), lo=0.0, hi=250.0),
                "confidence": _sanitize_scalar(ev.get("confidence"), lo=0.0, hi=1.0),
            }
            for ev in events
        ],
        "notes": [],
    }
    if conf < 0.45:
        out["notes"].append("limited_event_consistency")
    if len(events) < 2:
        out["notes"].append("single_event_axis_summary")
    return out


def _merge_axes(axis_blocks: Mapping[str, Mapping[str, Any]], sample_count: int) -> dict[str, Any]:
    weights: list[float] = []
    merged_values: dict[str, list[float]] = {
        "step_response_delay_ms": [],
        "rise_time_ms": [],
        "settling_time_ms": [],
        "overshoot_percent": [],
        "steady_state_tracking_error": [],
        "response_quality_score": [],
    }
    valid_axes: dict[str, Mapping[str, Any]] = {}
    for axis in ("roll", "pitch", "yaw"):
        block = axis_blocks.get(axis)
        if not isinstance(block, Mapping):
            continue
        conf = float(max(0.0, min(1.0, block.get("confidence", 0.0) or 0.0)))
        events = int(block.get("event_count", 0) or 0)
        if events <= 0 or conf <= 0.0:
            continue
        weight = conf * max(1.0, float(events))
        valid_axes[axis] = block
        weights.append(weight)
        for key in merged_values:
            val = block.get(key)
            if val is not None:
                merged_values[key].append(float(val))

    if not valid_axes:
        out = _default_axis(sample_count)
        out["notes"] = ["no_usable_response_axes"]
        return out

    def _merge(key: str, lo: float | None = None, hi: float | None = None) -> float | None:
        vals: list[float] = []
        ws: list[float] = []
        for axis, block in valid_axes.items():
            val = block.get(key)
            if val is None:
                continue
            vals.append(float(val))
            ws.append(float(max(0.05, float(block.get("confidence", 0.0) or 0.0) * max(1, int(block.get("event_count", 0) or 0)))))
        return _sanitize_scalar(_weighted_mean_or_none(vals, ws), lo=lo, hi=hi)

    confidence = float(_weighted_mean_or_none(
        [float(block.get("confidence", 0.0) or 0.0) for block in valid_axes.values()],
        [float(max(1, int(block.get("event_count", 0) or 0))) for block in valid_axes.values()],
    ) or 0.0)
    out = {
        "step_response_delay_ms": _merge("step_response_delay_ms", lo=0.0, hi=500.0),
        "rise_time_ms": _merge("rise_time_ms", lo=0.0, hi=800.0),
        "settling_time_ms": _merge("settling_time_ms", lo=0.0, hi=1200.0),
        "overshoot_percent": _merge("overshoot_percent", lo=0.0, hi=250.0),
        "steady_state_tracking_error": _merge("steady_state_tracking_error", lo=0.0, hi=500.0),
        "response_quality_score": float(max(0.0, min(100.0, _merge("response_quality_score", lo=0.0, hi=100.0) or 0.0))),
        "confidence": float(max(0.0, min(1.0, confidence))),
        "sample_count": int(max(0, sample_count)),
        "event_count": int(sum(int(block.get("event_count", 0) or 0) for block in valid_axes.values())),
        "notes": [],
    }
    if len(valid_axes) == 1:
        out["notes"].append("single_axis_response_summary")
    return out


def analyze_step_response(
    samples: Mapping[str, Any] | None,
    segments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    gyro = _finite_2d((samples or {}).get("gyro"))
    setpoint = _finite_2d((samples or {}).get("setpoint"))
    time_us = _finite_1d((samples or {}).get("time_us"))
    n = int(min(gyro.shape[0], setpoint.shape[0], time_us.size))
    if n <= 0 or gyro.shape[1] < 3 or setpoint.shape[1] < 3:
        return {
            "applied": False,
            "step_response_delay_ms": None,
            "rise_time_ms": None,
            "settling_time_ms": None,
            "overshoot_percent": None,
            "steady_state_tracking_error": None,
            "response_quality_score": 0.0,
            "confidence": 0.0,
            "sample_count": 0,
            "event_count": 0,
            "axes": {axis: _default_axis(0) for axis in _AXES},
            "response_summary": _default_axis(0),
            "overshoot_summary": {"percent": None, "severity": "unknown", "axes": {}},
            "notes": ["insufficient_samples"],
        }

    gyro = gyro[:n, :3]
    setpoint = setpoint[:n, :3]
    time_us = time_us[:n]

    dt_ms = _dt_ms(time_us)
    pre_win = max(6, int(round(18.0 / dt_ms)))
    plateau_offset = max(4, int(round(16.0 / dt_ms)))
    plateau_win = max(8, int(round(22.0 / dt_ms)))
    eval_win = max(32, int(round(180.0 / dt_ms)))
    settle_hold = max(8, int(round(28.0 / dt_ms)))
    allowed = _allowed_mask(segments, n, max(plateau_win, int(round(20.0 / dt_ms))))

    axis_out: dict[str, dict[str, Any]] = {}
    response_windows: list[dict[str, Any]] = []
    notes: list[str] = []
    usable_axes = 0
    total_events = 0
    for axis_idx, axis_name in enumerate(_AXES):
        sp = setpoint[:, axis_idx]
        gy = gyro[:, axis_idx]
        candidates = _extract_candidates(
            sp,
            allowed,
            dt_ms=dt_ms,
            pre_win=pre_win,
            plateau_offset=plateau_offset,
            plateau_win=plateau_win,
            eval_win=eval_win,
        )
        events: list[dict[str, Any]] = []
        for cand in candidates:
            ev = _analyze_event(
                sp,
                gy,
                int(cand["idx"]),
                dt_ms=dt_ms,
                pre_win=pre_win,
                plateau_offset=plateau_offset,
                plateau_win=plateau_win,
                eval_win=eval_win,
                settle_hold=settle_hold,
            )
            if ev is None:
                continue
            events.append(ev)
        axis_block = _aggregate_axis(events, n)
        for win in axis_block.get("event_windows", []):
            if isinstance(win, Mapping):
                rec = dict(win)
                rec["axis"] = axis_name
                response_windows.append(rec)
        axis_out[axis_name] = axis_block
        total_events += int(axis_block.get("event_count", 0) or 0)
        if int(axis_block.get("event_count", 0) or 0) > 0 and float(axis_block.get("confidence", 0.0) or 0.0) >= 0.2:
            usable_axes += 1

    merged = _merge_axes(axis_out, n)
    if usable_axes >= 2:
        notes.append("multi_axis_response_summary")
    elif usable_axes == 1:
        notes.append("single_axis_response_summary")
    else:
        notes.append("response_windows_low_quality")
    if total_events <= 1:
        notes.append("limited_response_event_count")

    overshoot_axes = {
        axis: axis_out[axis].get("overshoot_percent")
        for axis in _AXES
        if axis_out.get(axis, {}).get("overshoot_percent") is not None
    }
    overshoot_percent = merged.get("overshoot_percent")
    out = {
        "applied": bool(int(merged.get("event_count", 0) or 0) > 0 and float(merged.get("confidence", 0.0) or 0.0) >= 0.2),
        "step_response_delay_ms": merged.get("step_response_delay_ms"),
        "rise_time_ms": merged.get("rise_time_ms"),
        "settling_time_ms": merged.get("settling_time_ms"),
        "overshoot_percent": overshoot_percent,
        "steady_state_tracking_error": merged.get("steady_state_tracking_error"),
        "response_quality_score": float(max(0.0, min(100.0, merged.get("response_quality_score", 0.0) or 0.0))),
        "confidence": float(max(0.0, min(1.0, merged.get("confidence", 0.0) or 0.0))),
        "sample_count": int(n),
        "event_count": int(total_events),
        "axes": axis_out,
        "response_summary": {
            "step_response_delay_ms": merged.get("step_response_delay_ms"),
            "rise_time_ms": merged.get("rise_time_ms"),
            "settling_time_ms": merged.get("settling_time_ms"),
            "overshoot_percent": overshoot_percent,
            "steady_state_tracking_error": merged.get("steady_state_tracking_error"),
            "response_quality_score": float(max(0.0, min(100.0, merged.get("response_quality_score", 0.0) or 0.0))),
            "event_count": int(total_events),
            "confidence": float(max(0.0, min(1.0, merged.get("confidence", 0.0) or 0.0))),
        },
        "overshoot_summary": {
            "percent": overshoot_percent,
            "severity": _overshoot_severity(_sanitize_scalar(overshoot_percent, lo=0.0, hi=250.0)),
            "axes": overshoot_axes,
        },
        "response_windows": response_windows,
        "notes": notes,
    }
    return out


__all__ = ["analyze_step_response"]
