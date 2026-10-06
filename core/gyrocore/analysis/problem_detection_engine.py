# GyroCore WU4: adapted from AeroTuner backend/analysis/problem_detection_engine.py
"""
Problem detection from metrics_engine + segment_engine outputs.

Combines segment context with performance metrics using multi-factor scores
(not single hard thresholds). Deterministic and JSON-safe.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np

_PROBLEM_ORDER = (
    "propwash",
    "oscillation",
    "noise",
    "low_tracking",
    "motor_issue",
)

_SEVERITY_ORDER = ("low", "medium", "high")


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(v):
        return default
    return v


def _clamp01(x: float) -> float:
    return float(np.clip(_safe_float(x, 0.0), 0.0, 1.0))


def _norm_metrics(metrics: Any) -> Dict[str, Any]:
    if not isinstance(metrics, dict):
        metrics = {}
    tr = metrics.get("tracking") if isinstance(metrics.get("tracking"), dict) else {}
    nz = metrics.get("noise") if isinstance(metrics.get("noise"), dict) else {}
    res = metrics.get("resonance") if isinstance(metrics.get("resonance"), dict) else {}
    pw = metrics.get("propwash") if isinstance(metrics.get("propwash"), dict) else {}
    mo = metrics.get("motor") if isinstance(metrics.get("motor"), dict) else {}
    return {
        "tracking": {
            "score": float(np.clip(_safe_float(tr.get("score"), 50.0), 0.0, 100.0)),
            "mean_error": _safe_float(tr.get("mean_error"), 0.0),
        },
        "noise": {
            "value": float(np.clip(_safe_float(nz.get("value"), 50.0), 0.0, 100.0)),
            "hf_ratio": _clamp01(_safe_float(nz.get("hf_ratio"), 0.0)),
            "grade": str(nz.get("grade", "D")),
        },
        "resonance": {
            "severity": str(res.get("severity", "low")).lower(),
        },
        "propwash": {
            "level": str(pw.get("level", "unknown")),
            "confidence": _clamp01(pw.get("confidence", 0.0)),
        },
        "motor": {
            "health": float(np.clip(_safe_float(mo.get("health"), 100.0), 0.0, 100.0)),
            "imbalance": max(0.0, _safe_float(mo.get("imbalance"), 0.0)),
            "has_desync_risk": bool(mo.get("has_desync_risk", False)),
        },
    }


def _norm_segments(segments: Any) -> List[dict[str, Any]]:
    if not isinstance(segments, dict):
        return []
    raw = segments.get("segments")
    if not isinstance(raw, list):
        return []
    out: List[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def _indices_by_type(segs: List[dict[str, Any]], typ: str) -> List[int]:
    idx: List[int] = []
    for i, s in enumerate(segs):
        if str(s.get("type", "")) == typ:
            idx.append(i)
    return idx


def _segment_fraction(segs: List[dict[str, Any]], typ: str) -> float:
    if not segs:
        return 0.0
    n = sum(1 for s in segs if str(s.get("type", "")) == typ)
    return float(n) / float(len(segs))


def _smooth_gate(x: float, lo: float, hi: float) -> float:
    """Rise from 0 at lo to 1 at hi (linear)."""
    if hi <= lo:
        return 1.0 if x >= lo else 0.0
    t = (x - lo) / (hi - lo)
    return float(np.clip(t, 0.0, 1.0))


def _severity_from_score(s: float) -> str:
    s = _clamp01(s)
    if s < 1.0 / 3.0:
        return "low"
    if s < 2.0 / 3.0:
        return "medium"
    return "high"


def _combine_confidence(*parts: float) -> float:
    arr = np.array([_clamp01(p) for p in parts if p is not None], dtype=float)
    if arr.size == 0:
        return 0.0
    geom = float(np.prod(arr) ** (1.0 / arr.size))
    mean = float(np.mean(arr))
    return _clamp01(0.5 * geom + 0.5 * mean)


def _detect_propwash(
    m: Dict[str, Any], segs: List[dict[str, Any]]
) -> Tuple[dict[str, Any] | None, List[int]]:
    pw_conf = m["propwash"]["confidence"]
    prop_idx = _indices_by_type(segs, "propwash_candidate")
    seg_presence = min(1.0, len(prop_idx) / 3.0) if prop_idx else 0.0
    metric_strength = _smooth_gate(pw_conf, 0.35, 0.75)
    if not prop_idx or pw_conf <= 0.4:
        return None, []
    noise_bad = 1.0 - m["noise"]["value"] / 100.0
    noise_bad = _clamp01(noise_bad)
    strength = _combine_confidence(metric_strength, seg_presence, 0.6 + 0.4 * noise_bad)
    if strength < 0.18:
        return None, []
    sev_score = _clamp01(0.45 * pw_conf + 0.35 * noise_bad + 0.2 * seg_presence)
    conf = _combine_confidence(pw_conf, seg_presence, metric_strength)
    desc = (
        "Propwash-like behavior appears during throttle transients in this log, "
        "consistent with torque impulses exciting the airframe. "
        "Metric propwash confidence aligns with those segments."
    )
    sug = (
        "Try a modest increase in D-term on the affected axes, soften throttle curves, "
        "and review gyro / D-term filtering so you damp oscillations without adding excess delay."
    )
    return (
        {
            "type": "propwash",
            "severity": _severity_from_score(sev_score),
            "confidence": conf,
            "segments": list(prop_idx),
            "description": desc,
            "suggestion": sug,
        },
        prop_idx,
    )


def _detect_oscillation(
    m: Dict[str, Any], segs: List[dict[str, Any]]
) -> Tuple[dict[str, Any] | None, List[int]]:
    man_idx = _indices_by_type(segs, "maneuver")
    frac = _segment_fraction(segs, "maneuver")
    hf = m["noise"]["hf_ratio"]
    tr = m["tracking"]["score"]
    maneuver_signal = _smooth_gate(frac, 0.12, 0.45) * _smooth_gate(float(len(man_idx)), 0.5, 2.5)
    hf_signal = _smooth_gate(hf, 0.22, 0.55)
    tracking_ok = _smooth_gate(tr, 45.0, 72.0)
    strength = _combine_confidence(maneuver_signal, hf_signal, tracking_ok)
    if strength < 0.22 or not man_idx:
        return None, []
    sev_score = _clamp01(0.4 * hf_signal + 0.35 * maneuver_signal + 0.25 * tracking_ok)
    conf = strength
    desc = (
        "Repeated high-activity maneuver segments coincide with elevated high-frequency "
        "noise energy while tracking remains relatively tight—this pattern often reflects "
        "oscillation or ringing rather than simple sluggish response."
    )
    sug = (
        "Consider slightly reducing P gains or notches at the dominant resonance, "
        "and verify filter stages are not fighting each other; add damping before pushing P higher."
    )
    return (
        {
            "type": "oscillation",
            "severity": _severity_from_score(sev_score),
            "confidence": conf,
            "segments": list(man_idx),
            "description": desc,
            "suggestion": sug,
        },
        man_idx,
    )


def _detect_noise_issue(
    m: Dict[str, Any], segs: List[dict[str, Any]]
) -> Tuple[dict[str, Any] | None, List[int]]:
    nv = m["noise"]["value"]
    sev = m["resonance"]["severity"]
    cleanliness = nv / 100.0
    bad_noise = 1.0 - cleanliness
    res_score = {"low": 0.0, "medium": 0.55, "high": 1.0}.get(sev, 0.0)
    strength = _combine_confidence(_smooth_gate(bad_noise, 0.25, 0.65), res_score)
    if strength < 0.28 or sev not in ("medium", "high"):
        return None, []
    if nv > 58.0:
        return None, []
    conf = strength
    desc = (
        "Overall noise cleanliness is low while resonance severity is elevated—"
        "vibration or frame resonance may be coupling into the gyro trace, or filters may be mis-tuned."
    )
    sug = (
        "Increase targeted gyro filtering (notch / LPF) at the identified peaks, "
        "check mechanical tightness and props, and validate the stack is not amplifying HF noise."
    )
    all_idx = list(range(len(segs)))
    return (
        {
            "type": "noise",
            "severity": _severity_from_score(strength),
            "confidence": conf,
            "segments": all_idx,
            "description": desc,
            "suggestion": sug,
        },
        all_idx,
    )


def _detect_low_tracking(
    m: Dict[str, Any], segs: List[dict[str, Any]]
) -> Tuple[dict[str, Any] | None, List[int]]:
    tr = m["tracking"]["score"]
    man_idx = _indices_by_type(segs, "maneuver")
    frac = _segment_fraction(segs, "maneuver")
    low_tr = 1.0 - _smooth_gate(tr, 35.0, 62.0)
    demand = _smooth_gate(frac, 0.18, 0.5) * _smooth_gate(float(len(man_idx)), 1.0, 4.0)
    strength = _combine_confidence(low_tr, demand)
    if strength < 0.3 or tr >= 52.0 or len(man_idx) < 2:
        return None, []
    sev_score = _clamp01(0.55 * low_tr + 0.45 * demand)
    conf = strength
    desc = (
        "Tracking score is depressed despite frequent aggressive maneuver segments, "
        "suggesting the craft struggles to follow commands under dynamic flight."
    )
    sug = (
        "Increase P and feedforward cautiously on the worst axis, reduce excessive filtering latency, "
        "and confirm rates / setpoint limits match pilot expectations."
    )
    return (
        {
            "type": "low_tracking",
            "severity": _severity_from_score(sev_score),
            "confidence": conf,
            "segments": list(man_idx),
            "description": desc,
            "suggestion": sug,
        },
        man_idx,
    )


def _detect_motor_issue(
    m: Dict[str, Any], segs: List[dict[str, Any]]
) -> Tuple[dict[str, Any] | None, List[int]]:
    h = m["motor"]["health"]
    imb = m["motor"]["imbalance"]
    risk = m["motor"]["has_desync_risk"]
    low_health = _smooth_gate(1.0 - h / 100.0, 0.15, 0.55)
    high_imb = _smooth_gate(imb, 8.0, 28.0)
    risk_b = 1.0 if risk else 0.35
    strength = _combine_confidence(low_health, high_imb, risk_b)
    if strength < 0.25:
        return None, []
    if h >= 72.0 and imb < 12.0 and not risk:
        return None, []
    sev_score = _clamp01(0.5 * low_health + 0.35 * high_imb + (0.15 if risk else 0.0))
    conf = strength
    desc = (
        "Motor/noise stress indicators show reduced average health, elevated imbalance, "
        "or elevated correction demand; check for bent shafts, bad bearings, "
        "mismatched props, or excess load/noise sources."
    )
    sug = (
        "Inspect motors and solder joints, verify ESC firmware and motor direction, "
        "and consider reducing aggressive D until mechanical issues are ruled out."
    )
    all_idx = list(range(len(segs)))
    return (
        {
            "type": "motor_issue",
            "severity": _severity_from_score(sev_score),
            "confidence": conf,
            "segments": all_idx,
            "description": desc,
            "suggestion": sug,
        },
        all_idx,
    )


def _sort_problems(rows: List[dict[str, Any]]) -> List[dict[str, Any]]:
    def key(r: dict[str, Any]) -> Tuple[int, int, str]:
        sev = str(r.get("severity", "low"))
        try:
            si = _SEVERITY_ORDER.index(sev)
        except ValueError:
            si = 0
        try:
            pi = _PROBLEM_ORDER.index(str(r.get("type", "")))
        except ValueError:
            pi = 99
        conf = -round(float(r.get("confidence", 0.0)), 6)
        return (-si, conf, f"{pi:02d}{r.get('type', '')}")

    return sorted(rows, key=key)


def detect_problems(
    metrics: Dict[str, Any],
    segments: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Combine normalized metrics and segment labels into ranked problem reports.

    ``segments`` is the dict returned by ``detect_segments`` (must contain ``segments`` list).
    """
    try:
        m = _norm_metrics(metrics)
        segs = _norm_segments(segments)
        problems: List[dict[str, Any]] = []

        for fn in (
            _detect_propwash,
            _detect_oscillation,
            _detect_noise_issue,
            _detect_low_tracking,
            _detect_motor_issue,
        ):
            row, _ = fn(m, segs)
            if row is not None:
                row["confidence"] = _clamp01(row["confidence"])
                row["segments"] = [int(i) for i in row.get("segments", []) if i is not None]
                problems.append(row)

        problems = _sort_problems(problems)
        high_n = sum(1 for p in problems if str(p.get("severity")) == "high")
        return {
            "problems": problems,
            "summary": {
                "total": len(problems),
                "high_severity": high_n,
            },
        }
    except Exception:
        return {
            "problems": [],
            "summary": {"total": 0, "high_severity": 0},
        }
