# GyroCore WU4: adapted from AeroTuner backend/analysis/motor_saturation.py
from __future__ import annotations

import copy
from typing import Any, Mapping

import numpy as np


def _infer_motor_output_ceiling(data, motor_output_ceiling=None):
    if motor_output_ceiling is not None:
        try:
            ceiling = float(motor_output_ceiling)
        except (TypeError, ValueError):
            ceiling = 0.0
        if np.isfinite(ceiling) and ceiling > 0:
            return ceiling
    max_val = float(np.nanmax(data)) if data.size else 0.0
    if max_val <= 1.0:
        return 1.0
    if max_val <= 100.0:
        return 100.0
    if max_val <= 2000.0:
        return 2000.0
    return 2047.0 if max_val <= 2047.0 else max_val


def _normalize_motor_outputs(motor_data, motor_output_ceiling=None):
    data = np.array(motor_data, dtype=float)
    if data.size == 0:
        return data
    ceiling = _infer_motor_output_ceiling(data, motor_output_ceiling)
    if ceiling <= 1.0:
        return np.clip(data, 0.0, 1.0)
    if ceiling <= 100.0:
        return np.clip(data / ceiling, 0.0, 1.0)
    if float(np.nanmin(data)) >= 900.0 and ceiling <= 2000.0:
        return np.clip((data - 1000.0) / max(1.0, ceiling - 1000.0), 0.0, 1.0)
    return np.clip(data / ceiling, 0.0, 1.0)


def detect_saturation_windows(
    motor_data,
    windows,
    threshold=None,
    scale_max=None,
    saturation_ratio=0.975,
):
    """
    Mark response windows whose max motor output is near the DSHOT ceiling.

    ``windows`` is an iterable of mappings with ``start_idx`` and ``end_idx``.
    The returned list mirrors those windows with max-output and saturation flags.
    """
    if motor_data is None:
        return []
    data = np.array(motor_data, dtype=float)
    if data.ndim == 1:
        data = data.reshape((-1, 1))
    if data.ndim != 2 or data.shape[0] == 0:
        return []
    ceiling = _infer_motor_output_ceiling(data, scale_max)
    if threshold is None:
        raw_threshold = float(ceiling) * float(saturation_ratio)
    else:
        raw_threshold = float(threshold)
    norm_threshold = raw_threshold / float(ceiling) if ceiling else float(saturation_ratio)
    normalized = _normalize_motor_outputs(data, ceiling)
    out = []
    for window in windows or []:
        if not isinstance(window, dict):
            continue
        try:
            start = max(0, int(window.get("start_idx", 0)))
            end = min(data.shape[0], int(window.get("end_idx", start)) + 1)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        raw_slice = data[start:end]
        norm_slice = normalized[start:end]
        raw_max = float(np.nanmax(raw_slice)) if raw_slice.size else 0.0
        norm_max = float(np.nanmax(norm_slice)) if norm_slice.size else 0.0
        saturated = bool(raw_max >= raw_threshold or norm_max >= norm_threshold)
        rec = dict(window)
        rec.update(
            {
                "max_motor_output": round(raw_max, 4),
                "max_motor_normalized": round(norm_max, 4),
                "saturation_affected": saturated,
                "saturation_threshold": round(raw_threshold, 4),
                "saturation_ratio": round(norm_threshold, 4),
                "scale_max": ceiling,
            }
        )
        out.append(rec)
    return out


def summarize_saturation_affected_overshoot(windows):
    total = 0
    affected = 0
    max_output = 0.0
    for window in windows or []:
        if not isinstance(window, dict):
            continue
        total += 1
        if window.get("saturation_affected") is True:
            affected += 1
        try:
            max_output = max(max_output, float(window.get("max_motor_output") or 0.0))
        except (TypeError, ValueError):
            pass
    ratio = (affected / total) if total else 0.0
    if affected and ratio >= 0.5:
        classification = "saturation_limited"
    elif affected:
        classification = "partly_saturation_limited"
    else:
        classification = "not_saturation_limited"
    return {
        "window_count": total,
        "saturation_affected_count": affected,
        "saturation_affected_ratio": round(ratio, 4),
        "max_motor_output": round(max_output, 4),
        "classification": classification,
    }


def classify_overshoot_character(
    *,
    setpoint_derivative_leading_edge=False,
    fast_settling=False,
    post_settle_ringing=False,
    saturation_summary=None,
    high_throttle=False,
):
    """
    Generic overshoot classifier for tuning decisions.

    Craft class is intentionally not an input; callers may use craft class only as a
    soft prior when creating the evidence booleans passed here.
    """
    sat = saturation_summary if isinstance(saturation_summary, dict) else {}
    sat_ratio = float(sat.get("saturation_affected_ratio") or 0.0)
    saturated = sat_ratio > 0.0 or sat.get("classification") in {
        "saturation_limited",
        "partly_saturation_limited",
    }
    ff = bool(setpoint_derivative_leading_edge and fast_settling and not post_settle_ringing)
    ringing = bool(post_settle_ringing)
    if saturated and (ff or ringing):
        return "mixed"
    if saturated and (sat_ratio >= 0.5 or high_throttle):
        return "saturation_limited"
    if saturated:
        return "mixed"
    if ff:
        return "ff_driven"
    if ringing:
        return "p_underdamped"
    return "mixed"


def _response_event_windows(response_analysis: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(response_analysis, Mapping):
        return []
    raw = response_analysis.get("response_windows")
    if isinstance(raw, list):
        out: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, Mapping):
                continue
            try:
                start = int(item.get("start_idx", item.get("event_idx", 0)) or 0)
                end = int(item.get("end_idx", start) or start)
            except (TypeError, ValueError):
                continue
            if end < start:
                start, end = end, start
            rec = dict(item)
            rec["start_idx"] = start
            rec["end_idx"] = end
            out.append(rec)
        if out:
            return out

    axes = response_analysis.get("axes")
    if not isinstance(axes, Mapping):
        return []
    out = []
    for axis, block in axes.items():
        if not isinstance(block, Mapping):
            continue
        for item in block.get("event_windows") or []:
            if not isinstance(item, Mapping):
                continue
            try:
                start = int(item.get("start_idx", item.get("event_idx", 0)) or 0)
                end = int(item.get("end_idx", start) or start)
            except (TypeError, ValueError):
                continue
            if end < start:
                start, end = end, start
            rec = dict(item)
            rec["axis"] = str(axis)
            rec["start_idx"] = start
            rec["end_idx"] = end
            out.append(rec)
    return out


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(out):
        return None
    return float(out)


def attach_saturation_evidence_to_response(
    response_analysis: Mapping[str, Any] | None,
    motor_data,
    *,
    scale_max=None,
    saturation_ratio=0.975,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Attach motor-output saturation evidence to production response windows.

    The helper is deliberately fail-safe: when motor traces or response windows are
    absent, it marks saturation evidence unavailable instead of inferring a
    saturation-limited overshoot class.
    """
    response = copy.deepcopy(dict(response_analysis or {}))
    windows = _response_event_windows(response)
    data = np.array(motor_data, dtype=float) if motor_data is not None else np.array([])
    if data.ndim == 1 and data.size:
        data = data.reshape((-1, 1))

    evidence: dict[str, Any] = {
        "available": False,
        "reason": None,
        "window_count": 0,
        "saturation_affected_count": 0,
        "saturation_affected_ratio": 0.0,
        "classification": "unavailable",
    }

    if data.ndim != 2 or data.shape[0] == 0:
        evidence["reason"] = "motor_trace_unavailable"
        response["saturation_evidence"] = evidence
        overshoot_out = response.get("overshoot_summary")
        if not isinstance(overshoot_out, dict):
            overshoot_out = {}
        overshoot_out.setdefault("classification", "unknown")
        response["overshoot_summary"] = overshoot_out
        return response, evidence
    if not windows:
        evidence["reason"] = "response_windows_unavailable"
        response["saturation_evidence"] = evidence
        overshoot_out = response.get("overshoot_summary")
        if not isinstance(overshoot_out, dict):
            overshoot_out = {}
        overshoot_out.setdefault("classification", "unknown")
        response["overshoot_summary"] = overshoot_out
        return response, evidence

    detected = detect_saturation_windows(
        data,
        windows,
        scale_max=scale_max,
        saturation_ratio=saturation_ratio,
    )
    summary = summarize_saturation_affected_overshoot(detected)
    overshoot = response.get("overshoot_summary") if isinstance(response.get("overshoot_summary"), Mapping) else {}
    percent = _safe_float(overshoot.get("percent") if isinstance(overshoot, Mapping) else None)
    if percent is None:
        percent = _safe_float(response.get("overshoot_percent"))
    rise_ms = _safe_float(response.get("rise_time_ms"))
    settling_ms = _safe_float(response.get("settling_time_ms"))
    notes = response.get("notes") if isinstance(response.get("notes"), list) else []
    post_settle_ringing = any("ring" in str(note).lower() for note in notes) or (
        settling_ms is not None and settling_ms > 180.0
    )
    classification = classify_overshoot_character(
        setpoint_derivative_leading_edge=bool(percent is not None and percent >= 8.0 and (rise_ms is None or rise_ms <= 45.0)),
        fast_settling=bool(settling_ms is None or settling_ms <= 140.0),
        post_settle_ringing=post_settle_ringing,
        saturation_summary=summary,
        high_throttle=bool(summary.get("saturation_affected_ratio", 0.0) >= 0.25),
    )
    evidence = {
        "available": True,
        "reason": "response_windows_with_motor_trace",
        **summary,
        "classification": summary.get("classification", "not_saturation_limited"),
        "overshoot_classification": classification,
        "windows": detected,
    }
    response["saturation_evidence"] = evidence
    response["saturation_windows"] = detected
    response["overshoot_classification"] = classification
    overshoot_out = dict(overshoot) if isinstance(overshoot, Mapping) else {}
    overshoot_out["classification"] = classification
    overshoot_out["saturation_classification"] = evidence["classification"]
    response["overshoot_summary"] = overshoot_out
    return response, evidence


def compute_motor_saturation(motor_data, threshold=0.85):
    """
    motor_data: array-like shape (samples, motors)
    expected range:
      - either 0..1
      - or scaled (e.g. 1000–2000)

    returns:
      dict with saturation statistics
    """

    if motor_data is None or len(motor_data) == 0:
        return {
            "saturation_pct": 0,
            "maxed_pct": 0,
            "mean_output": 0.0,
            "p95_output": 0.0,
            "threshold": threshold,
            "status": "warning",
        }

    data = np.array(motor_data, dtype=float)

    # Detect Betaflight motor range (1000–2000)
    if data.max() > 100:
        # assume BF scale
        data = (data - 1000.0) / 1000.0
    else:
        # already normalized (0..1)
        pass

    # clamp safety
    data = np.clip(data, 0.0, 1.0)

    near_max = data > threshold
    maxed = data > 0.98

    total = data.size

    saturation_pct = (near_max.sum() / total) * 100
    maxed_pct = (maxed.sum() / total) * 100
    mean_output = float(np.mean(data))
    p95_output = float(np.percentile(data, 95))

    if saturation_pct < 10:
        status = "good"
    elif saturation_pct < 25:
        status = "warning"
    else:
        status = "critical"

    return {
        "saturation_pct": round(float(saturation_pct), 2),
        "maxed_pct": round(float(maxed_pct), 2),
        "mean_output": round(mean_output, 3),
        "p95_output": round(p95_output, 3),
        "threshold": threshold,
        "status": status,
    }
