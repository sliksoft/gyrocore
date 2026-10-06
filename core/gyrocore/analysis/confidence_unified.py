# GyroCore WU4: adapted from AeroTuner backend/analysis/confidence_unified.py
"""
Unified flight-analysis confidence: single implementation for API + tuning.

Derives a 0–1 score from FFT peaks, noise band, cluster shape, consistency,
harmonic alignment, and primary resonance confidence.
``resonance_conf`` (primary peak confidence 0–1) is recorded in factors and reason.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from gyrocore.analysis.noise_model import classify_noise_level_from_ratio
from gyrocore.analysis._support.hardware_profile import get_hardware_profile

# ``default`` / ``user`` unified multipliers; ``detected`` uses signal tier (see below).
_UNIFIED_FIELD_MULT: dict[str, dict[str, float]] = {
    "frame": {"user": 1.0, "default": 0.96},
    "motor_kv": {"user": 1.0, "default": 0.93},
    "battery": {"user": 1.0, "default": 0.93},
}
_DETECTED_MULT_BY_QUALITY: dict[str, float] = {
    "high": 0.94,
    "medium": 0.92,
    "low": 0.90,
}
_DETECTED_CAP_BY_QUALITY: dict[str, float] = {
    "high": 0.74,
    "medium": 0.70,
    "low": 0.66,
}


def _aggregate_hardware_source_label(sources: dict[str, str]) -> str:
    f = sources.get("frame", "user")
    k = sources.get("motor_kv", "user")
    b = sources.get("battery", "user")
    if "default" in (f, k, b):
        return "default"
    if "detected" in (f, k, b):
        return "detected"
    return "user"


def _detected_unified_multiplier(hardware_signal_context: dict[str, Any] | None) -> float:
    if not isinstance(hardware_signal_context, dict):
        return _DETECTED_MULT_BY_QUALITY["medium"]
    tier = str(hardware_signal_context.get("detected_quality") or "medium").lower()
    return float(_DETECTED_MULT_BY_QUALITY.get(tier, 0.92))


def _confidence_level(score: float) -> str:
    if score >= 0.67:
        return "high"
    if score >= 0.34:
        return "medium"
    return "low"


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _with_confidence_cap(
    confidence_eval: Mapping[str, Any],
    *,
    cap: float,
    reason: str,
    detail: str | None = None,
) -> dict[str, Any]:
    out = dict(confidence_eval)
    score = _finite_float(out.get("score"))
    if score is None:
        score = 0.0
    cap = max(0.0, min(1.0, float(cap)))
    was_capped = score > cap
    if was_capped:
        out["score"] = round(cap, 3)
        out["level"] = _confidence_level(cap)
        base = str(out.get("reason") or "")
        suffix = f"confidence_capped:{reason}"
        out["reason"] = f"{base}; {suffix}" if base else suffix

    factors_raw = out.get("factors")
    factors: dict[str, Any] = dict(factors_raw) if isinstance(factors_raw, Mapping) else {}
    governors_raw = factors.get("confidence_governors")
    governors = list(governors_raw) if isinstance(governors_raw, list) else []
    row: dict[str, Any] = {"reason": reason, "cap": round(cap, 3), "applied": was_capped}
    if detail:
        row["detail"] = detail
    governors.append(row)
    factors["confidence_governors"] = governors
    out["factors"] = factors

    limitations_raw = out.get("limitations")
    limitations = [str(x) for x in limitations_raw] if isinstance(limitations_raw, list) else []
    if reason not in limitations:
        limitations.append(reason)
    out["limitations"] = limitations
    return out


def adjust_unified_confidence_for_hardware_sources(
    confidence_eval: dict[str, Any],
    hardware_sources: dict[str, str] | None,
    hardware_signal_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Apply independent multipliers per core hardware field (frame / motor_kv / battery).
    ``hardware_sources`` values: ``user`` | ``detected`` | ``default``.
    ``detected`` uses ``hardware_signal_context["detected_quality"]`` (``high`` | ``medium`` | ``low``).
    """
    if not isinstance(confidence_eval, dict) or not isinstance(hardware_sources, dict):
        return confidence_eval
    mult = 1.0
    any_detected = False
    for key in ("frame", "motor_kv", "battery"):
        src = str(hardware_sources.get(key) or "user")
        row = _UNIFIED_FIELD_MULT.get(key) or {}
        if src == "default":
            mult *= float(row.get("default", 1.0))
        elif src == "detected":
            any_detected = True
        else:
            mult *= float(row.get("user", 1.0))
    if any_detected:
        mult *= _detected_unified_multiplier(hardware_signal_context)
    if mult >= 0.9999:
        return confidence_eval

    out = dict(confidence_eval)
    try:
        score = float(out.get("score", 0.0))
    except (TypeError, ValueError):
        score = 0.0
    if score != score:  # NaN
        score = 0.0
    new_score = max(0.0, min(1.0, score * mult))
    if any(str(hardware_sources.get(key) or "user") == "default" for key in ("frame", "motor_kv", "battery")):
        new_score = min(new_score, 0.62)
    elif any_detected:
        detected_tier = (
            str(hardware_signal_context.get("detected_quality") or "medium").lower()
            if isinstance(hardware_signal_context, dict)
            else "medium"
        )
        new_score = min(new_score, float(_DETECTED_CAP_BY_QUALITY.get(detected_tier, 0.70)))
    new_score = round(new_score, 3)
    out["score"] = new_score
    out["level"] = _confidence_level(new_score)
    base = str(out.get("reason") or "")
    parts = [
        f"frame={hardware_sources.get('frame', 'user')}",
        f"motor_kv={hardware_sources.get('motor_kv', 'user')}",
        f"battery={hardware_sources.get('battery', 'user')}",
    ]
    suffix = f"hardware_sources ({', '.join(parts)})"
    out["reason"] = f"{base}; {suffix}" if base else suffix
    fac = out.get("factors")
    factors: dict[str, Any] = dict(fac) if isinstance(fac, dict) else {}
    factors["hardware_sources"] = {
        "frame": str(hardware_sources.get("frame") or "user"),
        "motor_kv": str(hardware_sources.get("motor_kv") or "user"),
        "battery": str(hardware_sources.get("battery") or "user"),
    }
    factors["hardware_source"] = _aggregate_hardware_source_label(factors["hardware_sources"])
    if any_detected:
        if isinstance(hardware_signal_context, dict) and hardware_signal_context.get(
            "detected_quality"
        ):
            factors["detected_quality"] = str(
                hardware_signal_context["detected_quality"]
            ).lower()
        else:
            factors["detected_quality"] = "medium"
    out["factors"] = factors
    return out


def apply_confidence_quality_governors(
    confidence_eval: dict[str, Any],
    *,
    quality_report: Mapping[str, Any] | None = None,
    erpm_analysis: Mapping[str, Any] | None = None,
    spectral_evidence: Mapping[str, Any] | None = None,
    hardware_class: str | None = None,
) -> dict[str, Any]:
    """Conservatively cap exposed confidence when supporting evidence is weak."""
    if not isinstance(confidence_eval, dict):
        return confidence_eval

    out: dict[str, Any] = dict(confidence_eval)

    if isinstance(quality_report, Mapping):
        status = str(quality_report.get("status") or "").strip().lower()
        if status == "low_quality":
            out = _with_confidence_cap(out, cap=0.33, reason="quality_status_low_quality")
        elif status == "low_confidence":
            out = _with_confidence_cap(out, cap=0.66, reason="quality_status_low_confidence")

        quality_score = _finite_float(quality_report.get("score"))
        if quality_score is not None:
            if quality_score < 40.0:
                out = _with_confidence_cap(
                    out,
                    cap=0.33,
                    reason="log_quality_poor",
                    detail=f"score={round(quality_score, 2)}",
                )
            elif quality_score < 60.0:
                out = _with_confidence_cap(
                    out,
                    cap=0.66,
                    reason="log_quality_marginal",
                    detail=f"score={round(quality_score, 2)}",
                )

        metrics = quality_report.get("metrics")
        if isinstance(metrics, Mapping):
            throttle_var = _finite_float(metrics.get("throttle_variation"))
            if throttle_var is not None:
                if throttle_var < 0.08:
                    out = _with_confidence_cap(
                        out,
                        cap=0.58,
                        reason="throttle_variety_low",
                        detail=f"throttle_variation={round(throttle_var, 4)}",
                    )
                elif throttle_var < 0.14:
                    out = _with_confidence_cap(
                        out,
                        cap=0.66,
                        reason="throttle_variety_limited",
                        detail=f"throttle_variation={round(throttle_var, 4)}",
                    )

            # Stick activity below the quality-engine warning threshold: add to
            # limitations without capping confidence so the result UI can surface it.
            stick_act = _finite_float(metrics.get("stick_activity"))
            if stick_act is not None and stick_act < 0.22:
                out = _with_confidence_cap(
                    out,
                    cap=1.0,
                    reason="stick_activity_low",
                    detail=f"stick_activity={round(stick_act, 4)}",
                )

    if isinstance(erpm_analysis, Mapping):
        profile = get_hardware_profile(hardware_class)
        skip_missing_erpm_cap = bool(
            profile is not None
            and (
                profile.ducted is True
                or str(profile.noise_expectation).strip().lower() == "high"
            )
        )
        coverage = _finite_float(erpm_analysis.get("erpm_sample_coverage"))
        rows = _finite_float(erpm_analysis.get("erpm_rows_with_erpm"))
        motor_freqs = erpm_analysis.get("motor_frequencies_hz")
        usable_freqs = (
            [x for x in motor_freqs if _finite_float(x) is not None and float(x) > 0.0]
            if isinstance(motor_freqs, list)
            else []
        )
        telemetry_missing = (
            (coverage is not None and coverage <= 0.0)
            or (rows is not None and rows <= 0.0)
            or (motor_freqs is not None and not usable_freqs)
        )
        if telemetry_missing and not skip_missing_erpm_cap:
            out = _with_confidence_cap(out, cap=0.66, reason="erpm_telemetry_missing")

    if isinstance(spectral_evidence, Mapping):
        quality = str(spectral_evidence.get("quality") or "").strip().lower()
        if quality == "low":
            out = _with_confidence_cap(out, cap=0.58, reason="spectral_quality_low")
        if spectral_evidence.get("samples_were_capped") is True:
            out = _with_confidence_cap(out, cap=0.66, reason="spectral_samples_capped")
        if spectral_evidence.get("samples_were_subsampled") is True:
            out = _with_confidence_cap(out, cap=0.66, reason="spectral_samples_subsampled")

    return out


_LIMITATION_REASON_TEXT: dict[str, str] = {
    "quality_status_low_quality": "Log quality was rated low, so confidence is capped.",
    "quality_status_low_confidence": "The quality gate returned low confidence, so confidence is capped.",
    "log_quality_poor": "The log quality score is poor, so high confidence is not allowed.",
    "log_quality_marginal": "The log quality score is marginal, so confidence is limited.",
    "throttle_variety_low": "Throttle variety is low, so evidence is less representative.",
    "throttle_variety_limited": "Throttle variety is limited, so evidence is less representative.",
    "erpm_telemetry_missing": "ERPM/RPM telemetry is missing, so RPM and harmonic certainty is limited.",
    "spectral_quality_low": "Spectral evidence quality is low, so filter and harmonic certainty is limited.",
    "spectral_samples_capped": "Spectral evidence came from a capped sample window.",
    "spectral_samples_subsampled": "Spectral evidence came from a subsampled log window.",
}

_LIMITATION_TIP_TEXT: dict[str, str] = {
    "quality_status_low_quality": "Use a cleaner tuning flight log with stable sampling and fewer dropouts.",
    "quality_status_low_confidence": "Use a controlled tuning flight with clear inputs and representative throttle range.",
    "log_quality_poor": "Re-log with a clean tuning flight before trusting high-confidence changes.",
    "log_quality_marginal": "A cleaner log with steadier sampling can improve confidence.",
    "throttle_variety_low": "Re-log with broader throttle range and deliberate pitch/roll inputs.",
    "throttle_variety_limited": "Include more varied throttle and maneuver inputs in the next log.",
    "erpm_telemetry_missing": "Enable bidirectional DShot/RPM telemetry and include ERPM fields in the log.",
    "spectral_quality_low": "Capture a cleaner log with less vibration/noise before relying on filter certainty.",
    "spectral_samples_capped": "Upload a shorter focused log or re-log a representative tuning flight.",
    "spectral_samples_subsampled": "Upload a shorter focused log to avoid subsampled spectral evidence.",
}


def _append_unique_text(items: list[str], text: str | None, *, limit: int | None = None) -> None:
    if not isinstance(text, str):
        return
    clean = " ".join(text.strip().split())
    if not clean or clean in items:
        return
    if limit is not None and len(items) >= limit:
        return
    items.append(clean)


def _format_percent(value: Any) -> str | None:
    number = _finite_float(value)
    if number is None:
        return None
    return f"{round(max(0.0, min(1.0, number)) * 100):.0f}%"


def _humanize_confidence_code(code: str) -> str:
    return code.replace("_", " ").strip()


def build_confidence_explanation(confidence_eval: Mapping[str, Any] | None) -> dict[str, Any]:
    """
    Convert final backend confidence evidence into a small public explanation.

    This is a deterministic projection only: it does not score, cap, recommend,
    inspect raw samples, or call any external service.
    """
    if not isinstance(confidence_eval, Mapping):
        return {
            "summary": "Confidence is based on the available analysis evidence, but detailed confidence factors were not available.",
            "reasons": [],
            "improvement_tips": [
                "Use a controlled tuning flight with clean logging and representative throttle range.",
            ],
        }

    score = _finite_float(confidence_eval.get("score"))
    level_raw = str(confidence_eval.get("level") or "").strip().lower()
    level = level_raw if level_raw in {"high", "medium", "low"} else (
        _confidence_level(score) if score is not None else "medium"
    )
    score_text = _format_percent(score)
    level_label = level.capitalize()
    summary = (
        f"Confidence is {level} ({score_text}) based on the available signal evidence."
        if score_text
        else f"Confidence is {level} based on the available signal evidence."
    )

    factors_raw = confidence_eval.get("factors")
    factors: Mapping[str, Any] = factors_raw if isinstance(factors_raw, Mapping) else {}
    reasons: list[str] = []
    tips: list[str] = []

    noise_level = str(factors.get("noise_level") or "").strip().lower()
    if noise_level in {"low", "medium", "high"}:
        _append_unique_text(reasons, f"Noise evidence is {noise_level}.")
        if noise_level == "high":
            _append_unique_text(tips, "Reduce vibration/noise and capture a cleaner log.")

    cluster_strength = str(factors.get("cluster_strength") or "").strip().lower()
    if cluster_strength:
        _append_unique_text(reasons, f"FFT peak clustering is {cluster_strength}.")
        if cluster_strength == "weak":
            _append_unique_text(tips, "A log with clearer resonance peaks can improve confidence.")

    peak_consistency = str(factors.get("peak_consistency") or "").strip().lower()
    if peak_consistency:
        _append_unique_text(reasons, f"Peak consistency is {peak_consistency}.")
        if peak_consistency in {"low", "unknown"}:
            _append_unique_text(tips, "Use a more repeatable tuning flight so peaks are easier to confirm.")

    harmonic_alignment = str(factors.get("harmonic_alignment") or "").strip().lower()
    if harmonic_alignment:
        _append_unique_text(reasons, f"Harmonic alignment is {harmonic_alignment.replace('_', ' ')}.")
        if harmonic_alignment in {"none", "partial"}:
            _append_unique_text(tips, "RPM telemetry and cleaner resonance evidence can improve harmonic certainty.")

    resonance_text = _format_percent(factors.get("resonance_confidence"))
    if resonance_text:
        _append_unique_text(reasons, f"Primary resonance confidence is {resonance_text}.")

    if str(factors.get("bandwidth") or "").strip().lower() == "deferred":
        _append_unique_text(reasons, "Bandwidth evidence is deferred and is not included in the confidence score.")

    hardware_sources = factors.get("hardware_sources")
    if isinstance(hardware_sources, Mapping):
        source_bits: list[str] = []
        for key in ("frame", "motor_kv", "battery"):
            src = str(hardware_sources.get(key) or "user").strip().lower()
            if src:
                source_bits.append(f"{key}={src}")
        if source_bits:
            _append_unique_text(reasons, f"Hardware source evidence: {', '.join(source_bits)}.")
        if any(
            str(hardware_sources.get(key) or "user").strip().lower() in {"default", "detected"}
            for key in ("frame", "motor_kv", "battery")
        ):
            _append_unique_text(
                tips,
                "Confirm frame, motor KV, and battery instead of relying on detected/default hardware.",
            )

    governors = factors.get("confidence_governors")
    if isinstance(governors, list):
        for row in governors:
            if not isinstance(row, Mapping):
                continue
            code = str(row.get("reason") or "").strip()
            if not code:
                continue
            cap_text = _format_percent(row.get("cap"))
            reason_text = _LIMITATION_REASON_TEXT.get(code, _humanize_confidence_code(code))
            if row.get("applied") is True and cap_text:
                _append_unique_text(reasons, f"Confidence was capped at {cap_text}: {reason_text}")
            else:
                _append_unique_text(reasons, reason_text)

    limitations_raw = confidence_eval.get("limitations")
    if isinstance(limitations_raw, list):
        for item in limitations_raw:
            if not isinstance(item, str):
                continue
            code = item.strip()
            if not code:
                continue
            _append_unique_text(
                reasons,
                _LIMITATION_REASON_TEXT.get(code, _humanize_confidence_code(code)),
            )
            _append_unique_text(tips, _LIMITATION_TIP_TEXT.get(code))

    if not reasons:
        _append_unique_text(reasons, f"{level_label} confidence comes from the final backend confidence score.")

    if not tips and level != "high":
        _append_unique_text(
            tips,
            "Use a controlled tuning flight with clean logging and representative throttle range.",
        )

    return {
        "summary": summary,
        "reasons": reasons[:8],
        "improvement_tips": tips[:5],
    }


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _resolved_noise_level_lowercase(analysis: dict) -> str:
    """low | medium | high from unified label or noise_ratio."""
    nl_u = str(analysis.get("noise_level_unified") or "").strip().lower()
    if nl_u in ("low", "medium", "high"):
        return nl_u
    return classify_noise_level_from_ratio(analysis.get("noise_ratio", 0.0)).lower()


def _harmonic_alignment_level(primary_hz: float, peaks_hz: list[float]) -> str:
    if primary_hz <= 0:
        return "not_applicable"
    secondaries = [
        float(f) for f in peaks_hz if float(f) > 0 and abs(float(f) - primary_hz) > 1e-6
    ]
    if not secondaries:
        return "not_applicable"

    harmonic_matches = 0
    for candidate in secondaries:
        is_match = any(
            abs(candidate - (primary_hz * n)) <= max(1.0, primary_hz * n * 0.03)
            for n in range(2, 7)
        )
        if is_match:
            harmonic_matches += 1

    ratio = harmonic_matches / max(1, len(secondaries))
    if ratio >= 0.66:
        return "strong"
    if ratio >= 0.33:
        return "partial"
    return "none"


def compute_unified_confidence(resonance_conf: float, analysis: dict) -> dict:
    """
    Deterministic confidence from FFT-derived analysis + resonance primary confidence.

    ``resonance_conf`` should be 0..1 (e.g. ``resonance_module["primary"]["confidence"]``).
    Strategy helpers still receive string factors ``noise_level``, ``cluster_strength``,
    ``peak_consistency``, ``harmonic_alignment`` (from peak geometry), plus ``reason``.
    """
    src = analysis if isinstance(analysis, dict) else {}
    peak_freqs = [float(x) for x in (src.get("peak_frequencies") or []) if float(x) > 0]
    peak_amps = [float(x) for x in (src.get("peak_amplitudes") or []) if float(x) > 0]
    primary_hz = float(src.get("peak_frequency", 0.0) or 0.0)

    noise_level = _resolved_noise_level_lowercase(src)
    if noise_level == "low":
        s_noise = 0.85
    elif noise_level == "medium":
        s_noise = 0.55
    else:
        s_noise = 0.25

    cluster_metric = 0.0
    if peak_amps:
        amp_max = max(peak_amps)
        amp_mean = sum(peak_amps) / len(peak_amps)
        cluster_metric = amp_max / (amp_mean + 1e-6)
    if cluster_metric >= 2.5:
        s_cluster = 0.85
        cluster_strength = "strong"
    elif cluster_metric >= 1.5:
        s_cluster = 0.55
        cluster_strength = "moderate"
    else:
        s_cluster = 0.25
        cluster_strength = "weak"

    if len(peak_amps) >= 2:
        top = sorted(peak_amps, reverse=True)[:3]
        consistency_ratio = top[0] / (sum(top) / len(top) + 1e-6)
        if consistency_ratio <= 1.4:
            s_consistency = 0.85
            peak_consistency = "high"
        elif consistency_ratio <= 2.0:
            s_consistency = 0.55
            peak_consistency = "medium"
        else:
            s_consistency = 0.30
            peak_consistency = "low"
    else:
        s_consistency = 0.5
        peak_consistency = "unknown"

    # Bandwidth confidence is intentionally deferred until a calibrated signal
    # bandwidth / spectral coverage metric exists. Do not score a placeholder.
    bandwidth = "deferred"

    harmonic_alignment = _harmonic_alignment_level(primary_hz, peak_freqs)
    if harmonic_alignment == "strong":
        s_harmonic = 0.85
    elif harmonic_alignment == "partial":
        s_harmonic = 0.65
    elif harmonic_alignment == "none":
        s_harmonic = 0.25
    else:
        s_harmonic = 1.0

    try:
        rc = float(resonance_conf)
    except (TypeError, ValueError):
        rc = 0.5
    if not (rc == rc):  # NaN
        rc = 0.5
    resonance_primary = _clamp01(rc)

    legacy_subscores = [s_noise, s_cluster, s_consistency, s_harmonic]
    legacy_score = sum(legacy_subscores) / len(legacy_subscores)
    subscores = [*legacy_subscores, resonance_primary]
    blended_score = sum(subscores) / len(subscores)
    score = round(max(0.0, min(1.0, min(legacy_score, blended_score))), 3)
    if score >= 0.67:
        level = "high"
    elif score >= 0.34:
        level = "medium"
    else:
        level = "low"

    reason = (
        f"Confidence from noise {noise_level}, clusters {cluster_strength}, "
        f"consistency {peak_consistency}, harmonics {harmonic_alignment}, "
        f"resonance_primary {round(resonance_primary, 3)}"
    )
    return {
        "score": score,
        "level": level,
        "reason": reason,
        "factors": {
            "noise_level": noise_level,
            "cluster_strength": cluster_strength,
            "peak_consistency": peak_consistency,
            "bandwidth": bandwidth,
            "harmonic_alignment": harmonic_alignment,
            "resonance_confidence": round(resonance_primary, 4),
        },
    }
