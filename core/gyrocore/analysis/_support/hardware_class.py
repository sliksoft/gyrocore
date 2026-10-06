# GyroCore WU4: adapted from AeroTuner backend/services/hardware_class.py
"""Canonical hardware class values for analyze hardware/profile contracts."""

from __future__ import annotations

from typing import Any

HARDWARE_CLASS_VALUES = frozenset(
    {
        "whoop_1s",
        "whoop_2s",
        "micro_2_5_3_5",
        "freestyle_5",
        "racing_5",
        "long_range_7",
        "long_range_10_large",
        "cine_heavy",
    }
)

RPM_POLICY_HARDWARE_CLASSES = frozenset(
    {
        "whoop_1s",
        "small_whoop_2s",
        "toothpick_2_3_5_inch",
        "standard_5_inch",
        "freestyle_6_inch",
        "long_range_7_inch",
        "heavy_long_range_10_inch",
        "cinewhoop_ducted",
        "xclass_large_prop",
        "unknown",
    }
)

LEGACY_HARDWARE_CLASS_TO_RPM_POLICY: dict[str, str] = {
    "tinywhoop": "whoop_1s",
    "freestyle_5": "standard_5_inch",
    "racing_5": "standard_5_inch",
    "long_range_7": "long_range_7_inch",
    "long_range_10_large": "heavy_long_range_10_inch",
    "cine_heavy": "cinewhoop_ducted",
    "whoop_2s": "small_whoop_2s",
    "micro_2_5_3_5": "toothpick_2_3_5_inch",
    "racing_5_inch": "standard_5_inch",
    "freestyle_5_inch": "standard_5_inch",
    "large_prop_10_inch": "heavy_long_range_10_inch",
    "heavy_lift": "heavy_long_range_10_inch",
    "cinematic_large_prop": "cinewhoop_ducted",
    "large_prop_10": "heavy_long_range_10_inch",
    "heavy_10_inch": "heavy_long_range_10_inch",
    "heavy_10": "heavy_long_range_10_inch",
    "cinewhoop": "cinewhoop_ducted",
    "xclass_large": "xclass_large_prop",
    "freestyle_6_inch": "freestyle_6_inch",
}


def normalize_hardware_class(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if value in HARDWARE_CLASS_VALUES:
        return value
    return None


def resolve_rpm_policy_hardware_class(raw: Any) -> str:
    """Map stored hardware class to explicit RPM policy registry key."""
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in LEGACY_HARDWARE_CLASS_TO_RPM_POLICY:
            return LEGACY_HARDWARE_CLASS_TO_RPM_POLICY[value]
        if value in RPM_POLICY_HARDWARE_CLASSES:
            return value
        normalized = normalize_hardware_class(value)
        if normalized in LEGACY_HARDWARE_CLASS_TO_RPM_POLICY:
            return LEGACY_HARDWARE_CLASS_TO_RPM_POLICY[normalized]
        if normalized in RPM_POLICY_HARDWARE_CLASSES:
            return normalized
    return "unknown"
