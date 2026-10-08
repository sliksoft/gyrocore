"""Thermal / motor envelope (WU10).

Donor: AeroTuner ``backend/services/tuning_safety_policy.py``
(``classify_thermal_motor_risk``, ``desync_risk_active``,
``should_enforce_baseline_envelope``, ``clamp_targets_to_baseline_thermal``,
``rpm_dshot_health_gate`` with ``unknown_is_unsafe=False``).

SaaS/hardware-inference weighting is not migrated.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

RPM_DSHOT_SAFETY_EXPLANATION = (
    "RPM filter or bidirectional DShot health is uncertain, so GyroCore is not "
    "increasing D-term or reducing filtering. Fix RPM telemetry / bidirectional DShot first."
)

_SEVERITY_LABEL_FLOAT: dict[str, float] = {
    "critical": 1.0,
    "high": 1.0,
    "medium": 0.5,
    "low": 0.0,
}


def _coerce_float(val: Any, default: float = 0.0) -> float:
    if val is None or isinstance(val, bool):
        return default
    try:
        v = float(val)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


def coerce_problem_severity(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, str):
        label = value.strip().lower()
        if label in _SEVERITY_LABEL_FLOAT:
            return _SEVERITY_LABEL_FLOAT[label]
        value = label
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _problems_rows(analysis: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(analysis, Mapping):
        return []
    probs = analysis.get("problems")
    if isinstance(probs, list):
        return [p for p in probs if isinstance(p, Mapping)]
    if isinstance(probs, Mapping):
        inner = probs.get("problems")
        if isinstance(inner, list):
            return [p for p in inner if isinstance(p, Mapping)]
    return []


def _motor_issue_max_severity(analysis: Mapping[str, Any] | None) -> float:
    best = 0.0
    for row in _problems_rows(analysis):
        typ = str(row.get("type", "")).strip().lower()
        if typ != "motor_issue":
            continue
        best = max(best, coerce_problem_severity(row.get("severity"), 0.0))
    return best


def _motor_health(analysis: Mapping[str, Any] | None) -> float:
    if not isinstance(analysis, Mapping):
        return 1.0
    md = analysis.get("motor_diagnostics")
    if isinstance(md, Mapping):
        raw = _coerce_float(md.get("health"), 1.0)
        if raw > 1.0:
            return max(0.0, min(1.0, raw / 100.0))
        return max(0.0, min(1.0, raw))
    motors = analysis.get("motors")
    if isinstance(motors, Mapping):
        diag = motors.get("diagnostics")
        if isinstance(diag, Mapping):
            raw = _coerce_float(diag.get("health"), 1.0)
            if raw > 1.0:
                return max(0.0, min(1.0, raw / 100.0))
            return max(0.0, min(1.0, raw))
    return 1.0


def _motor_stress_level(analysis: Mapping[str, Any] | None) -> float:
    sev = _motor_issue_max_severity(analysis)
    health = _motor_health(analysis)
    return max(sev, 1.0 - health)


def _motor_stress_tier(analysis: Mapping[str, Any] | None) -> str:
    s = _motor_stress_level(analysis)
    if s >= 0.82:
        return "critical"
    if s >= 0.65:
        return "high"
    if s >= 0.42:
        return "medium"
    return "low"


def classify_thermal_motor_risk(analysis: Mapping[str, Any] | None) -> dict[str, Any]:
    ana = analysis if isinstance(analysis, Mapping) else None
    sev = _motor_issue_max_severity(ana)
    tier = _motor_stress_tier(ana)
    health = _motor_health(ana)
    motor_issue_active = sev > 0.05
    hot_motors = (
        tier in ("high", "critical")
        or health < 0.52
        or sev > 0.38
        or (motor_issue_active and health < 0.62)
    )
    thermal_risk = bool(hot_motors or (motor_issue_active and sev > 0.22))
    return {
        "motor_issue_severity": float(sev),
        "motor_issue_active": motor_issue_active,
        "motor_stress_tier": tier,
        "motor_health": float(health),
        "hot_motors": bool(hot_motors),
        "thermal_risk": bool(thermal_risk),
    }


def desync_risk_active(analysis: Mapping[str, Any] | None) -> bool:
    if not isinstance(analysis, Mapping):
        return False
    if analysis.get("has_desync_risk") is True:
        return True
    md = analysis.get("motor_diagnostics")
    if isinstance(md, Mapping) and md.get("has_desync_risk") is True:
        return True
    motors = analysis.get("motors")
    if isinstance(motors, Mapping):
        diag = motors.get("diagnostics")
        if isinstance(diag, Mapping) and diag.get("has_desync_risk") is True:
            return True
    for row in _problems_rows(analysis):
        t = str(row.get("type", "")).strip().lower()
        if "desync" in t:
            return True
    return False


def gyro_lpf1_baseline_hz_non_binding(baseline_hz: Any) -> bool:
    try:
        v = float(baseline_hz)
    except (TypeError, ValueError):
        return True
    if not math.isfinite(v):
        return True
    return v <= 1e-6


def _gyro_filter_baseline_hz_non_binding(key: str, baseline_hz: Any) -> bool:
    if not str(key or "").startswith("gyro_"):
        return False
    return gyro_lpf1_baseline_hz_non_binding(baseline_hz)


def _label(value: Any) -> str:
    return str(value or "").strip().lower()


def _nested_mapping(root: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    cur: Any = root
    for key in path:
        if not isinstance(cur, Mapping):
            return {}
        cur = cur.get(key)
    return cur if isinstance(cur, Mapping) else {}


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    return None


def _rpm_gate_context(analysis: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    explicit = False
    ctx: dict[str, Any] = {}
    health = analysis.get("rpm_dshot_health")
    if isinstance(health, Mapping):
        explicit = True
        ctx.update(dict(health))
    fi = analysis.get("filter_intelligence")
    if isinstance(fi, Mapping):
        explicit = True
        confidence = _nested_mapping(fi, "confidence")
        if "rpm_filter" in confidence:
            ctx.setdefault("confidence", confidence.get("rpm_filter"))
        state = _nested_mapping(fi, "filter_state")
        if state:
            ctx.setdefault("rpm_filter_enabled", state.get("rpm_filter"))
            ctx.setdefault("dshot_bidir", state.get("dshot_bidir"))
            ctx.setdefault("motor_poles", state.get("motor_poles"))
            ctx.setdefault("rpm_telemetry_present", state.get("rpm_telemetry_present"))
        harmonic = _nested_mapping(fi, "harmonic_evidence")
        if harmonic:
            ctx.setdefault("harmonic_confidence", harmonic.get("confidence"))
            ctx.setdefault("rpm_telemetry_present", harmonic.get("rpm_telemetry_present"))
            ctx.setdefault("dshot_bidir", harmonic.get("dshot_bidir_confirmed"))
            if harmonic.get("motor_poles_known") is not None:
                ctx.setdefault("motor_poles_known", harmonic.get("motor_poles_known"))
        spectral = _nested_mapping(fi, "spectral_evidence")
        if spectral.get("quality") == "low":
            ctx.setdefault("spectral_quality_low", True)
    for key in (
        "rpm_filter_confidence",
        "rpm_harmonic_confidence",
        "rpm_frequency_alignment_uncertain",
    ):
        if key in analysis:
            explicit = True
            ctx.setdefault(key, analysis.get(key))
    return ctx, explicit


def rpm_dshot_health_gate(
    analysis: Mapping[str, Any] | None,
    *,
    unknown_is_unsafe: bool = False,
) -> dict[str, Any]:
    ana = analysis if isinstance(analysis, Mapping) else {}
    ctx, explicit = _rpm_gate_context(ana)
    reasons: list[str] = []
    if not explicit:
        if not unknown_is_unsafe:
            return {
                "status": "unknown",
                "enforce_safety": False,
                "reasons": [],
                "explanation": RPM_DSHOT_SAFETY_EXPLANATION,
            }
        reasons.append("rpm_dshot_health_unknown")
        return {
            "status": "unknown",
            "enforce_safety": True,
            "reasons": reasons,
            "explanation": RPM_DSHOT_SAFETY_EXPLANATION,
        }
    status = _label(ctx.get("status"))
    rpm_enabled = _bool_or_none(ctx.get("rpm_filter_enabled"))
    dshot = _bool_or_none(ctx.get("dshot_bidir"))
    telemetry = _bool_or_none(ctx.get("rpm_telemetry_present"))
    motor_poles_known = _bool_or_none(ctx.get("motor_poles_known"))
    if motor_poles_known is None:
        motor_poles_known = ctx.get("motor_poles") is not None
    confidence = _label(
        ctx.get("confidence")
        or ctx.get("rpm_filter_confidence")
        or ctx.get("harmonic_confidence")
        or ctx.get("rpm_harmonic_confidence")
    )
    harmonic_confidence = _label(ctx.get("harmonic_confidence") or ctx.get("rpm_harmonic_confidence"))
    if status in {"unhealthy", "unsafe", "blocked", "low", "disabled"}:
        reasons.append(f"rpm_dshot_status_{status}")
    if status in {"healthy", "ok"} and confidence in {"", "high"}:
        confidence = "high"
    if rpm_enabled is not True:
        reasons.append("rpm_filter_missing_or_disabled")
    if dshot is not True:
        reasons.append("bidirectional_dshot_missing_or_disabled")
    if telemetry is not True:
        reasons.append("rpm_telemetry_missing_or_weak")
    if motor_poles_known is not True:
        reasons.append("motor_poles_unknown")
    if confidence != "high":
        reasons.append("rpm_filter_confidence_not_high")
    if harmonic_confidence and harmonic_confidence != "high":
        reasons.append("rpm_harmonic_confidence_not_high")
    if ctx.get("rpm_frequency_alignment_uncertain") is True:
        reasons.append("rpm_frequency_alignment_uncertain")
    if ctx.get("spectral_quality_low") is True:
        reasons.append("rpm_spectral_quality_low")
    reasons = list(dict.fromkeys(reasons))
    enforce = bool(reasons)
    return {
        "status": "healthy" if not enforce else "uncertain",
        "enforce_safety": enforce,
        "reasons": reasons,
        "confidence": confidence or None,
        "rpm_filter_enabled": rpm_enabled,
        "dshot_bidir": dshot,
        "rpm_telemetry_present": telemetry,
        "motor_poles_known": motor_poles_known,
        "explanation": RPM_DSHOT_SAFETY_EXPLANATION,
    }


def should_enforce_baseline_envelope(analysis: Mapping[str, Any] | None) -> bool:
    r = classify_thermal_motor_risk(analysis)
    if r["thermal_risk"]:
        return True
    if r["motor_issue_active"]:
        return True
    if desync_risk_active(analysis):
        return True
    if rpm_dshot_health_gate(analysis)["enforce_safety"]:
        return True
    return False


def clamp_targets_to_baseline_thermal(
    targets: Mapping[str, Any] | None,
    baseline_config: Mapping[str, Any] | None,
    *,
    thermal_risk: bool,
    locks: list[str] | None = None,
) -> dict[str, Any]:
    lk = locks if locks is not None else []
    if not thermal_risk:
        return copy.deepcopy(dict(targets)) if isinstance(targets, Mapping) else {"filters": {}, "pid": {}}
    if not isinstance(targets, Mapping):
        return {"filters": {}, "pid": {}}
    out: dict[str, Any] = copy.deepcopy(dict(targets))
    bp = baseline_config.get("pid") if isinstance(baseline_config, Mapping) else None
    bf = baseline_config.get("filters") if isinstance(baseline_config, Mapping) else None
    tp = out.get("pid") if isinstance(out.get("pid"), Mapping) else {}
    for ax in ("roll", "pitch", "yaw"):
        ob = tp.get(ax) if isinstance(tp.get(ax), Mapping) else {}
        if not isinstance(ob, Mapping):
            continue
        bblk = bp.get(ax) if isinstance(bp, Mapping) and isinstance(bp.get(ax), Mapping) else {}
        base_d = _coerce_float(bblk.get("d"), None) if isinstance(bblk, Mapping) else None
        if base_d is not None and "d" in ob:
            tv = _coerce_float(ob.get("d"), base_d)
            if tv > base_d + 1e-6:
                out["pid"][ax]["d"] = float(base_d)
                lk.append(f"safety_cap:{ax}_d_to_baseline")
        base_dmax = _coerce_float(bblk.get("d_max"), None) if isinstance(bblk, Mapping) else None
        if base_dmax is not None and "d_max" in ob:
            tv = _coerce_float(ob.get("d_max"), base_dmax)
            if tv > base_dmax + 1e-6:
                out["pid"][ax]["d_max"] = float(base_dmax)
                lk.append(f"safety_cap:{ax}_d_max_to_baseline")

    if isinstance(bf, Mapping):
        tf = out.get("filters")
        if isinstance(tf, Mapping):
            for key in (
                "gyro_lpf1_static_hz",
                "gyro_lpf1_dyn_min_hz",
                "gyro_lpf1_dyn_max_hz",
                "gyro_lpf2_static_hz",
                "dterm_lpf1_dyn_max_hz",
                "dterm_lpf1_dyn_min_hz",
                "dterm_lpf2_static_hz",
            ):
                if key not in tf or key not in bf:
                    continue
                bv_raw = bf.get(key)
                tv = _coerce_float(tf.get(key), None)
                if tv is None:
                    continue
                if _gyro_filter_baseline_hz_non_binding(key, bv_raw):
                    continue
                bv = _coerce_float(bv_raw, None)
                if bv is None:
                    continue
                if tv > bv + 1e-6:
                    tf[key] = float(bv)
                    lk.append(f"safety_cap:filter_{key}_to_baseline")
    return out


__all__ = [
    "RPM_DSHOT_SAFETY_EXPLANATION",
    "clamp_targets_to_baseline_thermal",
    "classify_thermal_motor_risk",
    "coerce_problem_severity",
    "desync_risk_active",
    "gyro_lpf1_baseline_hz_non_binding",
    "rpm_dshot_health_gate",
    "should_enforce_baseline_envelope",
]
