"""Build an internal effective Betaflight baseline with source evidence."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from gyrocore.betaflight.defaults import load_betaflight_defaults
from gyrocore.betaflight.target_defaults import load_target_defaults
from gyrocore.betaflight.cli_profile import parse_cli_profile_blocks

SOURCE_CLI_DUMP = "cli_dump"
SOURCE_BETAFLIGHT_DEFAULT = "betaflight_default"
SOURCE_METADATA = "metadata"
SOURCE_BLACKBOX_HEADER = "blackbox_header"
SOURCE_USER_INPUT = "user_input"
SOURCE_UNKNOWN = "unknown"
SOURCE_CONTEXT_ONLY = "context_only"
SOURCE_UNSUPPORTED = "unsupported"
SOURCE_BOARD_DEFAULT = "board_default"


def _field_paths(config: Mapping[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    out: list[tuple[str, Any]] = []
    for key, value in config.items():
        if key.startswith("_"):
            continue
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping):
            out.extend(_field_paths(value, path))
        else:
            out.append((path, value))
    return out


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = root
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _overlay_mapping(
    target: dict[str, Any],
    source: Mapping[str, Any],
    evidence: dict[str, dict[str, Any]],
    *,
    source_label: str,
    confidence: float,
) -> None:
    for path, value in _field_paths(source):
        _set_path(target, path, copy.deepcopy(value))
        evidence[path] = {
            "source": source_label,
            "confidence": confidence,
        }


def build_board_overlay(
    board_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Board overlay hook wired to betaflight_target_defaults.

    Loads target-specific hardware config from betaflight/unified-targets.
    BF unified targets do not contain PID or filter numeric defaults, so
    pid/filter overlays are always empty. board_overlay_status will be
    "hardware_config_only" when a known target is found, otherwise "no_verified_overlay".
    """
    board_meta_dict: dict[str, Any] = (
        dict(board_metadata) if isinstance(board_metadata, Mapping) else {}
    )
    target_result = load_target_defaults(board_meta_dict if board_meta_dict else None)
    return {
        "filters": dict(target_result.get("filter_overlay") or {}),
        "pid": dict(target_result.get("pid_overlay") or {}),
        "d_min": {},
        "meta": dict(target_result.get("hardware_config") or {}),
        "_board_overlay_meta": {
            "status": target_result.get("board_overlay_status", "no_verified_overlay"),
            "source": target_result.get("source"),
            "verified": target_result.get("verified", False),
            "target_defaults_available": target_result.get("target_defaults_available", False),
            "target_defaults_verified": target_result.get("target_defaults_verified", False),
            "pid_defaults_available": target_result.get("pid_defaults_available", False),
            "filter_defaults_available": target_result.get("filter_defaults_available", False),
            "target_match_status": target_result.get("target_match_status", "no_verified_overlay"),
            "target_match_confidence": target_result.get("target_match_confidence", "none"),
            "target_support_claim_scope": target_result.get("target_support_claim_scope", "firmware_only"),
            "target_database": dict(target_result.get("target_database") or {}),
            "hardware_config": dict(target_result.get("hardware_config") or {}),
            "warnings": list(target_result.get("warnings") or [])
            or (["board_defaults_unavailable_noop"] if not target_result.get("target_defaults_available") else []),
        },
    }


def build_effective_config(
    parsed_cli_config: Mapping[str, Any] | None,
    *,
    firmware_support: Mapping[str, Any] | None = None,
    board_metadata: Mapping[str, Any] | None = None,
    profile_context: Mapping[str, Any] | None = None,
    bbl_metadata: Mapping[str, Any] | None = None,
    user_inputs: Mapping[str, Any] | None = None,
    cli_text: str | None = None,
) -> dict[str, Any]:
    """Build effective baseline config, evidence, and summary.

    The returned effective config is internal context. The explicit parsed CLI
    baseline remains the paste-ready CLI emission baseline.

    Args:
        parsed_cli_config: Already-parsed CLI config dict (from GyroCore parser).
        firmware_support: Firmware support metadata from support matrix.
        board_metadata: Board hardware metadata.
        profile_context: Profile context from CLI profile resolver.
        bbl_metadata: Blackbox log header metadata.
        user_inputs: User-provided context (frame size, hardware class, etc.).
        cli_text: Raw ``diff all`` CLI dump text. When provided, wires
            ``parse_cli_profile_blocks`` for profile isolation analysis.
    """
    parsed = parsed_cli_config if isinstance(parsed_cli_config, Mapping) else {}
    evidence: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    fallback_reason: str | None = None
    effective: dict[str, Any] = {"filters": {}, "pid": {}, "d_min": {}, "meta": {}}

    # Wire profile isolation from raw cli_text when provided.
    # parse_cli_profile_blocks returns profile_confidence, rateprofile_confidence,
    # active_pid_profile, active_rateprofile, warnings, etc.
    cli_profile_blocks: dict[str, Any] | None = None
    profile_isolation_status: str = "metadata_only"
    if cli_text and isinstance(cli_text, str) and cli_text.strip():
        try:
            cli_profile_blocks = parse_cli_profile_blocks(cli_text)
        except Exception:  # pragma: no cover — defensive; resolver should never raise
            cli_profile_blocks = None
            warnings.append("profile_isolation_parse_failed")
        if cli_profile_blocks is not None:
            _pid_profiles = cli_profile_blocks.get("pid_profiles") or {}
            _profile_conf = cli_profile_blocks.get("profile_confidence", "unknown")
            _rate_conf = cli_profile_blocks.get("rateprofile_confidence", "unknown")
            block_warnings = cli_profile_blocks.get("warnings") or []
            warnings.extend(str(w) for w in block_warnings if str(w).strip())
            if len(_pid_profiles) == 1 and _profile_conf == "high":
                profile_isolation_status = "single_profile"
            elif _profile_conf == "high":
                profile_isolation_status = "resolved"
            elif _profile_conf in ("ambiguous",):
                profile_isolation_status = "ambiguous"
                warnings.append("profile_isolation_ambiguous")
            else:
                profile_isolation_status = "ambiguous"
                warnings.append("profile_isolation_low_confidence")

    defaults_payload = load_betaflight_defaults(firmware_support)
    defaults_meta = defaults_payload["metadata"]
    if defaults_meta.get("defaults_available") is True:
        _overlay_mapping(
            effective,
            defaults_payload["defaults"],
            evidence,
            source_label=SOURCE_BETAFLIGHT_DEFAULT,
            confidence=0.9,
        )
    else:
        fallback_reason = str(defaults_meta.get("fallback_reason") or "defaults_unavailable")
        warnings.append(fallback_reason)

    board_overlay = build_board_overlay(board_metadata)
    board_overlay_meta = board_overlay.get("_board_overlay_meta") or {}
    board_defaults_available = any(
        isinstance(board_overlay.get(section), Mapping) and bool(board_overlay.get(section))
        for section in ("filters", "pid", "d_min")
    )
    if board_defaults_available:
        _overlay_mapping(
            effective,
            board_overlay,
            evidence,
            source_label=SOURCE_BOARD_DEFAULT,
            confidence=0.9,
        )

    _overlay_mapping(
        effective,
        {
            key: value
            for key, value in parsed.items()
            if key in {"filters", "pid", "d_min", "meta"}
        },
        evidence,
        source_label=SOURCE_CLI_DUMP,
        confidence=1.0,
    )

    board_meta = board_metadata if isinstance(board_metadata, Mapping) else {}
    bbl_meta = bbl_metadata if isinstance(bbl_metadata, Mapping) else {}
    user_meta = user_inputs if isinstance(user_inputs, Mapping) else {}
    metadata_values: dict[str, Any] = {}
    for key in ("board_name", "board", "target", "manufacturer_id", "mcu_id"):
        if board_meta.get(key) is not None:
            metadata_values[key] = board_meta.get(key)
        elif bbl_meta.get(key) is not None:
            metadata_values[key] = bbl_meta.get(key)
    for key in ("hardware_class", "frame_size", "frame"):
        if user_meta.get(key) is not None:
            metadata_values[key] = user_meta.get(key)
    for key, value in metadata_values.items():
        effective.setdefault("meta", {})[key] = value
        if key in board_meta:
            src = SOURCE_METADATA
        elif key in bbl_meta:
            src = SOURCE_BLACKBOX_HEADER
        else:
            src = SOURCE_USER_INPUT
        evidence[f"meta.{key}"] = {"source": src, "confidence": 1.0}

    profile = profile_context if isinstance(profile_context, Mapping) else {}
    for key in (
        "active_profile",
        "active_rateprofile",
        "active_profile_confidence",
        "active_rateprofile_confidence",
    ):
        if profile.get(key) is not None:
            effective.setdefault("meta", {})[key] = profile.get(key)
            evidence[f"meta.{key}"] = {"source": SOURCE_METADATA, "confidence": 1.0}

    profile_warnings = profile.get("warnings") if isinstance(profile.get("warnings"), list) else []
    warnings.extend(str(w) for w in profile_warnings if str(w).strip())
    warnings.extend(str(w) for w in defaults_meta.get("warnings", []) if str(w).strip())

    # Determine active profile confidence from cli_profile_blocks if available,
    # falling back to profile_context.
    if cli_profile_blocks is not None:
        active_profile_conf = cli_profile_blocks.get("profile_confidence", "unknown")
        active_rateprofile_conf = cli_profile_blocks.get("rateprofile_confidence", "unknown")
    else:
        active_profile_conf = profile.get("active_profile_confidence", "unknown")
        active_rateprofile_conf = profile.get("active_rateprofile_confidence", "unknown")

    summary = {
        "effective_config_available": bool(defaults_meta.get("defaults_available")),
        "defaults_profile_used": defaults_meta.get("defaults_profile_used"),
        "firmware_coverage": copy.deepcopy(defaults_meta.get("firmware_coverage") or {}),
        "defaults_known_fields_count": defaults_meta.get("known_fields_count", 0),
        "defaults_unknown_required_fields": list(defaults_meta.get("unknown_required_fields") or []),
        "defaults_provenance": copy.deepcopy(defaults_meta.get("provenance") or {}),
        "active_profile_confidence": active_profile_conf,
        "active_rateprofile_confidence": active_rateprofile_conf,
        "board_defaults_available": board_defaults_available,
        "compatibility_mode": bool(defaults_meta.get("compatibility_mode")),
        "warnings": list(dict.fromkeys(warnings)),
        "fallback_reason": fallback_reason,
        # Profile isolation status — updated from "metadata_only" when cli_text provided
        "profile_isolation_status": profile_isolation_status,
        # Board overlay status — wired to target defaults (Phase 3B)
        "board_overlay_status": str(board_overlay_meta.get("status") or "no_verified_overlay"),
        "board_overlay_source": board_overlay_meta.get("source"),
        "board_overlay_verified": bool(board_overlay_meta.get("verified", False)),
        "board_overlay_warnings": list(board_overlay_meta.get("warnings") or ["board_defaults_unavailable_noop"]),
        "target_overlay_status": str(board_overlay_meta.get("status") or "no_verified_overlay"),
        "target_defaults_verified": bool(board_overlay_meta.get("target_defaults_verified", False)),
        "target_match_status": str(board_overlay_meta.get("target_match_status") or "no_verified_overlay"),
        "target_match_confidence": str(board_overlay_meta.get("target_match_confidence") or "none"),
        "target_support_claim_scope": str(board_overlay_meta.get("target_support_claim_scope") or "firmware_only"),
        "target_database_status": "available" if board_overlay_meta.get("target_database") else "unavailable",
        "target_database_source": (board_overlay_meta.get("target_database") or {}).get("coverage_scope"),
        "target_database_target_count": int((board_overlay_meta.get("target_database") or {}).get("targets_parsed") or 0),
        "target_database_verified_count": int((board_overlay_meta.get("target_database") or {}).get("verified_count") or 0),
        "target_database_hardware_only_count": int((board_overlay_meta.get("target_database") or {}).get("hardware_only_count") or 0),
        "target_database_numeric_defaults_count": int((board_overlay_meta.get("target_database") or {}).get("numeric_defaults_count") or 0),
        "target_database_coverage_scope": (board_overlay_meta.get("target_database") or {}).get("coverage_scope"),
    }
    if not summary["effective_config_available"] and fallback_reason is None:
        summary["fallback_reason"] = "effective_config_unavailable"

    return {
        "effective_baseline_config": effective,
        "source_evidence": evidence,
        "effective_config_summary": summary,
    }


__all__ = [
    "SOURCE_BETAFLIGHT_DEFAULT",
    "SOURCE_CLI_DUMP",
    "SOURCE_CONTEXT_ONLY",
    "SOURCE_METADATA",
    "SOURCE_UNKNOWN",
    "SOURCE_UNSUPPORTED",
    "build_board_overlay",
    "build_effective_config",
    "build_effective_config",
]
