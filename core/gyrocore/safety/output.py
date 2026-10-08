"""Final tuning_output_safety gate (WU10). Never sets cli_actionable True."""

from __future__ import annotations

from typing import Any, Mapping

from gyrocore.autotune.merge import MERGE_REQUIRES_REVIEW
from gyrocore.betaflight.simplified_tuning import (
    DYN_LPF_MAX_HZ,
    F_GAIN_MAX,
    LPF_MAX_HZ,
    PID_GAIN_MAX,
)
from gyrocore.safety.results import (
    SafeTuneCandidate,
    TuningOutputSafetyResult,
    make_tuning_output_safety,
)
from gyrocore.safety.types import SafetyCheck, SafetyVerdict, StageBypassError

CONFIDENCE_PID_THRESHOLD = 0.4

# Domain block codes (machine-readable).
BLOCK_MECHANICAL = "mechanical_hard_block"
BLOCK_MISSING_MECHANICAL = "missing_mechanical_safety_stage"
BLOCK_MISSING_SAFE_TUNE = "missing_safe_tune_stage"
BLOCK_MISSING_ANALYSIS = "missing_required_analysis"
BLOCK_MISSING_BASELINE = "missing_required_pid_or_filter_baseline"
BLOCK_MISSING_CURRENT = "missing_current_tune"
BLOCK_MERGE_REVIEW = "unresolved_merge_requires_review"
BLOCK_SYSID = "system_id_unusable"
BLOCK_INVALID_SIMPLIFIED = "invalid_simplified_tuning_state"
BLOCK_SLIDER_INCONSISTENT = "slider_inconsistency"
BLOCK_MALFORMED = "malformed_proposal"
BLOCK_UNSUPPORTED = "unsupported_betaflight_state"
BLOCK_VALUES = "resulting_values_invalid"
BLOCK_CANDIDATE = "safe_tune_candidate_blocked"


def _confidence_score(analysis: Mapping[str, Any] | None) -> float:
    if not isinstance(analysis, Mapping):
        return 1.0
    conf = analysis.get("confidence")
    if isinstance(conf, Mapping):
        try:
            return float(conf.get("score", 1.0) or 1.0)
        except (TypeError, ValueError):
            return 0.0
    if isinstance(conf, (int, float)) and not isinstance(conf, bool):
        return float(conf)
    return 1.0


def _quality_status(analysis: Mapping[str, Any] | None) -> str:
    if not isinstance(analysis, Mapping):
        return ""
    quality = analysis.get("quality")
    if isinstance(quality, Mapping):
        return str(quality.get("status") or "").strip().lower()
    return str(analysis.get("quality_status") or "").strip().lower()


def _noise_high(analysis: Mapping[str, Any] | None) -> bool:
    if not isinstance(analysis, Mapping):
        return False
    metrics = analysis.get("metrics")
    if isinstance(metrics, Mapping):
        noise = metrics.get("noise")
        if isinstance(noise, Mapping):
            level = str(noise.get("level") or "").strip().upper()
            if level == "HIGH":
                return True
    return str(analysis.get("noise_level") or "").strip().upper() == "HIGH"


def _values_within_firmware(config: Mapping[str, Any] | None) -> tuple[bool, tuple[str, ...]]:
    if not isinstance(config, Mapping):
        return False, ("clamped_config_missing",)
    bad: list[str] = []
    pid = config.get("pid") if isinstance(config.get("pid"), Mapping) else {}
    for axis in ("roll", "pitch", "yaw"):
        block = pid.get(axis) if isinstance(pid.get(axis), Mapping) else {}
        for comp, hi in (("p", PID_GAIN_MAX), ("i", PID_GAIN_MAX), ("d", PID_GAIN_MAX), ("d_max", PID_GAIN_MAX), ("ff", F_GAIN_MAX)):
            if comp not in block:
                continue
            try:
                v = float(block[comp])
            except (TypeError, ValueError):
                bad.append(f"{axis}.{comp}_non_numeric")
                continue
            if v != v or v < 0 or v > hi:
                bad.append(f"{axis}.{comp}_out_of_firmware_range")
    filt = config.get("filters") if isinstance(config.get("filters"), Mapping) else {}
    for key, hi in (
        ("gyro_lpf1_dyn_min_hz", DYN_LPF_MAX_HZ),
        ("gyro_lpf1_dyn_max_hz", DYN_LPF_MAX_HZ),
        ("gyro_lpf1_static_hz", LPF_MAX_HZ),
        ("gyro_lpf2_static_hz", LPF_MAX_HZ),
        ("dterm_lpf1_dyn_min_hz", DYN_LPF_MAX_HZ),
        ("dterm_lpf1_dyn_max_hz", DYN_LPF_MAX_HZ),
        ("dterm_lpf1_static_hz", LPF_MAX_HZ),
        ("dterm_lpf2_static_hz", LPF_MAX_HZ),
    ):
        if key not in filt:
            continue
        try:
            v = float(filt[key])
        except (TypeError, ValueError):
            bad.append(f"{key}_non_numeric")
            continue
        if v != v or v < 0 or v > hi:
            bad.append(f"{key}_out_of_firmware_range")
    return (not bad), tuple(bad)


def evaluate_tuning_output_safety(
    candidate: SafeTuneCandidate,
    *,
    analysis: Mapping[str, Any] | None = None,
    require_analysis: bool = True,
) -> TuningOutputSafetyResult:
    """Final authority for whether a later WU may expose the candidate.

    WU10 always reports ``cli_actionable=False``. Donor ``generated_cli_missing``
    is intentionally not a GyroCore block (CLI is WU11).
    """
    if not isinstance(candidate, SafeTuneCandidate):
        raise StageBypassError("evaluate_tuning_output_safety requires SafeTuneCandidate")

    blocking: list[str] = []
    warning: list[str] = []
    checks: list[SafetyCheck] = []
    proposal = candidate.proposal

    checks.append(
        SafetyCheck(
            rule_id="tos.mechanical_stage_present",
            verdict=SafetyVerdict.PASS,
            message="mechanical stage token present",
        )
    )
    checks.append(
        SafetyCheck(
            rule_id="tos.safe_tune_stage_present",
            verdict=SafetyVerdict.PASS,
            message="safe-tune stage token present",
        )
    )

    if candidate.mechanical.status is SafetyVerdict.BLOCK or candidate.mechanical.mechanical_block:
        blocking.append(BLOCK_MECHANICAL)
        blocking.extend(candidate.mechanical.blocking_reasons)
        checks.append(
            SafetyCheck(rule_id="tos.mechanical_not_blocked", verdict=SafetyVerdict.BLOCK, message=BLOCK_MECHANICAL)
        )
    elif candidate.mechanical.status is SafetyVerdict.WARN:
        warning.append("mechanical_limited_or_caution")
        warning.extend(candidate.mechanical.limited_reasons)
        warning.extend(candidate.mechanical.caution_reasons)

    if candidate.status is SafetyVerdict.BLOCK or candidate.blocked_reasons:
        blocking.append(BLOCK_CANDIDATE)
        blocking.extend(candidate.blocked_reasons)

    if proposal.status == MERGE_REQUIRES_REVIEW or proposal.review_reasons:
        blocking.append(BLOCK_MERGE_REVIEW)
        blocking.extend(proposal.review_reasons)

    sysid_codes = tuple(
        r for r in proposal.blocked_reasons if "system" in str(r).lower() or str(r).startswith("sysid")
    )
    if sysid_codes:
        blocking.append(BLOCK_SYSID)
        blocking.extend(sysid_codes)

    if proposal.proposed is None and proposal.status != MERGE_REQUIRES_REVIEW:
        if proposal.status == "blocked":
            blocking.append(BLOCK_MALFORMED)

    current_missing = []
    for axis in ("roll", "pitch", "yaw"):
        ax = proposal.current.axis(axis)
        for comp in ("p", "i", "d", "f"):
            if not getattr(ax, comp).present:
                current_missing.append(f"{axis}.{comp}")
    if current_missing:
        blocking.append(BLOCK_MISSING_BASELINE)

    if proposal.current.current_tune is None and "missing_current_tune" in proposal.blocked_reasons:
        blocking.append(BLOCK_MISSING_CURRENT)

    if proposal.proposed_validity is not None:
        val = proposal.proposed_validity
        if val.skipped_reasons:
            blocking.append(BLOCK_INVALID_SIMPLIFIED)
            blocking.extend(val.skipped_reasons)
        if val.pid_mismatches or val.gyro_mismatches or val.dterm_mismatches:
            blocking.append(BLOCK_SLIDER_INCONSISTENT)

    if require_analysis:
        if not isinstance(analysis, Mapping) or analysis.get("ok") is False:
            blocking.append(BLOCK_MISSING_ANALYSIS)
            checks.append(
                SafetyCheck(
                    rule_id="tos.required_analysis",
                    verdict=SafetyVerdict.BLOCK,
                    message=BLOCK_MISSING_ANALYSIS,
                )
            )

    quality = _quality_status(analysis)
    if quality == "low_quality":
        blocking.append("quality_status_low_quality")

    conf = _confidence_score(analysis)
    if conf < CONFIDENCE_PID_THRESHOLD:
        warning.append("analysis_confidence_low")
        checks.append(
            SafetyCheck(
                rule_id="tos.analysis_confidence",
                verdict=SafetyVerdict.WARN,
                message="analysis_confidence_low",
                evidence={"score": conf, "threshold": CONFIDENCE_PID_THRESHOLD},
            )
        )

    if _noise_high(analysis):
        warning.append("noise_level_high")

    ok_vals, val_reasons = _values_within_firmware(candidate.clamped_config)
    if candidate.clamped_config is not None and not ok_vals:
        blocking.append(BLOCK_VALUES)
        blocking.extend(val_reasons)

    if candidate.status is SafetyVerdict.WARN:
        warning.append("safe_tune_clamps_applied")
        warning.extend(candidate.clamp_ids)

    blocking = list(dict.fromkeys(str(x) for x in blocking if str(x).strip()))
    warning = list(dict.fromkeys(str(x) for x in warning if str(x).strip() and str(x) not in blocking))

    if blocking:
        status = SafetyVerdict.BLOCK
        donor_status = "blocked"
    elif warning:
        status = SafetyVerdict.WARN
        donor_status = "limited"
    else:
        status = SafetyVerdict.PASS
        donor_status = "actionable"

    checks.append(
        SafetyCheck(
            rule_id="tos.cli_actionable_frozen_false",
            verdict=SafetyVerdict.PASS,
            message="WU10 never exposes actionable CLI",
            after=False,
        )
    )
    checks.append(
        SafetyCheck(
            rule_id="tos.final_verdict",
            verdict=status,
            message=donor_status,
            evidence={"blocking": blocking, "warnings": warning},
        )
    )

    return make_tuning_output_safety(
        status=status,
        candidate=candidate,
        blocking_reasons=tuple(blocking),
        warning_reasons=tuple(warning),
        checks=tuple(checks),
        donor_status=donor_status,
        provenance={
            "donor": "backend.routes.analyze._build_tuning_output_safety",
            "not_migrated": [
                "generated_cli_missing_or_invalid",
                "hardware_source_default_*",
                "motor_poles_pipeline",
                "support_matrix_policy",
                "HTTP attach_tuning_output_safety",
            ],
            "gyrocore_only": [
                BLOCK_MERGE_REVIEW,
                BLOCK_SYSID,
                BLOCK_SLIDER_INCONSISTENT,
                BLOCK_MISSING_ANALYSIS,
                BLOCK_MISSING_BASELINE,
                "cli_actionable_always_false_wu10",
            ],
        },
    )


__all__ = [
    "CONFIDENCE_PID_THRESHOLD",
    "evaluate_tuning_output_safety",
]
