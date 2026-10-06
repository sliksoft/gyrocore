# GyroCore WU4: adapted from AeroTuner backend/analysis/d_effectiveness_analysis.py
"""
Deterministic D-effectiveness analysis from setpoint / gyro traces.

The goal is practical tuning guidance rather than strict control-theory purity:
estimate whether D-term is meaningfully helping response, or mostly adding
noise / heat / motor stress cost.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np

_AXES: tuple[str, ...] = ("roll", "pitch", "yaw")
_ACTIVE_SEGMENT_TYPES = frozenset({"maneuver", "punch", "propwash_candidate"})


def _finite_1d(x: Any) -> np.ndarray:
    return np.nan_to_num(np.asarray(x, dtype=float).reshape(-1), nan=0.0, posinf=0.0, neginf=0.0)


def _finite_2d(x: Any, cols: int) -> np.ndarray:
    arr = np.asarray(x, dtype=float)
    if arr.ndim != 2:
        return np.zeros((0, cols), dtype=float)
    out = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    if out.shape[1] >= cols:
        return out[:, :cols]
    pad = np.zeros((out.shape[0], cols - out.shape[1]), dtype=float)
    return np.concatenate([out, pad], axis=1)


def _moving_mean(x: np.ndarray, win: int) -> np.ndarray:
    a = _finite_1d(x)
    if a.size == 0:
        return a
    w = max(1, int(win))
    if w == 1:
        return a.copy()
    k = np.ones(w, dtype=float) / float(w)
    return np.convolve(a, k, mode="same")


def _rms(x: np.ndarray) -> float:
    a = _finite_1d(x)
    if a.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(a * a)))


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    x = _finite_1d(a)
    y = _finite_1d(b)
    n = int(min(x.size, y.size))
    if n < 8:
        return 0.0
    x = x[:n]
    y = y[:n]
    sx = float(np.std(x))
    sy = float(np.std(y))
    if sx <= 1e-9 or sy <= 1e-9:
        return 0.0
    out = float(np.corrcoef(x, y)[0, 1])
    if not np.isfinite(out):
        return 0.0
    return float(max(-1.0, min(1.0, out)))


def _weighted_mean(values: list[float], weights: list[float], default: float = 0.0) -> float:
    if not values:
        return float(default)
    v = np.asarray(values, dtype=float)
    w = np.asarray(weights, dtype=float)
    mask = np.isfinite(v) & np.isfinite(w) & (w > 0.0)
    if not np.any(mask):
        mask = np.isfinite(v)
        if not np.any(mask):
            return float(default)
        return float(np.mean(v[mask]))
    return float(np.average(v[mask], weights=w[mask]))


def _clamp01(v: Any) -> float:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(out):
        return 0.0
    return float(max(0.0, min(1.0, out)))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        out = float(v)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(out):
        return default
    return float(out)


def _dt_ms(time_us: np.ndarray) -> float:
    tu = _finite_1d(time_us)
    if tu.size < 2:
        return 2.0
    diff = np.diff(tu)
    diff = diff[np.isfinite(diff) & (diff > 0.0)]
    if diff.size == 0:
        return 2.0
    out = float(np.median(diff) / 1000.0)
    if not np.isfinite(out) or out <= 0.0:
        return 2.0
    return float(max(0.25, min(20.0, out)))


def _allowed_mask(segments: Mapping[str, Any] | None, n: int, margin: int) -> np.ndarray:
    mask = np.ones(n, dtype=bool)
    if not isinstance(segments, Mapping):
        return mask
    raw = segments.get("segments")
    if not isinstance(raw, list):
        return mask
    active = [seg for seg in raw if isinstance(seg, Mapping) and seg.get("type") in _ACTIVE_SEGMENT_TYPES]
    if not active:
        return mask
    out = np.zeros(n, dtype=bool)
    for seg in active:
        try:
            s = int(seg.get("start_idx", 0))
            e = int(seg.get("end_idx", 0))
        except (TypeError, ValueError):
            continue
        if e < s:
            s, e = e, s
        s = max(0, min(n - 1, s - margin))
        e = max(0, min(n - 1, e + margin))
        out[s : e + 1] = True
    return out if np.any(out) else mask


def _noise_context(analysis: Mapping[str, Any] | None) -> float:
    if not isinstance(analysis, Mapping):
        return 0.0
    noise = analysis.get("noise_model")
    if isinstance(noise, Mapping):
        ratio = noise.get("hf_ratio", noise.get("ratio"))
        if ratio is not None:
            return _clamp01(ratio)
        score = noise.get("score")
        if score is not None:
            return _clamp01(_safe_float(score, 0.0) / 100.0)
    signal = analysis.get("signal")
    if isinstance(signal, Mapping):
        inner = signal.get("noise_model")
        if isinstance(inner, Mapping):
            ratio = inner.get("hf_ratio", inner.get("ratio"))
            if ratio is not None:
                return _clamp01(ratio)
    metrics = analysis.get("metrics")
    if isinstance(metrics, Mapping):
        noise = metrics.get("noise")
        if isinstance(noise, Mapping):
            value = _safe_float(noise.get("value"), 100.0)
            return _clamp01((100.0 - value) / 100.0)
    return 0.0


def _motor_context(analysis: Mapping[str, Any] | None) -> tuple[float, bool]:
    if not isinstance(analysis, Mapping):
        return (0.0, False)
    health_risk = 0.0
    desync = False
    md = analysis.get("motor_diagnostics")
    if isinstance(md, Mapping):
        health_raw = md.get("health")
        if health_raw is not None:
            h = _safe_float(health_raw, 100.0)
            if h <= 1.0:
                health_risk = _clamp01(1.0 - h)
            else:
                health_risk = _clamp01((100.0 - h) / 100.0)
        desync = bool(md.get("has_desync_risk", False))
    probs = analysis.get("problems")
    rows: list[Mapping[str, Any]] = []
    if isinstance(probs, list):
        rows = [row for row in probs if isinstance(row, Mapping)]
    elif isinstance(probs, Mapping):
        inner = probs.get("problems")
        if isinstance(inner, list):
            rows = [row for row in inner if isinstance(row, Mapping)]
    sev = 0.0
    for row in rows:
        if str(row.get("type", "")).strip().lower() == "motor_issue":
            raw = row.get("severity")
            if isinstance(raw, str):
                sev = max(sev, {"low": 0.25, "medium": 0.55, "high": 0.9}.get(raw.strip().lower(), 0.0))
            else:
                sev = max(sev, _clamp01(raw))
    return (max(health_risk, sev), desync)


def _response_axis_context(
    response_analysis: Mapping[str, Any] | None,
    axis_name: str,
) -> tuple[float, float]:
    if not isinstance(response_analysis, Mapping):
        return (0.5, 0.0)
    axes = response_analysis.get("axes")
    block = axes.get(axis_name) if isinstance(axes, Mapping) else None
    if not isinstance(block, Mapping):
        return (
            _clamp01(_safe_float(response_analysis.get("response_quality_score"), 50.0) / 100.0),
            _clamp01(_safe_float(response_analysis.get("overshoot_percent"), 0.0) / 35.0),
        )
    quality = _clamp01(_safe_float(block.get("response_quality_score"), 50.0) / 100.0)
    overshoot = _clamp01(_safe_float(block.get("overshoot_percent"), 0.0) / 35.0)
    return (quality, overshoot)


def _window_candidates(sp: np.ndarray, allowed_mask: np.ndarray, dt_ms: float) -> list[dict[str, int | float]]:
    n = int(sp.size)
    if n < 80:
        return []
    smooth = _moving_mean(sp, max(3, int(round(8.0 / max(dt_ms, 0.25)))))
    dsp = np.abs(np.diff(smooth))
    if dsp.size == 0:
        return []
    span = float(np.percentile(np.abs(smooth), 95.0))
    thr = max(6.0, float(np.median(dsp)) * 5.0, float(np.percentile(dsp, 95.0)) * 0.45, span * 0.03)
    raw = np.where(dsp >= thr)[0] + 1
    if raw.size == 0:
        return []

    pre_win = max(6, int(round(12.0 / max(dt_ms, 0.25))))
    plateau_offset = max(10, int(round(42.0 / max(dt_ms, 0.25))))
    plateau_win = max(8, int(round(18.0 / max(dt_ms, 0.25))))
    eval_win = max(45, int(round(165.0 / max(dt_ms, 0.25))))
    min_gap = max(plateau_win, int(round(36.0 / max(dt_ms, 0.25))))

    grouped: list[int] = []
    group: list[int] = []
    for idx in raw.tolist():
        if not group or idx - group[-1] <= max(2, min_gap // 3):
            group.append(int(idx))
            continue
        grouped.append(int(max(group, key=lambda i: float(dsp[min(max(i - 1, 0), dsp.size - 1)]))))
        group = [int(idx)]
    if group:
        grouped.append(int(max(group, key=lambda i: float(dsp[min(max(i - 1, 0), dsp.size - 1)]))))

    out: list[dict[str, int | float]] = []
    last_idx = -min_gap
    amp_floor = max(18.0, span * 0.08, thr * 1.6)
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
        amp = float(np.mean(post) - np.mean(pre))
        if abs(amp) < amp_floor:
            continue
        if float(np.std(pre)) > max(6.0, abs(amp) * 0.35):
            continue
        out.append(
            {
                "idx": int(idx),
                "amp": float(amp),
                "pre_win": int(pre_win),
                "eval_win": int(eval_win),
            }
        )
        last_idx = idx
    return out


def _shift_left(x: np.ndarray, lead: int) -> np.ndarray:
    a = _finite_1d(x)
    if a.size == 0 or lead <= 0:
        return a.copy()
    if lead >= a.size:
        return np.full_like(a, a[-1] if a.size else 0.0)
    out = np.empty_like(a)
    out[:-lead] = a[lead:]
    out[-lead:] = a[-1]
    return out


def _axis_default(sample_count: int, signal_source: str = "proxy_error_derivative") -> dict[str, Any]:
    return {
        "applied": False,
        "signal_source": signal_source,
        "d_effectiveness_score": 50.0,
        "d_response_correlation": 0.0,
        "d_noise_penalty": 0.0,
        "d_heat_risk_bias": 0.0,
        "d_utility_estimate": 0.0,
        "d_effectiveness_confidence": 0.0,
        "sample_count": int(max(0, sample_count)),
        "event_count": 0,
        "usable_window_count": 0,
        "summary": summarize_d_effectiveness(
            score=50.0,
            correlation=0.0,
            noise_penalty=0.0,
            heat_risk=0.0,
            utility=0.0,
            confidence=0.0,
            event_count=0,
            usable_window_count=0,
            notes=["insufficient_d_signal_windows"],
        ),
        "notes": ["insufficient_d_signal_windows"],
    }


def summarize_d_effectiveness(
    *,
    score: float,
    correlation: float,
    noise_penalty: float,
    heat_risk: float,
    utility: float,
    confidence: float,
    event_count: int,
    usable_window_count: int,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    notes = [str(x) for x in notes or []]
    low_conf = confidence < 0.28 or usable_window_count <= 0
    d_effective = score >= 58.0 and utility >= 0.58 and correlation >= 0.28
    d_limited_by_noise = noise_penalty >= 0.56
    d_limited_by_motor_risk = heat_risk >= 0.56
    d_low_value = score < 48.0 or utility < 0.40 or correlation < 0.18
    d_risky = heat_risk >= 0.76 or (noise_penalty >= 0.72 and utility < 0.56)
    likely_more_d_useful = (
        confidence >= 0.55
        and score >= 72.0
        and correlation >= 0.38
        and noise_penalty < 0.45
        and heat_risk < 0.45
    )

    if low_conf:
        label = "insufficient_signal"
        text = "D-effectiveness signal is too weak for a strong conclusion"
    elif d_effective and (d_limited_by_noise or d_limited_by_motor_risk):
        label = "d_helping_but_limited"
        if d_limited_by_motor_risk and d_limited_by_noise:
            text = "D is helping, but noise and motor stress are limiting headroom"
        elif d_limited_by_motor_risk:
            text = "D is helping, but motor / thermal risk is limiting headroom"
        else:
            text = "D is helping, but noise is limiting headroom"
    elif d_risky:
        label = "d_risky"
        text = "Current D behavior looks expensive relative to noise / motor risk"
    elif d_effective:
        label = "d_helping_and_usable"
        text = "D is contributing useful damping with usable headroom"
    else:
        label = "d_low_value"
        text = "D contribution looks weak relative to the observed response"

    return {
        "label": label,
        "text": text,
        "d_effective": bool(d_effective and not low_conf),
        "d_limited_by_noise": bool(d_limited_by_noise and not low_conf),
        "d_limited_by_motor_risk": bool(d_limited_by_motor_risk and not low_conf),
        "d_low_value": bool(d_low_value and not low_conf),
        "d_risky": bool(d_risky and not low_conf),
        "likely_more_d_useful": bool(likely_more_d_useful and not low_conf),
        "event_count": int(max(0, event_count)),
        "usable_window_count": int(max(0, usable_window_count)),
        "notes": notes,
    }


def _axis_signal_source(d_axis: np.ndarray) -> str:
    if d_axis.size == 0:
        return "proxy_error_derivative"
    if not np.any(np.isfinite(d_axis)):
        return "proxy_error_derivative"
    if float(np.percentile(np.abs(np.nan_to_num(d_axis)), 90.0)) <= 1e-6:
        return "proxy_error_derivative"
    return "axis_d"


def _analyze_axis(
    axis_name: str,
    sp: np.ndarray,
    gyro: np.ndarray,
    d_axis: np.ndarray,
    throttle: np.ndarray,
    motors: np.ndarray,
    time_us: np.ndarray,
    *,
    analysis: Mapping[str, Any] | None,
    response_analysis: Mapping[str, Any] | None,
    segments: Mapping[str, Any] | None,
) -> dict[str, Any]:
    n = int(min(sp.size, gyro.size))
    source = _axis_signal_source(d_axis)
    if n < 80:
        return _axis_default(n, source)

    sp = _finite_1d(sp[:n])
    gy = _finite_1d(gyro[:n])
    thr = _finite_1d(throttle[:n]) if throttle.size else np.zeros((n,), dtype=float)
    mot = _finite_2d(motors[:n], 4) if motors.size else np.zeros((n, 4), dtype=float)
    tu = _finite_1d(time_us[:n]) if time_us.size else np.arange(n, dtype=float)
    dt_ms = _dt_ms(tu)
    dt_s = max(1e-4, dt_ms / 1000.0)
    allowed = _allowed_mask(segments, n, max(4, int(round(20.0 / max(dt_ms, 0.25)))))
    windows = _window_candidates(sp, allowed, dt_ms)
    if not windows:
        out = _axis_default(n, source)
        out["notes"] = ["no_usable_d_windows"]
        out["summary"] = summarize_d_effectiveness(
            score=50.0,
            correlation=0.0,
            noise_penalty=0.0,
            heat_risk=0.0,
            utility=0.0,
            confidence=0.0,
            event_count=0,
            usable_window_count=0,
            notes=out["notes"],
        )
        return out

    error = sp - gy
    error_smooth = _moving_mean(error, max(3, int(round(6.0 / max(dt_ms, 0.25)))))
    err_rate = np.gradient(error_smooth, dt_s)
    future_err_rate = _shift_left(err_rate, max(1, int(round(8.0 / max(dt_ms, 0.25)))))
    if source == "axis_d":
        d_sig_full = _moving_mean(_finite_1d(d_axis[:n]), max(1, int(round(4.0 / max(dt_ms, 0.25)))))
    else:
        d_sig_full = -_moving_mean(err_rate, max(2, int(round(4.0 / max(dt_ms, 0.25)))))

    d_scale = max(1e-6, float(np.percentile(np.abs(d_sig_full), 90.0)))
    err_scale = max(1e-6, float(np.percentile(np.abs(err_rate), 90.0)))
    noise_ctx = _noise_context(analysis)
    motor_risk_ctx, has_desync = _motor_context(analysis)
    resp_quality_ctx, resp_overshoot_ctx = _response_axis_context(response_analysis, axis_name)

    weights: list[float] = []
    corrs: list[float] = []
    penalties_noise: list[float] = []
    heat_risks: list[float] = []
    utilities: list[float] = []
    confidences: list[float] = []
    event_notes: set[str] = set()
    usable = 0

    for win in windows:
        idx = int(win["idx"])
        amp = abs(float(win["amp"]))
        end = min(n, idx + int(win["eval_win"]))
        if end - idx < 24:
            continue

        early_end = min(end, idx + max(10, int(round(42.0 / max(dt_ms, 0.25)))))
        late_start = min(end - 6, idx + max(18, int(round(96.0 / max(dt_ms, 0.25)))))
        if early_end <= idx + 4 or late_start <= early_end:
            continue

        d_seg = d_sig_full[idx:end]
        ferr = future_err_rate[idx:end]
        e_seg = error_smooth[idx:end]
        g_seg = gy[idx:end]
        thr_seg = thr[idx:end] if thr.size else np.zeros((end - idx,), dtype=float)
        mot_seg = mot[idx:end] if mot.size else np.zeros((end - idx, 4), dtype=float)

        if d_seg.size < 12 or ferr.size < 12:
            continue

        corr_pos = _corr(d_seg, -ferr)
        corr_neg = _corr(-d_seg, -ferr)
        corr = max(0.0, corr_pos, corr_neg)

        early_abs_err = float(np.mean(np.abs(e_seg[: early_end - idx])))
        late_abs_err = float(np.mean(np.abs(e_seg[late_start - idx :])))
        improvement_raw = (early_abs_err - late_abs_err) / max(5.0, early_abs_err)
        improvement = _clamp01(0.5 + 0.5 * improvement_raw)

        target = float(sp[min(end - 1, idx + max(1, int(round(36.0 / max(dt_ms, 0.25)))))] )
        if float(win["amp"]) >= 0.0:
            overshoot = max(0.0, float(np.max(g_seg) - target))
        else:
            overshoot = max(0.0, float(target - np.min(g_seg)))
        overshoot_penalty = _clamp01(overshoot / max(20.0, amp))

        settle_penalty = _clamp01(late_abs_err / max(12.0, amp * 0.7))
        activity_norm = _clamp01(_rms(d_seg) / d_scale)
        demand_norm = _clamp01((0.55 * (_rms(err_rate[idx:end]) / err_scale)) + (0.45 * amp / 240.0))

        d_smooth = _moving_mean(d_seg, max(3, int(round(4.0 / max(dt_ms, 0.25)))))
        hf_ratio = _rms(d_seg - d_smooth) / max(1e-6, _rms(d_seg))
        noise_penalty = _clamp01((0.68 * min(1.0, hf_ratio / 0.92)) + (0.32 * noise_ctx))

        motor_spread = 0.0
        if mot_seg.size:
            mot_mean = np.mean(np.abs(mot_seg), axis=1)
            valid = mot_mean > 1e-6
            if np.any(valid):
                spread = np.std(mot_seg[valid], axis=1) / np.maximum(1.0, mot_mean[valid])
                motor_spread = _clamp01(float(np.mean(spread)) / 0.12)
        throttle_risk = _clamp01(float(np.mean(thr_seg))) if thr_seg.size else 0.0
        heat_risk = _clamp01(
            (0.34 * motor_risk_ctx)
            + (0.16 * (1.0 if has_desync else 0.0))
            + (0.18 * throttle_risk)
            + (0.14 * motor_spread)
            + (0.10 * noise_ctx)
            + (0.08 * activity_norm)
        )

        utility = _clamp01(
            (0.34 * corr)
            + (0.24 * improvement)
            + (0.11 * demand_norm)
            + (0.10 * (1.0 - overshoot_penalty))
            + (0.09 * (1.0 - settle_penalty))
            + (0.07 * resp_quality_ctx)
            + (0.05 * (1.0 - resp_overshoot_ctx))
            - (0.18 * noise_penalty)
            - (0.12 * heat_risk)
        )

        confidence = _clamp01(
            0.14
            + (0.18 * _clamp01(amp / 220.0))
            + (0.16 * demand_norm)
            + (0.16 * activity_norm)
            + (0.12 * (1.0 - noise_penalty))
            + (0.10 * (1.0 - settle_penalty))
            + (0.08 * resp_quality_ctx)
            + (0.06 if source == "axis_d" else 0.0)
        )
        if source != "axis_d":
            confidence = min(confidence, 0.72)

        weight = max(0.05, confidence) * max(0.20, min(1.5, amp / 120.0))
        weights.append(weight)
        corrs.append(corr)
        penalties_noise.append(noise_penalty)
        heat_risks.append(heat_risk)
        utilities.append(utility)
        confidences.append(confidence)
        usable += 1

        if source != "axis_d":
            event_notes.add("proxy_d_signal_used")
        if noise_penalty >= 0.60:
            event_notes.add("d_noise_limited")
        if heat_risk >= 0.58:
            event_notes.add("d_motor_heat_limited")
        if corr < 0.25:
            event_notes.add("d_response_correlation_weak")
        if overshoot_penalty >= 0.40:
            event_notes.add("d_overshoot_support_weak")

    if usable <= 0 or not weights:
        out = _axis_default(n, source)
        out["event_count"] = len(windows)
        out["notes"] = ["d_windows_rejected_low_quality"]
        out["summary"] = summarize_d_effectiveness(
            score=50.0,
            correlation=0.0,
            noise_penalty=0.0,
            heat_risk=0.0,
            utility=0.0,
            confidence=0.12 if windows else 0.0,
            event_count=len(windows),
            usable_window_count=0,
            notes=out["notes"],
        )
        out["d_effectiveness_confidence"] = 0.12 if windows else 0.0
        return out

    corr = _weighted_mean(corrs, weights, 0.0)
    noise_penalty = _weighted_mean(penalties_noise, weights, 0.0)
    heat_risk = _weighted_mean(heat_risks, weights, 0.0)
    utility = _weighted_mean(utilities, weights, 0.0)
    confidence = _weighted_mean(confidences, weights, 0.0)
    confidence = _clamp01(confidence * min(1.0, 0.55 + 0.20 * usable))

    raw_score = 100.0 * (
        (0.47 * utility)
        + (0.24 * corr)
        + (0.16 * (1.0 - noise_penalty))
        + (0.13 * (1.0 - heat_risk))
    )
    score = 50.0 + (raw_score - 50.0) * (0.35 + 0.65 * confidence)
    score = float(max(0.0, min(100.0, score)))

    notes = sorted(event_notes)
    if usable < len(windows):
        notes.append("d_window_quality_rejections")
    summary = summarize_d_effectiveness(
        score=score,
        correlation=corr,
        noise_penalty=noise_penalty,
        heat_risk=heat_risk,
        utility=utility,
        confidence=confidence,
        event_count=len(windows),
        usable_window_count=usable,
        notes=notes,
    )

    return {
        "applied": bool(usable > 0),
        "signal_source": source,
        "d_effectiveness_score": score,
        "d_response_correlation": corr,
        "d_noise_penalty": noise_penalty,
        "d_heat_risk_bias": heat_risk,
        "d_utility_estimate": utility,
        "d_effectiveness_confidence": confidence,
        "sample_count": int(n),
        "event_count": int(len(windows)),
        "usable_window_count": int(usable),
        "summary": summary,
        "notes": notes,
    }


def merge_axis_d_effectiveness(axes: Mapping[str, Any] | None) -> dict[str, Any]:
    axes = axes if isinstance(axes, Mapping) else {}
    weights: list[float] = []
    scores: list[float] = []
    corrs: list[float] = []
    noise_penalties: list[float] = []
    heat_risks: list[float] = []
    utilities: list[float] = []
    confidences: list[float] = []
    sources: list[str] = []
    axis_summary: dict[str, Any] = {}
    notes: set[str] = set()
    total_events = 0
    total_windows = 0

    for axis_name in _AXES:
        block = axes.get(axis_name)
        if not isinstance(block, Mapping):
            continue
        conf = _clamp01(block.get("d_effectiveness_confidence"))
        events = int(max(0, _safe_float(block.get("event_count"), 0.0)))
        usable = int(max(0, _safe_float(block.get("usable_window_count"), 0.0)))
        axis_weight = (1.0 if axis_name in ("roll", "pitch") else 0.35) * max(0.05, conf) * max(
            0.35, min(1.5, 0.60 + 0.20 * usable)
        )
        weights.append(axis_weight)
        scores.append(_safe_float(block.get("d_effectiveness_score"), 50.0))
        corrs.append(_clamp01(block.get("d_response_correlation")))
        noise_penalties.append(_clamp01(block.get("d_noise_penalty")))
        heat_risks.append(_clamp01(block.get("d_heat_risk_bias")))
        utilities.append(_clamp01(block.get("d_utility_estimate")))
        confidences.append(conf)
        sources.append(str(block.get("signal_source") or "proxy_error_derivative"))
        total_events += events
        total_windows += usable
        summary = block.get("summary") if isinstance(block.get("summary"), Mapping) else {}
        axis_summary[axis_name] = {
            "score": _safe_float(block.get("d_effectiveness_score"), 50.0),
            "confidence": conf,
            "event_count": events,
            "usable_window_count": usable,
            "label": str(summary.get("label") or "insufficient_signal"),
        }
        raw_notes = block.get("notes")
        if isinstance(raw_notes, list):
            notes.update(str(x) for x in raw_notes[:6])

    if not weights:
        summary = summarize_d_effectiveness(
            score=50.0,
            correlation=0.0,
            noise_penalty=0.0,
            heat_risk=0.0,
            utility=0.0,
            confidence=0.0,
            event_count=0,
            usable_window_count=0,
            notes=["insufficient_d_signal_windows"],
        )
        return {
            "applied": False,
            "signal_source": "proxy_error_derivative",
            "d_effectiveness_score": 50.0,
            "d_response_correlation": 0.0,
            "d_noise_penalty": 0.0,
            "d_heat_risk_bias": 0.0,
            "d_utility_estimate": 0.0,
            "d_effectiveness_confidence": 0.0,
            "event_count": 0,
            "usable_window_count": 0,
            "summary": summary,
            "axis_summary": axis_summary,
            "notes": ["insufficient_d_signal_windows"],
            "axes": dict(axes),
        }

    score = _weighted_mean(scores, weights, 50.0)
    corr = _weighted_mean(corrs, weights, 0.0)
    noise_penalty = _weighted_mean(noise_penalties, weights, 0.0)
    heat_risk = _weighted_mean(heat_risks, weights, 0.0)
    utility = _weighted_mean(utilities, weights, 0.0)
    confidence = _weighted_mean(confidences, weights, 0.0)
    confidence = _clamp01(confidence * min(1.0, 0.55 + 0.12 * total_windows))

    if all(src == "axis_d" for src in sources):
        signal_source = "axis_d"
    elif any(src == "axis_d" for src in sources):
        signal_source = "mixed"
    else:
        signal_source = "proxy_error_derivative"

    merged_notes = sorted(notes)
    summary = summarize_d_effectiveness(
        score=score,
        correlation=corr,
        noise_penalty=noise_penalty,
        heat_risk=heat_risk,
        utility=utility,
        confidence=confidence,
        event_count=total_events,
        usable_window_count=total_windows,
        notes=merged_notes,
    )
    return {
        "applied": bool(total_windows > 0),
        "signal_source": signal_source,
        "d_effectiveness_score": float(max(0.0, min(100.0, score))),
        "d_response_correlation": corr,
        "d_noise_penalty": noise_penalty,
        "d_heat_risk_bias": heat_risk,
        "d_utility_estimate": utility,
        "d_effectiveness_confidence": confidence,
        "event_count": int(max(0, total_events)),
        "usable_window_count": int(max(0, total_windows)),
        "summary": summary,
        "axis_summary": axis_summary,
        "notes": merged_notes,
        "axes": dict(axes),
    }


def analyze_d_effectiveness(
    samples: Mapping[str, Any] | None,
    analysis: Mapping[str, Any] | None = None,
    *,
    response_analysis: Mapping[str, Any] | None = None,
    segments: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    bundle = samples if isinstance(samples, Mapping) else {}
    gyro = _finite_2d(bundle.get("gyro"), 3)
    sp = _finite_2d(bundle.get("setpoint"), 3)
    d_term = _finite_2d(bundle.get("d_term"), 3)
    throttle = _finite_1d(bundle.get("throttle"))
    motors = _finite_2d(bundle.get("motors"), 4)
    time_us = _finite_1d(bundle.get("time_us"))

    n = int(min(gyro.shape[0], sp.shape[0]))
    if n <= 0:
        return merge_axis_d_effectiveness({})

    axes: dict[str, Any] = {}
    for idx, axis_name in enumerate(_AXES):
        axes[axis_name] = _analyze_axis(
            axis_name,
            sp[:n, idx],
            gyro[:n, idx],
            d_term[:n, idx] if d_term.shape[0] >= n else np.zeros((n,), dtype=float),
            throttle[:n] if throttle.size >= n else np.zeros((n,), dtype=float),
            motors[:n, :] if motors.shape[0] >= n else np.zeros((n, 4), dtype=float),
            time_us[:n] if time_us.size >= n else np.arange(n, dtype=float),
            analysis=analysis,
            response_analysis=response_analysis,
            segments=segments,
        )
    return merge_axis_d_effectiveness(axes)
