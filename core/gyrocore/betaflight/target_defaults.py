"""Betaflight target defaults service.

Provides `load_target_defaults()` for integration into build_board_overlay()
in effective_config_builder.py.

Target defaults in BF architecture:
    - Unified target configs contain hardware pin/resource assignments and
      hardware-specific set-commands (gyro align, serial providers, ESC params).
    - They do NOT contain per-target PID or filter numeric defaults.
    - Global PID/filter defaults are firmware-wide (see betaflight_firmware_defaults.py).
    - Therefore board_overlay for PID/filter will always be empty (no override).
    - The board_overlay_status will be "hardware_config_only" when a target is found,
      or "no_verified_overlay" when not found.

This service is NEVER used to emit paste-ready CLI values. It informs the
effective_config summary about board capabilities only.
"""

from __future__ import annotations

from typing import Any

from gyrocore.betaflight.data.betaflight_target_overlays import (
    get_target_database_summary,
    get_target_overlay,
)


def _base_result(status: str, notes: str) -> dict[str, Any]:
    coverage = get_target_database_summary()
    return {
        "pid_overlay": {},
        "filter_overlay": {},
        "hardware_config": None,
        "target_defaults_available": False,
        "pid_defaults_available": False,
        "filter_defaults_available": False,
        "board_overlay_status": status,
        "target_overlay_status": status,
        "target_defaults_verified": False,
        "target_match_status": status,
        "target_match_confidence": "none",
        "target_support_claim_scope": "firmware_only",
        "source": None,
        "verified": False,
        "warnings": ["target_overlay_unavailable", "board_defaults_unavailable_noop"],
        "notes": notes,
        "target_database": coverage,
    }


def load_target_defaults(board_metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load target-specific overlay data for a board.

    Args:
        board_metadata: Dict containing board info, expected keys:
            - board_name (str): e.g. "BETAFPVG473"
            - manufacturer_id (str): e.g. "BEFH"
            - Any other board context

    Returns:
        dict with keys:
            pid_overlay: dict — always empty (no per-target PIDs in BF)
            filter_overlay: dict — always empty (no per-target filters in BF)
            hardware_config: dict | None — hardware-specific info if target found
            target_defaults_available: bool
            pid_defaults_available: bool — always False
            filter_defaults_available: bool — always False
            board_overlay_status: str — one of:
                "no_board_metadata"       — no board_metadata provided
                "no_board_name"           — board_metadata missing board_name
                "no_verified_overlay"     — board_name not in target database
                "hardware_config_only"    — target found, hardware config present, no PID/filter overlay
            source: str | None
            verified: bool
            notes: str
    """
    if not board_metadata or not isinstance(board_metadata, dict):
        return _base_result("no_board_metadata", "No board_metadata provided.")

    board_name = board_metadata.get("board_name")
    if not board_name:
        return _base_result("no_board_name", "board_metadata provided but missing board_name key.")

    manufacturer_id = board_metadata.get("manufacturer_id")
    overlay = get_target_overlay(board_name, manufacturer_id=manufacturer_id)
    if overlay is None:
        return _base_result(
            "no_verified_overlay",
            f"Board {board_name!r} not found in target database.",
        )

    hw_cfg = overlay.get("hardware_config") or {}
    status = str(overlay.get("target_overlay_status") or "hardware_config_only")
    match_status = str(overlay.get("target_match_status") or "verified")
    match_confidence = str(overlay.get("target_match_confidence") or "medium")
    verified = bool(overlay.get("target_defaults_verified") and match_status == "verified")
    pid_defaults_available = bool(overlay.get("pid_defaults_available"))
    filter_defaults_available = bool(overlay.get("filter_defaults_available"))
    return {
        "pid_overlay": dict(overlay.get("pid_overlay") or {}),
        "filter_overlay": dict(overlay.get("filter_overlay") or {}),
        "hardware_config": hw_cfg,
        "target_defaults_available": overlay.get("target_defaults_available", False),
        "pid_defaults_available": pid_defaults_available,
        "filter_defaults_available": filter_defaults_available,
        "board_overlay_status": status,
        "target_overlay_status": status,
        "target_defaults_verified": verified,
        "target_match_status": match_status,
        "target_match_confidence": match_confidence,
        "target_support_claim_scope": "firmware_plus_target" if verified else "firmware_only",
        "source": overlay.get("overlay_source") or overlay.get("source_repo"),
        "verified": verified,
        "warnings": list(overlay.get("warnings") or []),
        "notes": overlay.get("notes", ""),
        "target_database": get_target_database_summary(),
    }


__all__ = ["load_target_defaults"]
