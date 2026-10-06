"""Backend support policy tied to effective-config confidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from gyrocore.betaflight.real_log_validation import resolve_real_log_validation_status


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if value is None:
        return []
    return [str(value)]


def resolve_support_matrix_policy(
    firmware_support: Mapping[str, Any] | None,
    effective_config_summary: Mapping[str, Any] | None,
    *,
    output_safety_passed: bool = True,
) -> dict[str, Any]:
    support = firmware_support if isinstance(firmware_support, Mapping) else {}
    summary = effective_config_summary if isinstance(effective_config_summary, Mapping) else {}
    displayed = str(support.get("support_level") or "unknown")
    engine_profile = support.get("engine_profile")
    defaults_profile = summary.get("defaults_profile_used")
    compatibility = bool(summary.get("compatibility_mode"))
    warnings = _as_list(support.get("warnings")) + _as_list(summary.get("warnings"))
    downgrade: list[str] = []
    provenance = summary.get("defaults_provenance")
    if isinstance(provenance, Mapping) and provenance.get("verified") is not True:
        source_label = str(provenance.get("source_label") or defaults_profile or "unknown")
        warnings.append(f"defaults_provenance_unverified:{source_label}")

    available = summary.get("effective_config_available") is True
    unknown_required = _as_list(summary.get("defaults_unknown_required_fields"))
    profile_conf = str(summary.get("active_profile_confidence") or "unknown")

    if displayed == "unknown" or support.get("cli_allowed") is not True:
        backend_level = "diagnostic_only"
        paste_ready = False
        if displayed == "unknown":
            downgrade.append("firmware_unknown")
    elif displayed == "diagnostic_only":
        backend_level = "diagnostic_only"
        paste_ready = False
    elif displayed == "limited":
        backend_level = "limited"
        paste_ready = bool(output_safety_passed and support.get("cli_allowed") is True)
        if not available:
            backend_level = "diagnostic_only"
            paste_ready = False
            downgrade.append("effective_config_unavailable")
    else:
        backend_level = "full"
        paste_ready = bool(output_safety_passed and support.get("cli_allowed") is True)
        if not available:
            backend_level = "diagnostic_only"
            paste_ready = False
            downgrade.append("effective_config_unavailable")
        elif unknown_required:
            backend_level = "limited"
            paste_ready = False
            downgrade.append("required_defaults_unknown")

    real_validation = resolve_real_log_validation_status(dict(summary))
    real_log_validation_status = str(real_validation.get("validation_status") or "not_run")
    real_validation_accepted_partial = bool(real_validation.get("accepted_partial"))
    real_validation_allows_proof = real_log_validation_status == "pass" or (
        real_log_validation_status == "partial" and real_validation_accepted_partial
    )

    if defaults_profile == "4.4" and backend_level == "full" and not real_validation_allows_proof:
        backend_level = "limited"
        downgrade.append("betaflight_4_4_defaults_not_full_effective")
    if compatibility:
        warnings.append("compatibility_mode_4_6_safe")
    if profile_conf == "ambiguous":
        if backend_level == "full":
            backend_level = "limited"
        downgrade.append("active_profile_ambiguous")
    elif profile_conf == "unknown":
        warnings.append("active_profile_unknown")

    # Missing board defaults are expected in Batch 1 and never hard-block.
    if summary.get("board_defaults_available") is not True:
        warnings.append("board_defaults_unavailable_noop")

    if backend_level == "diagnostic_only":
        support_level = "diagnostic_only"
    elif backend_level == "limited":
        support_level = "limited"
    else:
        support_level = "full"

    paste_ready_eligible = paste_ready and backend_level in {"full", "limited"}

    # --- Phase 3: Backend proof model fields ---
    defaults_verified = bool(
        isinstance(provenance, Mapping) and provenance.get("verified") is True
    )
    prov_source_type = str(
        provenance.get("source_type") if isinstance(provenance, Mapping) else "unavailable"
    ) or "unavailable"
    if prov_source_type == "audit_seed" and defaults_verified:
        defaults_provenance_status = "audit_seed"
    elif defaults_verified:
        defaults_provenance_status = "verified"
    elif prov_source_type in {"inherited", "compatibility_mode", "unavailable"}:
        defaults_provenance_status = prov_source_type
    else:
        defaults_provenance_status = "unavailable"

    # Profile isolation: read from effective_config_summary when cli_text wired (Phase 3B).
    # Falls back to "metadata_only" if not set (e.g., no cli_text supplied).
    profile_isolation_status = str(summary.get("profile_isolation_status") or "metadata_only")

    # Board overlay status: read from effective_config_summary (Phase 3B).
    board_overlay_status = str(summary.get("board_overlay_status") or "no_verified_overlay")

    # Target overlay status and verification (Phase 3B addition).
    target_overlay_status = str(summary.get("target_overlay_status") or "no_verified_overlay")
    target_defaults_verified = bool(summary.get("target_defaults_verified", False))
    target_match_status = str(summary.get("target_match_status") or target_overlay_status)
    target_match_confidence = str(summary.get("target_match_confidence") or "none")
    target_support_claim_scope = str(summary.get("target_support_claim_scope") or "firmware_only")
    target_database_status = str(summary.get("target_database_status") or "unavailable")
    target_database_source = summary.get("target_database_source")
    target_database_target_count = int(summary.get("target_database_target_count") or 0)
    target_database_verified_count = int(summary.get("target_database_verified_count") or 0)
    target_database_hardware_only_count = int(summary.get("target_database_hardware_only_count") or 0)
    target_database_numeric_defaults_count = int(summary.get("target_database_numeric_defaults_count") or 0)
    target_database_coverage_scope = summary.get("target_database_coverage_scope")
    board_numeric_defaults_proven = bool(
        summary.get("target_database_numeric_defaults_count")
        and target_defaults_verified
        and target_overlay_status == "numeric_defaults_available"
    )

    # Build blockers list — support_claim_proven is True only when ALL conditions met.
    blockers: list[str] = []
    if backend_level not in {"full", "limited"}:
        blockers.append("backend_level_not_full_or_limited")
    if not paste_ready_eligible:
        blockers.append("paste_ready_not_eligible")
    if not defaults_verified:
        blockers.append("defaults_not_verified")
    if isinstance(provenance, Mapping):
        blockers.extend(str(b) for b in provenance.get("blockers", []) if str(b).strip())
    if real_log_validation_status in {"not_run", "blocked_no_fixtures"}:
        blockers.append("real_log_validation_blocked_no_fixtures")
    elif real_log_validation_status == "fail":
        blockers.append("real_log_validation_failed")
    elif real_log_validation_status == "partial" and not real_validation_accepted_partial:
        blockers.append("real_log_validation_partial_not_accepted_for_scope")
    if profile_isolation_status == "ambiguous":
        blockers.append("profile_isolation_ambiguous")
    elif profile_isolation_status not in {"resolved", "single_profile"}:
        blockers.append("profile_isolation_not_resolved")
    if "firmware_unknown" in list(dict.fromkeys(downgrade)):
        blockers.append("firmware_unknown")
    if "effective_config_unavailable" in list(dict.fromkeys(downgrade)):
        blockers.append("effective_config_unavailable")
    if target_support_claim_scope == "firmware_plus_target":
        if not target_defaults_verified or target_match_status != "verified":
            blockers.append("target_proof_missing_or_unverified")
    elif target_match_status == "manufacturer_mismatch":
        blockers.append("target_manufacturer_mismatch")

    support_claim_proven = len(blockers) == 0

    return {
        "displayed_support_level": displayed,
        "backend_effective_support_level": backend_level,
        "support_level": support_level,
        "engine_profile_used": engine_profile,
        "defaults_profile_used": defaults_profile,
        "cli_profile_used": defaults_profile,
        "compatibility_mode": compatibility,
        "paste_ready_eligible": paste_ready_eligible,
        "support_matrix_warnings": list(dict.fromkeys(warnings)),
        "support_downgrade_reasons": list(dict.fromkeys(downgrade)),
        # Phase 3B proof model fields:
        "defaults_verified": defaults_verified,
        "defaults_provenance_status": defaults_provenance_status,
        "real_log_validation_status": real_log_validation_status,
        "real_log_validation_fixture_ids": list(real_validation.get("fixture_ids") or []),
        "real_log_validation_blockers": list(real_validation.get("blockers") or []),
        "real_log_validation_required_fixtures": list(real_validation.get("required_fixtures") or []),
        "real_log_validation_scope": real_validation.get("scope"),
        "profile_isolation_status": profile_isolation_status,
        "board_overlay_status": board_overlay_status,
        "target_overlay_status": target_overlay_status,
        "target_defaults_verified": target_defaults_verified,
        "target_database_status": target_database_status,
        "target_database_source": target_database_source,
        "target_database_target_count": target_database_target_count,
        "target_database_verified_count": target_database_verified_count,
        "target_database_hardware_only_count": target_database_hardware_only_count,
        "target_database_numeric_defaults_count": target_database_numeric_defaults_count,
        "target_database_coverage_scope": target_database_coverage_scope,
        "target_match_status": target_match_status,
        "target_match_confidence": target_match_confidence,
        "target_support_claim_scope": target_support_claim_scope,
        "support_claim_scope": target_support_claim_scope
        if target_support_claim_scope == "firmware_plus_target"
        else ("compatibility_mode" if compatibility else support_level),
        "board_numeric_defaults_proven": board_numeric_defaults_proven,
        "support_claim_proven": support_claim_proven,
        "support_claim_blockers": list(dict.fromkeys(blockers)),
    }


__all__ = ["resolve_support_matrix_policy"]
