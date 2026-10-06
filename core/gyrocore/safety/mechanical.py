"""Mechanical/build noise safety gate for tuning output.

Donor: AeroTuner ``backend/services/mechanical_safety_gate.py`` (WU10 port).
"""

from __future__ import annotations

from gyrocore.safety.fault import (
    collect_mechanical_fault_evidence,
    noise_only_low_confidence_should_caution_not_limit,
)

import math
import re
from typing import Any, Mapping


MECHANICAL_BLOCK_EXPLANATION = (
    "Do not tune yet. Inspect props, motors, frame, stack mounting, and possible "
    "bent shaft or noise source before applying PID/filter changes."
)

MECHANICAL_LIMITED_EXPLANATION = (
    "GyroCore sees possible mechanical noise, so treat tuning guidance cautiously "
    "and re-test with a short clean hover/cruise log after inspection."
)

MOTOR_WARNING_CAUTION_EXPLANATION = (
    "Some motors showed relative warning diagnostics, but overall noise looks clean. "
    "Inspect motors before aggressive tuning; paste-ready guidance remains available."
)

MOTOR_CORRECTION_DEMAND_CAUTION_EXPLANATION = (
    "GyroCore saw motor output imbalance or elevated correction demand, but global gyro "
    "noise was low. This can be caused by aggressive flight inputs or a mechanical issue. "
    "Use a shorter controlled tuning flight to confirm before relying on paste-ready CLI."
)

_INDEPENDENT_BLOCK_REASONS = frozenset(
    {
        "motor_issue_high_severity_danger",
        "dangerous_flight_event",
        "per_motor_noise_anomaly",
        "persistent_resonance_with_motor_or_noise_risk",
    }
)

_CLEAN_WARNING_ONLY_LIMITED = frozenset({"warning_motor_diagnostic"})
_CLEAN_HF_RATIO_MAX = 0.35
_CLEAN_NOISE_CLEANLINESS_MIN = 45.0

def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out


def _append_unique(items: list[str], value: str) -> None:
    text = str(value or "").strip()
    if text and text not in items:
        items.append(text)


def _severity_score(value: Any) -> float:
    s = str(value or "").strip().lower()
    return {"high": 1.0, "medium": 0.6, "low": 0.25}.get(s, 0.0)


def _problem_rows(pipeline_problems: Mapping[str, Any] | None) -> list[Mapping[str, Any]]:
    if not isinstance(pipeline_problems, Mapping):
        return []
    rows = pipeline_problems.get("problems")
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _strip_inferred_risk_phrases(text: str) -> str:
    inferred_patterns = (
        r"\bdesync(?:-|\s+)?like\s+(?:risk\s+)?(?:indicator|indicators|symptom|symptoms)\b",
        r"\bdesync\s+risk(?:\s+(?:indicator|indicators|symptom|symptoms))?\b",
        r"\bsync(?:-|\s+)?like\s+(?:correction\s+demand|risk\s+indicators?)\b",
        r"\bsaturation\s+risk\b",
    )
    out = text
    for pattern in inferred_patterns:
        out = re.sub(pattern, " ", out)
    return out


def _has_danger_text(text: str) -> bool:
    text = _strip_inferred_risk_phrases(text)
    danger_patterns = (
        r"\bdesync(?:ed|s)?\b",
        r"\bsaturat(?:e|ed|es|ing|ion)?\b",
        r"\bfailsafe\b",
        r"\bcrash(?:ed|es)?\b",
        r"\barming(?:\s+(?:danger|issue|failure|fault))?\b",
        r"\bflyaway\b",
        r"\bmotor\s+stop(?:ped)?\b",
        r"\bmotor\s+stall(?:ed)?\b",
        r"\bloss\s+of\s+control\b",
    )
    negated_prefix = re.compile(r"(?:^|\b)(?:no|not|without|never|none|free of)\s+(?:\w+\s+){0,3}$")
    for pattern in danger_patterns:
        for match in re.finditer(pattern, text):
            prefix = text[max(0, match.start() - 40):match.start()]
            suffix = text[match.end():match.end() + 8]
            if negated_prefix.search(prefix) or suffix.startswith("-free"):
                continue
            return True
    return False


_CONFIRMED_SPECTRAL_ISSUES = {"broadband_noise", "abnormal_harmonics", "motor_gyro_mismatch"}
_RELATIVE_ONLY_MOTOR_ISSUES = {"noise", "imbalance"}


def _is_confirmed_bad_motor_row(
    row: Mapping[str, Any],
    *,
    status: str,
    issues: list[str],
) -> bool:
    if row.get("confirmed_bad_motor") is True and status == "bad":
        return True
    if row.get("confirmed") is True and status == "bad":
        return True
    evidence_class = str(row.get("evidence_class") or "").strip().lower()
    if evidence_class in {"confirmed", "measured"} and status == "bad":
        return True
    return status == "bad" and any(issue in _CONFIRMED_SPECTRAL_ISSUES for issue in issues)


def _has_absolute_health_basis(row: Mapping[str, Any]) -> bool:
    basis = str(
        row.get("health_basis")
        or row.get("health_source")
        or row.get("health_evidence")
        or ""
    ).strip().lower()
    if basis in {"absolute", "measured", "confirmed"}:
        return True
    return row.get("absolute_health") is True


def _motor_counts(
    motor_diagnostics: Mapping[str, Any] | None,
) -> tuple[int, int, int, list[str]]:
    if not isinstance(motor_diagnostics, Mapping):
        return 0, 0, 0, []
    motors = motor_diagnostics.get("motors")
    if not isinstance(motors, list):
        return 0, 0, 0, []
    hard_bad = 0
    relative_bad = 0
    warnings = 0
    issues: list[str] = []
    for row in motors:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "").strip().lower()
        conf = _coerce_float(row.get("confidence"), 0.5)
        health = _coerce_float(row.get("health"), 100.0)
        row_issues: list[str] = []
        raw_issues = row.get("issues")
        if isinstance(raw_issues, list):
            for issue in raw_issues:
                issue_text = str(issue)
                _append_unique(row_issues, issue_text)
                _append_unique(issues, issue_text)
        has_confident_signal = conf >= 0.35
        is_relative_only_health_row = bool(row_issues) and all(
            issue in _RELATIVE_ONLY_MOTOR_ISSUES for issue in row_issues
        )
        is_low_health = (
            health < 52.0
            and has_confident_signal
            and (
                _has_absolute_health_basis(row)
                or not is_relative_only_health_row
            )
        )
        is_confirmed_bad = has_confident_signal and _is_confirmed_bad_motor_row(
            row,
            status=status,
            issues=row_issues,
        )
        if is_low_health or is_confirmed_bad:
            hard_bad += 1
        elif status == "bad" and has_confident_signal:
            relative_bad += 1
        elif status == "warning" and conf >= 0.35:
            warnings += 1
    return hard_bad, relative_bad, warnings, issues


def _resonance_context(
    engine_metrics: Mapping[str, Any] | None,
    resonance_module: Mapping[str, Any] | None,
) -> tuple[str, bool, bool]:
    metrics = engine_metrics if isinstance(engine_metrics, Mapping) else {}
    resonance = metrics.get("resonance") if isinstance(metrics.get("resonance"), Mapping) else {}
    severity = str(resonance.get("severity") or "").strip().lower()
    if severity not in {"low", "medium", "high"}:
        severity = "low"
    rm = resonance_module if isinstance(resonance_module, Mapping) else {}
    primary = rm.get("primary") if isinstance(rm.get("primary"), Mapping) else {}
    primary_type = str(primary.get("type") or "").strip().lower()
    bandwidth = _coerce_float(primary.get("bandwidth"), 0.0)
    spread = _coerce_float(rm.get("spread"), 0.0)
    broad = bool(primary_type == "noise" or bandwidth >= 60.0 or spread >= 75.0)
    persistent = bool(severity == "high" or spread >= 90.0)
    return severity, broad, persistent


def _any_confirmed_bad_motor(motor_diagnostics: Mapping[str, Any] | None) -> bool:
    if not isinstance(motor_diagnostics, Mapping):
        return False
    motors = motor_diagnostics.get("motors")
    if not isinstance(motors, list):
        return False
    for row in motors:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "").strip().lower()
        issues_raw = row.get("issues")
        row_issues: list[str] = []
        if isinstance(issues_raw, list):
            row_issues = [str(x).strip() for x in issues_raw if str(x).strip()]
        if _is_confirmed_bad_motor_row(row, status=status, issues=row_issues):
            return True
    return False


def _has_confirmed_danger_in_problems(pipeline_problems: Mapping[str, Any] | None) -> bool:
    for row in _problem_rows(pipeline_problems):
        text = " ".join(
            str(row.get(k, "")) for k in ("type", "description", "suggestion", "message")
        ).lower()
        sev = _severity_score(row.get("severity"))
        conf = _coerce_float(row.get("confidence"), 0.5)
        if _has_danger_text(text) and sev >= 0.6 and conf >= 0.55:
            return True
    return False


def _is_clean_global_noise_context(
    *,
    high_noise: bool,
    noise_cleanliness: float,
    noise_level: str | None,
    broad_resonance: bool,
    persistent_resonance: bool,
    resonance_severity: str,
) -> bool:
    if high_noise:
        return False
    if noise_cleanliness <= _CLEAN_NOISE_CLEANLINESS_MIN:
        return False
    if str(noise_level or "").strip().upper() == "HIGH":
        return False
    if broad_resonance or persistent_resonance:
        return False
    if resonance_severity in {"medium", "high"}:
        return False
    return True


def _is_aggressive_flight_context(flight_context: Mapping[str, Any] | None) -> bool:
    if not isinstance(flight_context, Mapping):
        return False
    style = str(flight_context.get("requested_style") or flight_context.get("style") or "").strip().lower()
    goal = str(
        flight_context.get("requested_goal_profile")
        or flight_context.get("goal_profile")
        or ""
    ).strip().lower()
    goals = flight_context.get("goals")
    goal_tokens: set[str] = set()
    if goal:
        goal_tokens.add(goal)
    if isinstance(goals, list):
        goal_tokens.update(str(g).strip().lower() for g in goals if str(g).strip())
    aggressive_styles = {"racing", "freestyle", "aggressive"}
    aggressive_goals = {"racing_locked", "aggressive", "locked-in race", "racing", "racing_aggressive"}
    return style in aggressive_styles or bool(goal_tokens & aggressive_goals)


def _has_independent_low_health_motor_basis(
    motor_diagnostics: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(motor_diagnostics, Mapping):
        return False
    motors = motor_diagnostics.get("motors")
    if not isinstance(motors, list):
        return False
    for row in motors:
        if not isinstance(row, Mapping):
            continue
        status = str(row.get("status") or "").strip().lower()
        health = _coerce_float(row.get("health"), 100.0)
        conf = _coerce_float(row.get("confidence"), 0.5)
        row_issues: list[str] = []
        raw_issues = row.get("issues")
        if isinstance(raw_issues, list):
            row_issues = [str(x).strip() for x in raw_issues if str(x).strip()]
        if conf < 0.35 or status != "bad" or health >= 52.0:
            continue
        if _has_absolute_health_basis(row):
            return True
        if _is_confirmed_bad_motor_row(row, status=status, issues=row_issues):
            return True
    return False


def _is_correction_demand_only_block(
    *,
    blocking: list[str],
    bad_motors: int,
    relative_bad_motors: int,
    motor_issues: list[str],
    motor_diagnostics: Mapping[str, Any] | None,
    high_noise: bool,
    noise_cleanliness: float,
    noise_level: str | None,
    broad_resonance: bool,
    persistent_resonance: bool,
    resonance_severity: str,
    pipeline_problems: Mapping[str, Any] | None,
) -> bool:
    """True when bad_motor_diagnostic is the only block and evidence looks correction-demand-only."""
    if not blocking:
        return False
    if any(reason in _INDEPENDENT_BLOCK_REASONS for reason in blocking):
        return False
    if blocking != ["bad_motor_diagnostic"]:
        return False
    if bad_motors <= 0 and relative_bad_motors <= 0:
        return False
    if not _is_clean_global_noise_context(
        high_noise=high_noise,
        noise_cleanliness=noise_cleanliness,
        noise_level=noise_level,
        broad_resonance=broad_resonance,
        persistent_resonance=persistent_resonance,
        resonance_severity=resonance_severity,
    ):
        return False
    if any(issue in _CONFIRMED_SPECTRAL_ISSUES for issue in motor_issues):
        return False
    if _any_confirmed_bad_motor(motor_diagnostics):
        return False
    if _has_independent_low_health_motor_basis(motor_diagnostics):
        return False
    if _has_confirmed_danger_in_problems(pipeline_problems):
        return False
    return True


def _is_clean_warning_only_motor_case(
    *,
    limited: list[str],
    blocking: list[str],
    bad_motors: int,
    relative_bad_motors: int,
    warning_motors: int,
    motor_issues: list[str],
    high_noise: bool,
    hf_ratio: float,
    noise_cleanliness: float,
    noise_level: str | None,
    resonance_severity: str,
) -> bool:
    """True when warning-only motor diagnostics should not force mechanical_limited."""
    if blocking:
        return False
    if bad_motors > 0 or relative_bad_motors > 0:
        return False
    if warning_motors <= 0:
        return False
    if set(limited) != _CLEAN_WARNING_ONLY_LIMITED:
        return False
    if high_noise:
        return False
    if hf_ratio >= _CLEAN_HF_RATIO_MAX:
        return False
    if noise_cleanliness <= _CLEAN_NOISE_CLEANLINESS_MIN:
        return False
    if str(noise_level or "").strip().upper() == "HIGH":
        return False
    if resonance_severity in {"medium", "high"}:
        return False
    if any(issue in _CONFIRMED_SPECTRAL_ISSUES for issue in motor_issues):
        return False
    return True


def build_mechanical_safety_gate(
    *,
    pipeline_problems: Mapping[str, Any] | None = None,
    motor_diagnostics: Mapping[str, Any] | None = None,
    engine_metrics: Mapping[str, Any] | None = None,
    resonance_module: Mapping[str, Any] | None = None,
    confidence_eval: Mapping[str, Any] | None = None,
    quality_status: str | None = None,
    noise_level: str | None = None,
    flight_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify existing mechanical/noise evidence into output safety guidance."""
    reasons: list[str] = []
    limited: list[str] = []
    messages: list[str] = []

    metrics = engine_metrics if isinstance(engine_metrics, Mapping) else {}
    noise = metrics.get("noise") if isinstance(metrics.get("noise"), Mapping) else {}
    noise_cleanliness = _coerce_float(noise.get("value"), 100.0)
    hf_ratio = _coerce_float(noise.get("hf_ratio"), 0.0)
    high_noise = bool(
        str(noise_level or "").strip().upper() == "HIGH"
        or noise_cleanliness <= 45.0
        or hf_ratio >= 0.35
    )
    low_conf = bool(
        str(quality_status or "").strip().lower() == "low_quality"
        or _coerce_float((confidence_eval or {}).get("score"), 1.0) < 0.45
    )

    for row in _problem_rows(pipeline_problems):
        ptype = str(row.get("type") or "").strip().lower()
        text = " ".join(
            str(row.get(k, "")) for k in ("type", "description", "suggestion", "message")
        ).lower()
        sev = _severity_score(row.get("severity"))
        conf = _coerce_float(row.get("confidence"), 0.5)
        danger_text = _has_danger_text(text)
        if ptype == "motor_issue" and sev >= 1.0 and conf >= 0.55 and danger_text:
            _append_unique(reasons, "motor_issue_high_severity_danger")
        elif ptype == "motor_issue" and sev >= 1.0:
            _append_unique(limited, "motor_issue_high_severity")
        elif ptype == "motor_issue" and sev >= 0.6:
            _append_unique(limited, "motor_issue_medium_severity")
        if danger_text and sev >= 0.6 and conf >= 0.55:
            _append_unique(reasons, "dangerous_flight_event")
        if any(token in text for token in ("bent shaft", "bad bearings", "frame resonance", "mechanical")):
            if sev >= 0.6 and conf >= 0.25:
                _append_unique(limited, "mechanical_problem_indicator")

    bad_motors, relative_bad_motors, warning_motors, motor_issues = _motor_counts(
        motor_diagnostics
    )
    if bad_motors > 0:
        _append_unique(reasons, "bad_motor_diagnostic")
    elif relative_bad_motors > 0 or warning_motors > 0:
        _append_unique(limited, "warning_motor_diagnostic")
    if any(issue in motor_issues for issue in ("broadband_noise", "abnormal_harmonics", "motor_gyro_mismatch")):
        if bad_motors > 0:
            _append_unique(reasons, "per_motor_noise_anomaly")
        else:
            _append_unique(limited, "per_motor_noise_anomaly")

    resonance_severity, broad_resonance, persistent_resonance = _resonance_context(
        engine_metrics,
        resonance_module,
    )
    if high_noise and broad_resonance:
        _append_unique(limited, "broad_frame_resonance_noise")
    if persistent_resonance and (bad_motors > 0 or high_noise):
        if bad_motors > 0:
            _append_unique(reasons, "persistent_resonance_with_motor_or_noise_risk")
        else:
            _append_unique(limited, "persistent_resonance_with_noise_risk")
    elif resonance_severity == "medium" and broad_resonance:
        _append_unique(limited, "medium_broad_resonance")

    if low_conf and (high_noise or warning_motors > 0 or resonance_severity in {"medium", "high"}):
        _append_unique(limited, "mechanical_noise_low_confidence")

    aggressive_flight = _is_aggressive_flight_context(flight_context)
    correction_demand_only = _is_correction_demand_only_block(
        blocking=reasons,
        bad_motors=bad_motors,
        relative_bad_motors=relative_bad_motors,
        motor_issues=motor_issues,
        motor_diagnostics=motor_diagnostics,
        high_noise=high_noise,
        noise_cleanliness=noise_cleanliness,
        noise_level=noise_level,
        broad_resonance=broad_resonance,
        persistent_resonance=persistent_resonance,
        resonance_severity=resonance_severity,
        pipeline_problems=pipeline_problems,
    )
    independent_mechanical_evidence = not correction_demand_only and bool(reasons)
    if correction_demand_only:
        reasons.clear()
        _append_unique(limited, "motor_correction_demand_uncertain")
        if bad_motors > 0 or relative_bad_motors > 0:
            _append_unique(limited, "warning_motor_diagnostic")

    mechanical_block = bool(reasons)
    mechanical_caution = False
    caution_reasons: list[str] = []
    downgrade_reason: str | None = None
    mechanical_outcome = "mechanical_clear"
    mechanical_evidence_strength = (
        "independent"
        if independent_mechanical_evidence
        else ("correction_demand" if correction_demand_only else "none")
    )

    mechanical_fault_preview = collect_mechanical_fault_evidence(
        mechanical_gate={
            "evidence": {
                "bad_motor_count": bad_motors,
                "relative_bad_motor_count": relative_bad_motors,
                "resonance_severity": resonance_severity,
                "broad_resonance": broad_resonance,
                "persistent_resonance": persistent_resonance,
                "independent_mechanical_evidence": independent_mechanical_evidence,
            },
            "blocking_reasons": reasons,
            "limited_reasons": limited,
        },
        motor_diagnostics=motor_diagnostics,
        analysis={"motor_diagnostics": motor_diagnostics} if motor_diagnostics else None,
    )
    if noise_only_low_confidence_should_caution_not_limit(
        limited_reasons=limited,
        mechanical_fault=mechanical_fault_preview,
        high_noise=high_noise,
        low_confidence=low_conf,
    ):
        if "mechanical_noise_low_confidence" in limited:
            limited.remove("mechanical_noise_low_confidence")
        _append_unique(caution_reasons, "noise_low_confidence_capped")
        mechanical_caution = True

    if mechanical_block:
        mechanical_outcome = "mechanical_block"
        mechanical_limited = False
        limited_tier = "blocked"
        max_delta_scale = 0.0
    elif correction_demand_only:
        mechanical_limited = False
        mechanical_caution = True
        mechanical_outcome = "motor_correction_demand_caution"
        downgrade_reason = "clean_noise_correction_demand"
        caution_reasons = ["motor_correction_demand_caution"]
        limited_tier = "caution"
        max_delta_scale = 1.0
        _append_unique(messages, MOTOR_CORRECTION_DEMAND_CAUTION_EXPLANATION)
    elif _is_clean_warning_only_motor_case(
        limited=limited,
        blocking=reasons,
        bad_motors=bad_motors,
        relative_bad_motors=relative_bad_motors,
        warning_motors=warning_motors,
        motor_issues=motor_issues,
        high_noise=high_noise,
        hf_ratio=hf_ratio,
        noise_cleanliness=noise_cleanliness,
        noise_level=noise_level,
        resonance_severity=resonance_severity,
    ):
        mechanical_limited = False
        mechanical_caution = True
        mechanical_outcome = "motor_warning_caution"
        downgrade_reason = "clean_warning_only"
        caution_reasons = ["motor_warning_caution"]
        limited = []
        limited_tier = "caution"
        max_delta_scale = 1.0
        _append_unique(messages, MOTOR_WARNING_CAUTION_EXPLANATION)
    else:
        mechanical_limited = bool(limited)
        if mechanical_limited:
            mechanical_outcome = "mechanical_limited"
        if relative_bad_motors > 0 or warning_motors > 1:
            limited_tier = "strong"
            max_delta_scale = 0.5
        elif any(
            reason
            in {
                "motor_issue_high_severity",
                "motor_issue_medium_severity",
                "per_motor_noise_anomaly",
                "broad_frame_resonance_noise",
                "persistent_resonance_with_noise_risk",
            }
            for reason in limited
        ):
            limited_tier = "strong"
            max_delta_scale = 0.5
        elif warning_motors == 1:
            limited_tier = "mild"
            max_delta_scale = 0.75
        elif mechanical_limited:
            limited_tier = "moderate"
            max_delta_scale = 0.65
        else:
            limited_tier = "none"
            max_delta_scale = 1.0
        if mechanical_limited:
            _append_unique(messages, MECHANICAL_LIMITED_EXPLANATION)

    if mechanical_block:
        _append_unique(messages, "GyroCore is holding tuning changes because the log looks mechanically noisy.")
        _append_unique(messages, MECHANICAL_BLOCK_EXPLANATION)
        _append_unique(messages, "Re-test with a short clean hover/cruise log after fixing the build issue.")

    return {
        "mechanical_block": mechanical_block,
        "mechanical_limited": mechanical_limited,
        "mechanical_caution": mechanical_caution,
        "mechanical_outcome": mechanical_outcome,
        "severity": "blocked"
        if mechanical_block
        else ("caution" if mechanical_caution or mechanical_limited else "info"),
        "reasons": reasons + limited + caution_reasons,
        "blocking_reasons": reasons,
        "limited_reasons": limited,
        "caution_reasons": caution_reasons,
        "downgrade_reason": downgrade_reason,
        "recommended_action": "guidance_only"
        if mechanical_block
        else ("limited_tune" if mechanical_limited else ("caution" if mechanical_caution else "none")),
        "user_message": messages,
        "evidence": {
            "high_noise": high_noise,
            "low_confidence": low_conf,
            "resonance_severity": resonance_severity,
            "broad_resonance": broad_resonance,
            "persistent_resonance": persistent_resonance,
            "bad_motor_count": bad_motors,
            "relative_bad_motor_count": relative_bad_motors,
            "warning_motor_count": warning_motors,
            "limited_tier": limited_tier,
            "max_delta_scale": max_delta_scale,
            "mechanical_outcome": mechanical_outcome,
            "downgrade_reason": downgrade_reason,
            "motor_correction_demand_uncertain": correction_demand_only,
            "mechanical_evidence_strength": mechanical_evidence_strength,
            "independent_mechanical_evidence": independent_mechanical_evidence,
            "aggressive_flight_context": aggressive_flight,
            "measured_temperature_available": False,
        },
        "limited_tier": limited_tier,
        "max_delta_scale": max_delta_scale,
    }
