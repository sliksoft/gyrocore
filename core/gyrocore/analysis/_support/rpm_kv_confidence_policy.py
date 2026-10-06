# GyroCore WU4: adapted from AeroTuner backend/services/rpm_kv_confidence_policy.py
"""Hardware-class-aware RPM/KV confidence policy (v1 conservative defaults)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from gyrocore.analysis.motor_fft_harmonics import (
    RPM_ALIGNMENT_RATIO_MAX,
    RPM_ALIGNMENT_RATIO_MIN,
)
from gyrocore.analysis._support.hardware_class import resolve_rpm_policy_hardware_class

RPM_CONFIDENCE_CLEAR = "clear"
RPM_CONFIDENCE_LIMITED = "limited"
RPM_CONFIDENCE_INVALID = "invalid"

INDEPENDENT_GYRO_AGREEMENT_MAX_REL_DELTA = 0.05
RPM_REASON_LOW_SAMPLE_RATE = "gyro_crosscheck_not_assessable_low_sample_rate"
RPM_REASON_ERPM_NOT_GYRO_CONFIRMED = "erpm_telemetry_present_not_gyro_confirmed"
RPM_REASON_LOADED_WHOOP_NOLOAD_MODEL = "nominal_kv_model_unloaded_for_loaded_whoop"
RPM_REASON_ALIGNMENT_LIMITED = "rpm_kv_alignment_limited"

LOADED_OR_DUCTED_POLICY_CLASSES = frozenset(
    {
        "whoop_1s",
        "small_whoop_2s",
        "cinewhoop_ducted",
    }
)


@dataclass(frozen=True)
class RpmKvPolicySpec:
    policy_key: str
    policy_name: str
    kv_model_trust: str
    ratio_min: float
    ratio_max: float
    near_threshold_band: float
    extreme_invalid_min: float | None
    extreme_invalid_max: float | None
    allows_limited_from_model: bool
    erpm_dominant_always_limited: bool


def _policy(
    policy_key: str,
    *,
    policy_name: str,
    kv_model_trust: str,
    ratio_min: float,
    ratio_max: float,
    near_threshold_band: float = 0.0,
    extreme_invalid_min: float | None = None,
    extreme_invalid_max: float | None = None,
    allows_limited_from_model: bool = True,
    erpm_dominant_always_limited: bool = False,
) -> RpmKvPolicySpec:
    return RpmKvPolicySpec(
        policy_key=policy_key,
        policy_name=policy_name,
        kv_model_trust=kv_model_trust,
        ratio_min=ratio_min,
        ratio_max=ratio_max,
        near_threshold_band=near_threshold_band,
        extreme_invalid_min=extreme_invalid_min,
        extreme_invalid_max=extreme_invalid_max,
        allows_limited_from_model=allows_limited_from_model,
        erpm_dominant_always_limited=erpm_dominant_always_limited,
    )


# v1 conservative policy defaults, not empirical final thresholds.
# No further threshold tuning without mandatory 2-week Loki cohort review.
RPM_KV_POLICY_REGISTRY: dict[str, RpmKvPolicySpec] = {
    "whoop_1s": _policy(
        "whoop_1s",
        policy_name="rpm_kv_v1_whoop_soft_model",
        kv_model_trust="low",
        ratio_min=0.22,
        ratio_max=3.0,
        near_threshold_band=0.08,
        extreme_invalid_min=0.22,
        extreme_invalid_max=3.0,
        erpm_dominant_always_limited=True,
    ),
    "small_whoop_2s": _policy(
        "small_whoop_2s",
        policy_name="rpm_kv_v1_whoop_2s_soft_model",
        kv_model_trust="low",
        ratio_min=0.25,
        ratio_max=2.8,
        near_threshold_band=0.07,
        extreme_invalid_min=0.25,
        extreme_invalid_max=2.8,
        erpm_dominant_always_limited=True,
    ),
    "toothpick_2_3_5_inch": _policy(
        "toothpick_2_3_5_inch",
        policy_name="rpm_kv_v1_micro_soft_model",
        kv_model_trust="medium_low",
        ratio_min=0.30,
        ratio_max=2.6,
        near_threshold_band=0.06,
        extreme_invalid_min=0.30,
        extreme_invalid_max=2.6,
        erpm_dominant_always_limited=True,
    ),
    "standard_5_inch": _policy(
        "standard_5_inch",
        policy_name="rpm_kv_v1_standard_5_strict",
        kv_model_trust="high",
        ratio_min=0.40,
        ratio_max=2.5,
        near_threshold_band=0.03,
        extreme_invalid_min=0.40,
        extreme_invalid_max=2.5,
        erpm_dominant_always_limited=False,
    ),
    "freestyle_6_inch": _policy(
        "freestyle_6_inch",
        policy_name="rpm_kv_v1_freestyle_6",
        kv_model_trust="high",
        ratio_min=0.36,
        ratio_max=2.6,
        near_threshold_band=0.04,
        extreme_invalid_min=0.36,
        extreme_invalid_max=2.6,
        erpm_dominant_always_limited=False,
    ),
    "long_range_7_inch": _policy(
        "long_range_7_inch",
        policy_name="rpm_kv_v1_long_range_7",
        kv_model_trust="medium",
        ratio_min=0.32,
        ratio_max=2.7,
        near_threshold_band=0.05,
        extreme_invalid_min=0.32,
        extreme_invalid_max=2.7,
        erpm_dominant_always_limited=True,
    ),
    "heavy_long_range_10_inch": _policy(
        "heavy_long_range_10_inch",
        policy_name="rpm_kv_v1_large_prop_10",
        kv_model_trust="low",
        ratio_min=0.28,
        ratio_max=3.2,
        near_threshold_band=0.10,
        extreme_invalid_min=0.18,
        extreme_invalid_max=3.5,
        erpm_dominant_always_limited=True,
    ),
    "cinewhoop_ducted": _policy(
        "cinewhoop_ducted",
        policy_name="rpm_kv_v1_cinewhoop_ducted_soft_model",
        kv_model_trust="low",
        ratio_min=0.22,
        ratio_max=3.0,
        near_threshold_band=0.08,
        extreme_invalid_min=0.22,
        extreme_invalid_max=3.0,
        erpm_dominant_always_limited=True,
    ),
    "xclass_large_prop": _policy(
        "xclass_large_prop",
        policy_name="rpm_kv_v1_xclass_large_prop",
        kv_model_trust="low",
        ratio_min=0.24,
        ratio_max=3.2,
        near_threshold_band=0.10,
        extreme_invalid_min=0.16,
        extreme_invalid_max=3.8,
        erpm_dominant_always_limited=True,
    ),
    "unknown": _policy(
        "unknown",
        policy_name="rpm_kv_v1_unknown_strict",
        kv_model_trust="strict",
        ratio_min=RPM_ALIGNMENT_RATIO_MIN,
        ratio_max=RPM_ALIGNMENT_RATIO_MAX,
        near_threshold_band=0.0,
        extreme_invalid_min=RPM_ALIGNMENT_RATIO_MIN,
        extreme_invalid_max=RPM_ALIGNMENT_RATIO_MAX,
        allows_limited_from_model=False,
        erpm_dominant_always_limited=False,
    ),
}


def get_rpm_kv_policy(hardware_class: Any) -> RpmKvPolicySpec:
    key = resolve_rpm_policy_hardware_class(hardware_class)
    return RPM_KV_POLICY_REGISTRY.get(key, RPM_KV_POLICY_REGISTRY["unknown"])


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _ratio_out_of_band(ratio: float, lo: float, hi: float) -> bool:
    return ratio < lo or ratio > hi


def _ratio_threshold_margin(ratio: float, lo: float, hi: float) -> float:
    if ratio < lo:
        return round(lo - ratio, 4)
    if ratio > hi:
        return round(ratio - hi, 4)
    return round(min(ratio - lo, hi - ratio), 4)


def _infer_independent_gyro_peak_present(gyro_merge: dict[str, Any]) -> bool:
    if str(gyro_merge.get("gyro_hz_fallback") or "").strip() == "erpm_dominant":
        return False
    axis_peaks = gyro_merge.get("axis_peaks_hz")
    if not isinstance(axis_peaks, dict):
        return False
    for key in ("roll", "pitch", "yaw"):
        peak = _safe_float(axis_peaks.get(key))
        if peak is not None and peak > 0:
            return True
    return False


def _infer_erpm_gyro_relative_delta(gyro_merge: dict[str, Any]) -> float | None:
    gyro_hz = (
        _safe_float(gyro_merge.get("corrected_gyro_hz"))
        or _safe_float(gyro_merge.get("merged_hz_for_frame_model"))
        or _safe_float(gyro_merge.get("original_gyro_hz"))
    )
    erpm_motor_hz = _safe_float(gyro_merge.get("gyro_hz_fallback_motor_hz"))
    if gyro_hz is None or erpm_motor_hz is None or gyro_hz <= 0 or erpm_motor_hz <= 0:
        return None
    denom = max(gyro_hz, erpm_motor_hz)
    if denom <= 0:
        return None
    return round(abs(gyro_hz - erpm_motor_hz) / denom, 4)


def _limited_context_reasons(
    *,
    policy: RpmKvPolicySpec,
    ratio: float | None,
    model_oob: bool,
    policy_oob: bool,
    primary_reason: str | None,
) -> list[str]:
    reasons: list[str] = []
    if primary_reason:
        reasons.append(primary_reason)
    if (
        ratio is not None
        and ratio < RPM_ALIGNMENT_RATIO_MIN
        and model_oob
        and not policy_oob
        and policy.policy_key in LOADED_OR_DUCTED_POLICY_CLASSES
    ):
        reasons.append(RPM_REASON_LOADED_WHOOP_NOLOAD_MODEL)
    if reasons:
        reasons.append(RPM_REASON_ALIGNMENT_LIMITED)
    return list(dict.fromkeys(reasons))


def evaluate_rpm_kv_confidence(
    *,
    ratio: float | None,
    harmonic_match: bool,
    hardware_class: Any = None,
    gyro_hz_fallback: Any = None,
    gyro_merge: dict[str, Any] | None = None,
    independent_gyro_peak_present: bool | None = None,
    gyro_crosscheck_assessable: bool | None = None,
    erpm_gyro_relative_delta: float | None = None,
) -> dict[str, Any]:
    """Return RPM/KV confidence policy fields (pure; no I/O)."""
    gm = gyro_merge if isinstance(gyro_merge, dict) else {}
    policy = get_rpm_kv_policy(hardware_class)
    rv = _safe_float(ratio)

    erpm_same_source = str(gyro_hz_fallback or gm.get("gyro_hz_fallback") or "").strip() == "erpm_dominant"
    indep_peak = (
        independent_gyro_peak_present
        if independent_gyro_peak_present is not None
        else (
            bool(gm.get("independent_gyro_peak_present"))
            if isinstance(gm.get("independent_gyro_peak_present"), bool)
            else _infer_independent_gyro_peak_present(gm)
        )
    )
    crosscheck_assessable = (
        gyro_crosscheck_assessable
        if gyro_crosscheck_assessable is not None
        else gm.get("gyro_crosscheck_assessable")
    )
    if crosscheck_assessable is None:
        crosscheck_assessable = True
    rel_delta = (
        erpm_gyro_relative_delta
        if erpm_gyro_relative_delta is not None
        else _infer_erpm_gyro_relative_delta(gm)
    )
    indep_agreement = (
        indep_peak
        and not erpm_same_source
        and rel_delta is not None
        and rel_delta <= INDEPENDENT_GYRO_AGREEMENT_MAX_REL_DELTA
    )

    if gm.get("rpm_mismatch_suppressed_by_erpm_confirmation") is True or (
        gm.get("rpm_mismatch_suppressed_by_precap_erpm") is True
    ):
        return {
            "rpm_ratio_out_of_model_band": False,
            "rpm_ratio_out_of_policy_band": False,
            "rpm_confidence_class": RPM_CONFIDENCE_CLEAR,
            "rpm_confidence_reason": "erpm_confirmation_suppressed_mismatch",
            "rpm_should_block_paste_ready": False,
            "rpm_context_reasons": [],
            "rpm_cap_reason": None,
            "rpm_policy_name": policy.policy_name,
            "rpm_policy_hardware_class": policy.policy_key,
            "rpm_policy_threshold_min": policy.ratio_min,
            "rpm_policy_threshold_max": policy.ratio_max,
            "ratio_threshold_margin": None,
            "erpm_gyro_same_source": erpm_same_source,
            "independent_gyro_peak_present": indep_peak,
            "gyro_crosscheck_assessable": bool(crosscheck_assessable),
            "erpm_gyro_independent_agreement": indep_agreement,
            "erpm_gyro_relative_delta": rel_delta,
            "kv_model_plausibility": "plausible",
        }

    out: dict[str, Any] = {
        "rpm_ratio_out_of_model_band": False,
        "rpm_ratio_out_of_policy_band": False,
        "rpm_confidence_class": RPM_CONFIDENCE_CLEAR,
        "rpm_confidence_reason": "ratio_in_band",
        "rpm_should_block_paste_ready": False,
        "rpm_context_reasons": [],
        "rpm_cap_reason": None,
        "rpm_policy_name": policy.policy_name,
        "rpm_policy_hardware_class": policy.policy_key,
        "rpm_policy_threshold_min": policy.ratio_min,
        "rpm_policy_threshold_max": policy.ratio_max,
        "ratio_threshold_margin": None,
        "erpm_gyro_same_source": erpm_same_source,
        "independent_gyro_peak_present": indep_peak,
        "gyro_crosscheck_assessable": bool(crosscheck_assessable),
        "erpm_gyro_independent_agreement": indep_agreement,
        "erpm_gyro_relative_delta": rel_delta,
        "kv_model_plausibility": "plausible",
    }

    if rv is None or rv <= 0:
        out["rpm_confidence_class"] = RPM_CONFIDENCE_INVALID
        out["rpm_confidence_reason"] = "ratio_missing"
        out["rpm_should_block_paste_ready"] = True
        out["kv_model_plausibility"] = "implausible"
        return out

    if harmonic_match:
        out["rpm_confidence_reason"] = "harmonic_match"
        out["ratio_threshold_margin"] = _ratio_threshold_margin(rv, policy.ratio_min, policy.ratio_max)
        return out

    model_oob = _ratio_out_of_band(rv, RPM_ALIGNMENT_RATIO_MIN, RPM_ALIGNMENT_RATIO_MAX)
    policy_oob = _ratio_out_of_band(rv, policy.ratio_min, policy.ratio_max)
    out["rpm_ratio_out_of_model_band"] = model_oob
    out["rpm_ratio_out_of_policy_band"] = policy_oob
    out["ratio_threshold_margin"] = _ratio_threshold_margin(rv, policy.ratio_min, policy.ratio_max)

    extreme_min = policy.extreme_invalid_min if policy.extreme_invalid_min is not None else policy.ratio_min
    extreme_max = policy.extreme_invalid_max if policy.extreme_invalid_max is not None else policy.ratio_max
    if rv < extreme_min:
        out["rpm_confidence_class"] = RPM_CONFIDENCE_INVALID
        out["rpm_confidence_reason"] = "ratio_extreme_low"
        out["rpm_should_block_paste_ready"] = True
        out["kv_model_plausibility"] = "implausible"
        out["rpm_context_reasons"] = [out["rpm_confidence_reason"]]
        return out
    if rv > extreme_max:
        out["rpm_confidence_class"] = RPM_CONFIDENCE_INVALID
        out["rpm_confidence_reason"] = "ratio_extreme_high"
        out["rpm_should_block_paste_ready"] = True
        out["kv_model_plausibility"] = "implausible"
        out["rpm_context_reasons"] = [out["rpm_confidence_reason"]]
        return out

    if indep_peak and not erpm_same_source and rel_delta is not None:
        if rel_delta > INDEPENDENT_GYRO_AGREEMENT_MAX_REL_DELTA:
            out["rpm_confidence_class"] = RPM_CONFIDENCE_INVALID
            out["rpm_confidence_reason"] = "independent_erpm_gyro_mismatch"
            out["rpm_should_block_paste_ready"] = True
            out["kv_model_plausibility"] = "implausible"
            out["rpm_context_reasons"] = [out["rpm_confidence_reason"]]
            return out

    if erpm_same_source and not crosscheck_assessable:
        out["rpm_confidence_class"] = RPM_CONFIDENCE_LIMITED
        out["rpm_confidence_reason"] = RPM_REASON_LOW_SAMPLE_RATE
        out["rpm_should_block_paste_ready"] = False
        out["kv_model_plausibility"] = "limited"
        out["rpm_context_reasons"] = _limited_context_reasons(
            policy=policy,
            ratio=rv,
            model_oob=model_oob,
            policy_oob=policy_oob,
            primary_reason=out["rpm_confidence_reason"],
        )
        out["rpm_cap_reason"] = RPM_REASON_ALIGNMENT_LIMITED
        return out

    if erpm_same_source and crosscheck_assessable and not indep_peak:
        out["rpm_confidence_class"] = RPM_CONFIDENCE_LIMITED
        out["rpm_confidence_reason"] = RPM_REASON_ERPM_NOT_GYRO_CONFIRMED
        out["rpm_should_block_paste_ready"] = False
        out["kv_model_plausibility"] = "limited" if (model_oob or policy_oob) else "plausible"
        out["rpm_context_reasons"] = _limited_context_reasons(
            policy=policy,
            ratio=rv,
            model_oob=model_oob,
            policy_oob=policy_oob,
            primary_reason=out["rpm_confidence_reason"],
        )
        out["rpm_cap_reason"] = RPM_REASON_ALIGNMENT_LIMITED
        return out

    if not policy_oob and not model_oob:
        out["rpm_confidence_reason"] = "ratio_in_band"
        return out

    if policy.policy_key == "unknown":
        out["rpm_confidence_class"] = RPM_CONFIDENCE_INVALID
        out["rpm_confidence_reason"] = "unknown_class_strict_band_violation"
        out["rpm_should_block_paste_ready"] = True
        out["kv_model_plausibility"] = "implausible"
        out["rpm_context_reasons"] = [out["rpm_confidence_reason"]]
        return out

    near_threshold = False
    if policy.near_threshold_band > 0:
        if rv < policy.ratio_min and (policy.ratio_min - rv) <= policy.near_threshold_band:
            near_threshold = True
        if rv > policy.ratio_max and (rv - policy.ratio_max) <= policy.near_threshold_band:
            near_threshold = True

    limited_reason: str | None = None
    if erpm_same_source and policy.erpm_dominant_always_limited and not crosscheck_assessable:
        limited_reason = RPM_REASON_LOW_SAMPLE_RATE
    elif erpm_same_source and policy.erpm_dominant_always_limited:
        limited_reason = RPM_REASON_ERPM_NOT_GYRO_CONFIRMED
    elif (
        model_oob
        and not policy_oob
        and policy.policy_key in LOADED_OR_DUCTED_POLICY_CLASSES
    ):
        limited_reason = RPM_REASON_LOADED_WHOOP_NOLOAD_MODEL
    elif model_oob and policy.allows_limited_from_model:
        limited_reason = "kv_model_soft_mismatch"
    elif policy_oob and policy.allows_limited_from_model:
        limited_reason = "policy_band_soft_mismatch"
    elif near_threshold and policy.allows_limited_from_model:
        limited_reason = "near_threshold_soft_mismatch"

    if limited_reason and not policy_oob:
        out["rpm_confidence_class"] = RPM_CONFIDENCE_LIMITED
        out["rpm_confidence_reason"] = limited_reason
        out["kv_model_plausibility"] = "limited"
        out["rpm_context_reasons"] = _limited_context_reasons(
            policy=policy,
            ratio=rv,
            model_oob=model_oob,
            policy_oob=policy_oob,
            primary_reason=limited_reason,
        )
        out["rpm_cap_reason"] = RPM_REASON_ALIGNMENT_LIMITED
        return out

    if policy_oob:
        if policy.allows_limited_from_model and policy.policy_key in {
            "heavy_long_range_10_inch",
            "cinewhoop_ducted",
            "xclass_large_prop",
            "whoop_1s",
            "small_whoop_2s",
            "toothpick_2_3_5_inch",
            "freestyle_6_inch",
            "long_range_7_inch",
        }:
            out["rpm_confidence_class"] = RPM_CONFIDENCE_LIMITED
            out["rpm_confidence_reason"] = limited_reason or "policy_band_soft_mismatch"
            out["kv_model_plausibility"] = "limited"
            out["rpm_context_reasons"] = _limited_context_reasons(
                policy=policy,
                ratio=rv,
                model_oob=model_oob,
                policy_oob=policy_oob,
                primary_reason=out["rpm_confidence_reason"],
            )
            out["rpm_cap_reason"] = RPM_REASON_ALIGNMENT_LIMITED
            return out
        out["rpm_confidence_class"] = RPM_CONFIDENCE_INVALID
        out["rpm_confidence_reason"] = "policy_band_violation"
        out["rpm_should_block_paste_ready"] = True
        out["kv_model_plausibility"] = "implausible"
        out["rpm_context_reasons"] = [out["rpm_confidence_reason"]]
        return out

    if model_oob and policy.allows_limited_from_model:
        out["rpm_confidence_class"] = RPM_CONFIDENCE_LIMITED
        out["rpm_confidence_reason"] = limited_reason or "kv_model_soft_mismatch"
        out["kv_model_plausibility"] = "limited"
        out["rpm_context_reasons"] = _limited_context_reasons(
            policy=policy,
            ratio=rv,
            model_oob=model_oob,
            policy_oob=policy_oob,
            primary_reason=out["rpm_confidence_reason"],
        )
        out["rpm_cap_reason"] = RPM_REASON_ALIGNMENT_LIMITED
        return out

    out["rpm_confidence_class"] = RPM_CONFIDENCE_INVALID
    out["rpm_confidence_reason"] = "model_band_violation"
    out["rpm_should_block_paste_ready"] = True
    out["kv_model_plausibility"] = "implausible"
    out["rpm_context_reasons"] = [out["rpm_confidence_reason"]]
    return out


def apply_rpm_kv_confidence_policy(
    gyro_merge: dict[str, Any],
    *,
    hardware_class: Any = None,
) -> dict[str, Any]:
    """Evaluate policy and merge results into ``gyro_merge`` (mutates and returns)."""
    if not isinstance(gyro_merge, dict):
        return {}
    align = gyro_merge.get("rpm_alignment")
    align_dict = align if isinstance(align, dict) else {}
    confidence = evaluate_rpm_kv_confidence(
        ratio=_safe_float(align_dict.get("ratio")),
        harmonic_match=align_dict.get("harmonic_match") is True,
        hardware_class=hardware_class,
        gyro_hz_fallback=gyro_merge.get("gyro_hz_fallback"),
        gyro_merge=gyro_merge,
        gyro_crosscheck_assessable=gyro_merge.get("gyro_crosscheck_assessable"),
    )
    gyro_merge.update(confidence)
    gyro_merge["rpm_mismatch"] = confidence["rpm_confidence_class"] == RPM_CONFIDENCE_INVALID
    return gyro_merge
