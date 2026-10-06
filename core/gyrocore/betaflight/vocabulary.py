"""
User-facing CLI status vocabulary — label/copy mapping only (no tuning behavior).
"""

from __future__ import annotations

from typing import Any, Mapping

UserFacingCliState = str


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _blocked_count(effective_intent: Mapping[str, Any]) -> int:
    blocked = effective_intent.get("blocked_style_adjustments")
    if isinstance(blocked, list):
        return len(blocked)
    details = effective_intent.get("blocked_style_adjustment_details")
    if isinstance(details, list):
        return len(details)
    return 0


def resolve_user_facing_cli_state(
    *,
    safety: Mapping[str, Any] | None,
    effective_intent: Mapping[str, Any] | None,
    top_level_status: str | None = None,
) -> dict[str, str]:
    safe = _as_dict(safety)
    eff = _as_dict(effective_intent)
    mech = _as_dict(safe.get("mechanical"))

    cli_actionable = safe.get("cli_actionable") is True
    paste_ready = cli_actionable
    hard_block = safe.get("hard_block") is True or safe.get("cli_availability") == "hard_block"
    diagnostic_only = safe.get("diagnostic_only") is True or safe.get("cli_availability") == "diagnostic_only"
    max_scale = _safe_float(eff.get("max_delta_scale_applied"))
    if max_scale is None:
        max_scale = 1.0
    mechanical_limited = mech.get("mechanical_limited") is True
    mechanical_caution = mech.get("mechanical_caution") is True
    blocked_count = _blocked_count(eff)
    top = str(top_level_status or safe.get("status") or "").strip().lower()

    if hard_block or (not cli_actionable and diagnostic_only):
        return {
            "user_facing_cli_state": "blocked",
            "user_facing_cli_badge": "Blocked",
            "user_facing_cli_copy": "Paste-ready CLI is withheld until safety checks allow it.",
            "cli_status_reason": "hard_block_or_diagnostic_only",
        }
    if not cli_actionable:
        return {
            "user_facing_cli_state": "diagnostic_only",
            "user_facing_cli_badge": "Diagnostic only",
            "user_facing_cli_copy": "Use this run as diagnostic guidance; paste-ready CLI is not available.",
            "cli_status_reason": "cli_not_actionable",
        }
    if max_scale < 0.999:
        return {
            "user_facing_cli_state": "delta_capped",
            "user_facing_cli_badge": "Capped CLI",
            "user_facing_cli_copy": "CLI is available with scaled safety deltas; apply in small steps and re-log.",
            "cli_status_reason": "max_delta_scale_applied_below_one",
        }
    if blocked_count > 0 and max_scale >= 0.999:
        return {
            "user_facing_cli_state": "style_limited",
            "user_facing_cli_badge": "Race intent partially limited",
            "user_facing_cli_copy": (
                "CLI is ready, but some race-style adjustments were held back by safety envelopes."
            ),
            "cli_status_reason": "style_adjustments_blocked_without_delta_cap",
        }
    if mechanical_caution and not mechanical_limited:
        copy = "CLI is ready with caution; review motor warning indicators before pushing harder."
        if top == "low_confidence":
            copy = (
                "Needs tuning — CLI ready. Confidence is medium-low; apply cautiously and re-log."
            )
        return {
            "user_facing_cli_state": "actionable_with_caution",
            "user_facing_cli_badge": "CLI ready · caution",
            "user_facing_cli_copy": copy,
            "cli_status_reason": "mechanical_caution_without_hard_limit",
        }
    if top == "low_confidence":
        return {
            "user_facing_cli_state": "actionable",
            "user_facing_cli_badge": "CLI ready",
            "user_facing_cli_copy": (
                "Needs tuning — CLI ready. Confidence is medium-low; apply cautiously and re-log."
            ),
            "cli_status_reason": "actionable_low_confidence",
        }
    return {
        "user_facing_cli_state": "actionable",
        "user_facing_cli_badge": "CLI ready",
        "user_facing_cli_copy": "Paste-ready CLI is available for this run.",
        "cli_status_reason": "actionable",
    }


def map_legacy_cli_status_label_to_user_facing(
    legacy_label: str | None,
    *,
    user_facing_state: str,
) -> str:
    """Map legacy intent labels to clearer user-facing ``cli_status_label`` values."""
    if user_facing_state == "blocked":
        return "blocked"
    if user_facing_state == "diagnostic_only":
        return "blocked"
    if user_facing_state == "delta_capped":
        return "delta_capped"
    if user_facing_state == "style_limited":
        return "style_limited"
    if user_facing_state == "actionable_with_caution":
        return "actionable_with_caution"
    legacy = str(legacy_label or "").strip().lower()
    if legacy in {"motor_safe_override", "filtering_override", "sharp_correction", "intent_preserved"}:
        return legacy
    return "actionable"


def enrich_cli_status_vocabulary(
    *,
    safety: Mapping[str, Any],
    effective_intent: Mapping[str, Any] | None = None,
    top_level_status: str | None = None,
) -> dict[str, Any]:
    """Return safety fields with backward-compatible and user-facing CLI labels."""
    safe = dict(safety)
    eff = _as_dict(effective_intent)
    legacy_label = str(safe.get("cli_status_label") or eff.get("cli_status_label") or "").strip() or None
    facing = resolve_user_facing_cli_state(
        safety=safe,
        effective_intent=eff,
        top_level_status=top_level_status,
    )
    new_label = map_legacy_cli_status_label_to_user_facing(
        legacy_label,
        user_facing_state=str(facing.get("user_facing_cli_state") or "actionable"),
    )
    safe["cli_status_label_old"] = legacy_label
    safe["cli_status_label"] = new_label
    safe.update(facing)
    return safe
