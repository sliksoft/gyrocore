"""Consistency checks across uploaded CLI, BBL metadata, effective config, and RPM context."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested(mapping: Mapping[str, Any], *keys: str) -> Any:
    cur: Any = mapping
    for key in keys:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _bool_or_none(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in {"on", "true", "yes", "1", "enabled"}:
        return True
    if s in {"off", "false", "no", "0", "disabled"}:
        return False
    return None


def _positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def _add_unique(target: list[str], reason: str) -> None:
    if reason and reason not in target:
        target.append(reason)


def _status_from_reasons(
    hard_block_reasons: list[str],
    diagnostic_reasons: list[str],
    limited_reasons: list[str],
    warnings: list[str],
) -> str:
    if hard_block_reasons:
        return "hard_block"
    if diagnostic_reasons:
        return "diagnostic_only"
    if limited_reasons:
        return "limited"
    if warnings:
        return "warning"
    return "ok"


def validate_config_log_consistency(
    *,
    parsed_cli_baseline_config: Mapping[str, Any] | None = None,
    effective_baseline_config: Mapping[str, Any] | None = None,
    effective_config_summary: Mapping[str, Any] | None = None,
    effective_config_evidence: Mapping[str, Any] | None = None,
    firmware_support: Mapping[str, Any] | None = None,
    bbl_metadata: Mapping[str, Any] | None = None,
    analysis_metrics: Mapping[str, Any] | None = None,
    hardware_user_inputs: Mapping[str, Any] | None = None,
    rpm_dshot_health: Mapping[str, Any] | None = None,
    erpm_analysis: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return structured consistency status without raising.

    The validator intentionally downgrades confidence for metadata/config
    mismatches. Hard-block remains reserved for existing danger gates.
    """
    parsed = _as_mapping(parsed_cli_baseline_config)
    effective = _as_mapping(effective_baseline_config)
    summary = _as_mapping(effective_config_summary)
    evidence = _as_mapping(effective_config_evidence)
    support = _as_mapping(firmware_support)
    bbl = _as_mapping(bbl_metadata)
    analysis = _as_mapping(analysis_metrics)
    user = _as_mapping(hardware_user_inputs)
    rpm = _as_mapping(rpm_dshot_health)
    erpm = _as_mapping(erpm_analysis)
    filters = _as_mapping(parsed.get("filters"))
    meta = _as_mapping(parsed.get("meta"))
    eff_meta = _as_mapping(effective.get("meta"))

    warnings: list[str] = []
    limited_reasons: list[str] = []
    diagnostic_reasons: list[str] = []
    hard_block_reasons: list[str] = []
    confidence_penalty = 0.0
    rpm_confidence_penalty = 0.0

    cli_fw = meta.get("firmware_version") or eff_meta.get("firmware_version")
    bbl_fw = (
        bbl.get("firmware_version")
        or bbl.get("version")
        or bbl.get("firmware_revision")
        or analysis.get("betaflight_version")
    )
    firmware_consistency = "unknown"
    if (support.get("support_level") == "unknown") or (support.get("cli_allowed") is False and not support.get("engine_profile")):
        _add_unique(diagnostic_reasons, "firmware_unknown")
        firmware_consistency = "unknown"
        confidence_penalty = max(confidence_penalty, 0.8)
    elif cli_fw and bbl_fw and _norm(cli_fw) != _norm(bbl_fw):
        _add_unique(limited_reasons, "firmware_version_mismatch")
        firmware_consistency = "mismatch"
        confidence_penalty = max(confidence_penalty, 0.35)
    else:
        firmware_consistency = "ok" if (cli_fw or bbl_fw or support.get("engine_profile")) else "unknown"

    engine_profile = support.get("engine_profile")
    defaults_profile = summary.get("defaults_profile_used")
    if engine_profile and defaults_profile:
        engine_s = str(engine_profile)
        defaults_s = str(defaults_profile)
        compatible = (
            defaults_s == engine_s
            or defaults_s == "4.6-safe"
            and (engine_s == "4.6" or bool(summary.get("compatibility_mode")))
            or defaults_s == "4.3-limited"
            and engine_s == "4.4"
        )
        if not compatible:
            _add_unique(limited_reasons, "engine_defaults_profile_mismatch")
            confidence_penalty = max(confidence_penalty, 0.25)
    if summary.get("compatibility_mode") is True:
        _add_unique(warnings, "compatibility_mode_4_6_safe")

    board_consistency = "unknown"
    cli_board = meta.get("board_name") or eff_meta.get("board_name")
    bbl_board = bbl.get("board_name") or bbl.get("board") or bbl.get("target")
    if cli_board and bbl_board and _norm(cli_board) != _norm(bbl_board):
        _add_unique(warnings, "board_name_mismatch")
        board_consistency = "mismatch"
        confidence_penalty = max(confidence_penalty, 0.15)
    elif cli_board or bbl_board:
        board_consistency = "ok"
    else:
        _add_unique(warnings, "board_metadata_missing")

    cli_manufacturer = meta.get("manufacturer_id") or eff_meta.get("manufacturer_id")
    bbl_manufacturer = bbl.get("manufacturer_id")
    if cli_manufacturer and bbl_manufacturer and _norm(cli_manufacturer) != _norm(bbl_manufacturer):
        _add_unique(warnings, "manufacturer_id_mismatch")
        confidence_penalty = max(confidence_penalty, 0.15)
    if summary.get("board_defaults_available") is not True:
        _add_unique(warnings, "board_defaults_unavailable_noop")

    profile_conf = str(summary.get("active_profile_confidence") or "unknown")
    rateprofile_conf = str(summary.get("active_rateprofile_confidence") or "unknown")
    if profile_conf == "ambiguous":
        _add_unique(limited_reasons, "active_profile_ambiguous")
        confidence_penalty = max(confidence_penalty, 0.35)
    elif profile_conf == "unknown":
        _add_unique(warnings, "active_profile_unknown")
        confidence_penalty = max(confidence_penalty, 0.1)
    if rateprofile_conf == "ambiguous":
        _add_unique(limited_reasons, "active_rateprofile_ambiguous")
        confidence_penalty = max(confidence_penalty, 0.25)

    bbl_profile = bbl.get("active_profile") or bbl.get("pid_profile") or bbl.get("profile")
    eff_profile = eff_meta.get("active_profile")
    if bbl_profile is not None and eff_profile is not None and str(bbl_profile) != str(eff_profile):
        _add_unique(limited_reasons, "active_profile_mismatch")
        confidence_penalty = max(confidence_penalty, 0.35)
    bbl_rateprofile = bbl.get("active_rateprofile") or bbl.get("rate_profile") or bbl.get("rateprofile")
    eff_rateprofile = eff_meta.get("active_rateprofile")
    if bbl_rateprofile is not None and eff_rateprofile is not None and str(bbl_rateprofile) != str(eff_rateprofile):
        _add_unique(limited_reasons, "active_rateprofile_mismatch")
        confidence_penalty = max(confidence_penalty, 0.25)

    dshot_bidir = _bool_or_none(filters.get("dshot_bidir"))
    rpm_filter = _bool_or_none(filters.get("rpm_filter"))
    motor_pwm_protocol = _norm(filters.get("motor_pwm_protocol"))
    motor_poles_cli = _positive_int(filters.get("motor_poles"))
    user_hw = _as_mapping(user.get("hardware"))
    motor_poles_user = _positive_int(user_hw.get("motor_poles") if user_hw else user.get("motor_poles"))
    telemetry_present = bool(
        rpm.get("rpm_telemetry_present") is True
        or erpm.get("rpm_telemetry_present") is True
        or erpm.get("erpm_sample_coverage")
        or erpm.get("motor_frequencies_hz")
        or erpm.get("harmonics_hz")
        or erpm.get("dominant_frequency")
    )
    rpm_consistency = "ok"
    if dshot_bidir is True and not telemetry_present:
        _add_unique(limited_reasons, "dshot_bidir_on_but_no_rpm_telemetry")
        rpm_confidence_penalty = max(rpm_confidence_penalty, 0.55)
        rpm_consistency = "weak"
    if telemetry_present and dshot_bidir is not True:
        _add_unique(warnings, "rpm_telemetry_present_but_dshot_bidir_not_confirmed")
        rpm_confidence_penalty = max(rpm_confidence_penalty, 0.3)
        rpm_consistency = "warning" if rpm_consistency == "ok" else rpm_consistency
    if motor_poles_cli is None:
        _add_unique(limited_reasons, "motor_poles_missing_or_uncertain_for_rpm")
        rpm_confidence_penalty = max(rpm_confidence_penalty, 0.45)
        rpm_consistency = "weak"
    elif motor_poles_user is not None and motor_poles_user != motor_poles_cli:
        _add_unique(warnings, "motor_poles_user_mismatch_cli_authority_used")
        rpm_confidence_penalty = max(rpm_confidence_penalty, 0.15)
    if motor_pwm_protocol and "dshot" not in motor_pwm_protocol:
        _add_unique(warnings, "motor_pwm_protocol_not_dshot_for_rpm")
        rpm_confidence_penalty = max(rpm_confidence_penalty, 0.35)
        rpm_consistency = "warning" if rpm_consistency == "ok" else rpm_consistency
    if str(erpm.get("erpm_scale_assumption") or "").strip().lower() in {"ambiguous", "unknown", "conflicting"}:
        _add_unique(limited_reasons, "erpm_scale_ambiguous")
        rpm_confidence_penalty = max(rpm_confidence_penalty, 0.45)
        rpm_consistency = "ambiguous"
    if str(rpm.get("status") or "").strip().lower() in {"uncertain", "weak"}:
        rpm_confidence_penalty = max(rpm_confidence_penalty, 0.25)
        if rpm_consistency == "ok":
            rpm_consistency = "warning"
    if rpm_filter is False and telemetry_present:
        _add_unique(warnings, "rpm_telemetry_present_but_rpm_filter_disabled")

    esc = _as_mapping(user.get("esc") or user_hw.get("esc") if user_hw else user.get("esc"))
    esc_fw = _norm(esc.get("firmware"))
    pwm_freq = _norm(esc.get("pwm_frequency") or esc.get("pwm_frequency_khz"))
    if esc_fw == "bluejay" and "96" in pwm_freq:
        _add_unique(warnings, "bluejay_96khz_context_only")
    if esc.get("power_rating") or esc.get("esc_power_rating"):
        _add_unique(warnings, "esc_power_rating_context_only")

    if summary.get("effective_config_available") is False:
        _add_unique(diagnostic_reasons, "effective_config_unavailable")
        confidence_penalty = max(confidence_penalty, 0.7)
    if not defaults_profile:
        _add_unique(diagnostic_reasons, "defaults_profile_unavailable")
        confidence_penalty = max(confidence_penalty, 0.7)
    if summary.get("defaults_unknown_required_fields"):
        _add_unique(limited_reasons, "required_defaults_unknown")
        confidence_penalty = max(confidence_penalty, 0.4)
    if not parsed:
        _add_unique(diagnostic_reasons, "cli_baseline_authority_missing")
        confidence_penalty = max(confidence_penalty, 0.8)
    default_evidence_paths = [
        path
        for path, item in evidence.items()
        if isinstance(item, Mapping) and item.get("source") == "betaflight_default"
    ]

    status = _status_from_reasons(
        hard_block_reasons,
        diagnostic_reasons,
        limited_reasons,
        warnings,
    )
    return {
        "status": status,
        "warnings": warnings,
        "limited_reasons": limited_reasons,
        "diagnostic_reasons": diagnostic_reasons,
        "hard_block_reasons": hard_block_reasons,
        "confidence_penalty": round(max(0.0, min(1.0, confidence_penalty)), 4),
        "rpm_confidence_penalty": round(max(0.0, min(1.0, rpm_confidence_penalty)), 4),
        "profile_confidence": profile_conf,
        "rateprofile_confidence": rateprofile_conf,
        "firmware_consistency": firmware_consistency,
        "board_consistency": board_consistency,
        "rpm_consistency": rpm_consistency,
        "summary": {
            "defaults_profile_used": defaults_profile,
            "engine_profile_used": engine_profile,
            "compatibility_mode": bool(summary.get("compatibility_mode")),
            "default_derived_field_count": len(default_evidence_paths),
            "dshot_bidir": dshot_bidir,
            "rpm_filter_enabled": rpm_filter,
            "rpm_telemetry_present": telemetry_present,
            "motor_poles_cli": motor_poles_cli,
            "motor_poles_user": motor_poles_user,
            "motor_pwm_protocol": filters.get("motor_pwm_protocol"),
        },
    }


__all__ = ["validate_config_log_consistency"]
