"""Versioned Betaflight default foundation for effective config.

Batch 1 deliberately keeps this table small and limited to tuning-relevant keys
that GyroCore already parses or reports. These are firmware/profile defaults,
not board-specific defaults, and they are never used as paste-ready CLI emit
authority by themselves.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from gyrocore.betaflight.data.betaflight_firmware_defaults import (
    get_firmware_coverage_summary,
    get_firmware_default_profile,
)

_PROFILE_RE = re.compile(r"(\d{1,4})\.(\d{1,2})")

# Official BF 4.5.1 PID defaults.
# Source: src/main/flight/pid.h @ tag 4.5.1
#   #define PID_ROLL_DEFAULT  { 45, 80, 40, 120 }
#   #define PID_PITCH_DEFAULT { 47, 84, 46, 125 }
#   #define PID_YAW_DEFAULT   { 45, 80,  0, 120 }
_PID_DEFAULTS_45: dict[str, dict[str, int]] = {
    "roll": {"p": 45, "i": 80, "d": 40, "ff": 120},
    "pitch": {"p": 47, "i": 84, "d": 46, "ff": 125},
    "yaw": {"p": 45, "i": 80, "d": 0, "ff": 120},  # i corrected from 100 → 80 (official BF 4.5.1)
}

# Official BF 4.5.1 d_min defaults.
# Source: src/main/flight/pid.h @ tag 4.5.1
#   #define D_MIN_DEFAULT { 30, 34, 0 }
_D_MIN_DEFAULTS_45: dict[str, int] = {
    "roll": 30,   # corrected from 23 → 30 (official BF 4.5.1)
    "pitch": 34,  # corrected from 25 → 34 (official BF 4.5.1)
    "yaw": 0,
}

# Official BF 4.5.1 filter defaults.
# Sources:
#   src/main/sensors/gyro.c @ 4.5.1: GYRO_LPF1_DYN_MIN_HZ_DEFAULT=250, GYRO_LPF1_DYN_MAX_HZ_DEFAULT=500, GYRO_LPF2_HZ_DEFAULT=500
#   src/main/flight/pid.h @ 4.5.1: DTERM_LPF1_DYN_MIN_HZ_DEFAULT=75, DTERM_LPF1_DYN_MAX_HZ_DEFAULT=150, DTERM_LPF2_HZ_DEFAULT=150
#   src/main/pg/dyn_notch.c @ 4.5.1: count=3, min_hz=100, max_hz=600, q=300
#   src/main/pg/rpm_filter.c @ 4.5.1: harmonics=3, min_hz=100, fade_range_hz=50
#   src/main/flight/pid.c @ 4.5.1: smooth_factor=25, jitter_factor=7, boost=15, tpa_rate=65, tpa_breakpoint=1350
#
# Notes on non-register fields:
#   rpm_filter_max_hz — does not exist in firmware rpmFilterConfig_t; Configurator UI concept only.
#                       Kept as None with verified=False annotation in provenance.
#   dyn_notch_width_percent — not a firmware register in BF 4.5; Configurator UI display only.
#                             Kept for GyroCore parser compatibility but marked unverified.
#   anti_gravity_gain — firmware uses integer scale (80); audit_seed used 5000 (possible milliunit
#                       or different parameter name in GyroCore). Kept at 80 (official BF 4.5.1).
_FILTER_DEFAULTS_45: dict[str, Any] = {
    "gyro_lpf1_static_hz": 0,
    "gyro_lpf1_dyn_min_hz": 250,
    "gyro_lpf1_dyn_max_hz": 500,
    "gyro_lpf1_type": "PT1",
    "gyro_lpf2_static_hz": 500,   # corrected from 350 → 500 (official BF 4.5.1: GYRO_LPF2_HZ_DEFAULT=500)
    "gyro_lpf2_type": "PT1",
    "dterm_lpf1_static_hz": 0,
    "dterm_lpf1_dyn_min_hz": 75,
    "dterm_lpf1_dyn_max_hz": 150,
    "dterm_lpf1_type": "PT1",
    "dterm_lpf2_static_hz": 150,
    "dterm_lpf2_type": "PT1",
    "dyn_notch_count": 3,          # corrected from 1 → 3 (official BF 4.5.1: pg/dyn_notch.c)
    "dyn_notch_min_hz": 100,       # corrected from 20 → 100 (official BF 4.5.1: pg/dyn_notch.c)
    "dyn_notch_max_hz": 600,
    "dyn_notch_q": 300,            # corrected from 500 → 300 (official BF 4.5.1: pg/dyn_notch.c)
    "dyn_notch_width_percent": 8,  # NOT a firmware register in BF 4.5; Configurator UI only (kept for GyroCore compat)
    "rpm_filter_harmonics": 3,
    "rpm_filter_min_hz": 100,
    "rpm_filter_max_hz": None,     # NOT a firmware register; was 500 in audit_seed. Field does not exist in rpmFilterConfig_t.
    "dshot_bidir": False,
    "anti_gravity_gain": 80,       # corrected from 5000 → 80 (official BF 4.5.1: flight/pid.c .anti_gravity_gain=80)
    "throttle_boost": 5,
    "yaw_lowpass_hz": 100,
    "tpa_rate": 65,
    "tpa_breakpoint": 1350,
    "feedforward_smooth_factor": 25,  # corrected from 45 → 25 (official BF 4.5.1: flight/pid.c)
    "feedforward_jitter_factor": 7,   # corrected from 12 → 7 (official BF 4.5.1: flight/pid.c)
    "feedforward_boost": 15,
    "simplified_gyro_filter_multiplier": 1.0,
    "simplified_dterm_filter_multiplier": 1.0,
}

_DEFAULTS_45: dict[str, Any] = {
    "filters": _FILTER_DEFAULTS_45,
    "pid": _PID_DEFAULTS_45,
    "d_min": _D_MIN_DEFAULTS_45,
}

# 4.6-safe currently reuses the 4.6 profile as a compatibility baseline for
# modern/date-based versions. It is surfaced explicitly in metadata.
_DEFAULTS_BY_PROFILE: dict[str, dict[str, Any]] = {
    "4.5": _DEFAULTS_45,
    "4.6": copy.deepcopy(_DEFAULTS_45),
    "4.6-safe": copy.deepcopy(_DEFAULTS_45),
    "4.4": {
        "filters": {
            key: value
            for key, value in _FILTER_DEFAULTS_45.items()
            if key != "dyn_notch_width_percent"
        },
        "pid": copy.deepcopy(_PID_DEFAULTS_45),
        "d_min": copy.deepcopy(_D_MIN_DEFAULTS_45),
    },
    "4.3-limited": {
        "filters": {
            key: value
            for key, value in _FILTER_DEFAULTS_45.items()
            if key
            not in {
                "dyn_notch_width_percent",
                "rpm_filter_max_hz",
            }
        },
        "pid": copy.deepcopy(_PID_DEFAULTS_45),
        "d_min": copy.deepcopy(_D_MIN_DEFAULTS_45),
    },
}

_PROFILE_WARNINGS: dict[str, list[str]] = {
    "4.4": ["betaflight_4_4_defaults_limited_key_coverage"],
    "4.3-limited": ["betaflight_4_3_limited_defaults"],
    "4.6-safe": ["betaflight_modern_profile_uses_4_6_safe_defaults"],
}

_PROFILE_PROVENANCE: dict[str, dict[str, Any]] = {
    "4.5": {
        "source_label": "official_betaflight_4_5_1_source_code",
        "source_type": "official_dump",
        "verified": True,
        "official_source_url_or_note": (
            "Extracted from betaflight/betaflight GitHub tag 4.5.1: "
            "src/main/flight/pid.h (PID/d_min/filter defines), "
            "src/main/sensors/gyro.c (gyro LPF defaults), "
            "src/main/pg/dyn_notch.c (notch defaults), "
            "src/main/pg/rpm_filter.c (RPM filter defaults). "
            "Phase 3B: tmp/external/extract_bf_defaults.py."
        ),
        "inherited_from": None,
        "confidence": "high",
        "notes": (
            "Values corrected from audit_seed: yaw_I 100→80, d_min.roll 23→30, "
            "d_min.pitch 25→34, gyro_lpf2_static_hz 350→500, dyn_notch_count 1→3, "
            "dyn_notch_min_hz 20→100, dyn_notch_q 500→300, feedforward_smooth_factor 45→25, "
            "feedforward_jitter_factor 12→7, anti_gravity_gain 5000→80 (firmware int scale). "
            "rpm_filter_max_hz and dyn_notch_width_percent are not firmware registers in BF 4.5."
        ),
        "provisional_keys": ["dyn_notch_width_percent", "rpm_filter_max_hz", "simplified_gyro_filter_multiplier", "simplified_dterm_filter_multiplier"],
        "unsupported_keys": ["rpm_filter_max_hz"],
    },
    "4.6": {
        "source_label": "gyrocore_audit_seed_inherited_from_4_5",
        "source_type": "inherited",
        "verified": False,
        "official_source_url_or_note": (
            "BF 4.6 does not exist as a public release (latest stable: 4.5.4, then 2025.12.x). "
            "4.6 profile is a compat alias inheriting corrected 4.5 defaults pending 2025.x verification."
        ),
        "inherited_from": "4.5",
        "confidence": "low",
        "notes": "4.6 profile inherits corrected BF 4.5.1 defaults. No 4.6.0 source exists to extract from.",
        "provisional_keys": ["all"],
        "unsupported_keys": [],
    },
    "4.6-safe": {
        "source_label": "compatibility_mode_4_6_safe_inherited_from_4_6",
        "source_type": "compatibility_mode",
        "verified": False,
        "official_source_url_or_note": None,
        "inherited_from": "4.6",
        "confidence": "low",
        "notes": "Compatibility profile for modern/date-based versions; no board-specific assumptions.",
        "provisional_keys": ["all"],
        "unsupported_keys": [],
    },
    "4.4": {
        "source_label": "gyrocore_audit_seed_4_4_limited",
        "source_type": "inherited",
        "verified": False,
        "official_source_url_or_note": None,
        "inherited_from": "4.5",
        "confidence": "low",
        "notes": "Incomplete/provisional 4.4 key coverage; support policy should downgrade effective support.",
        "provisional_keys": ["dyn_notch_width_percent"],
        "unsupported_keys": ["dyn_notch_width_percent"],
    },
    "4.3-limited": {
        "source_label": "gyrocore_audit_seed_4_3_limited",
        "source_type": "inherited",
        "verified": False,
        "official_source_url_or_note": None,
        "inherited_from": "4.5",
        "confidence": "low",
        "notes": "Limited conservative profile only; paste-ready output remains constrained by support policy.",
        "provisional_keys": [],
        "unsupported_keys": ["dyn_notch_width_percent", "rpm_filter_max_hz"],
    },
}


def get_defaults_provenance_summary(profile: str) -> dict[str, Any]:
    """Return a clean provenance summary for a given profile.

    Returns the provenance dict for known profiles, or an 'unavailable' stub
    for unknown profiles. Never raises.
    """
    generated = get_firmware_default_profile(profile)
    if generated is not None:
        return dict(generated.get("provenance") or {})
    if profile in _PROFILE_PROVENANCE:
        return dict(_PROFILE_PROVENANCE[profile])
    return {
        "source_label": "unavailable",
        "source_type": "unavailable",
        "verified": False,
        "official_source_url_or_note": None,
        "inherited_from": None,
        "confidence": "low",
        "notes": f"No provenance data available for profile {profile!r}.",
        "provisional_keys": [],
        "unsupported_keys": [],
    }


def _leaf_count(value: Any) -> int:
    if isinstance(value, Mapping):
        return sum(_leaf_count(v) for v in value.values())
    return 1


def _profile_from_support_or_version(
    firmware_support: Mapping[str, Any] | None = None,
    version: Any = None,
) -> tuple[str | None, bool, list[str]]:
    support = firmware_support if isinstance(firmware_support, Mapping) else {}
    raw_profile = support.get("engine_profile") or support.get("defaults_profile")
    warnings = list(support.get("warnings") or []) if isinstance(support.get("warnings"), list) else []
    if raw_profile is not None:
        profile = str(raw_profile).strip()
        normalized = str(support.get("normalized_version") or "")
        if profile == "4.6" and (normalized.startswith("2025.12.") or any("date" in str(w) for w in warnings)):
            return "2025.12", False, warnings
        if profile == "4.6" and any("mapped_to_4_6" in str(w) for w in warnings):
            return "4.6-safe", True, warnings
        if profile == "4.4" and support.get("support_level") == "limited":
            return "4.3-limited", False, warnings
        return profile, False, warnings

    raw_version = version if version is not None else support.get("normalized_version")
    if raw_version is None:
        return None, False, warnings
    text = str(raw_version).strip()
    match = _PROFILE_RE.search(text)
    if not match:
        return None, False, warnings
    major = int(match.group(1))
    minor = int(match.group(2))
    if major >= 2000:
        if major == 2025 and minor == 12:
            return "2025.12", False, warnings + ["betaflight_date_based_2025_12_official_defaults"]
        return "4.6-safe", True, warnings + ["betaflight_modern_profile_mapped_to_4_6"]
    if major >= 5:
        return "4.6-safe", True, warnings + ["betaflight_modern_profile_mapped_to_4_6"]
    if (major, minor) == (4, 3):
        return "4.3-limited", False, warnings + ["betaflight_4_3_limited_support"]
    if (major, minor) == (4, 4):
        return "4.4", False, warnings
    if (major, minor) == (4, 5):
        return "4.5", False, warnings
    if major == 4 and minor >= 6:
        return "4.6", False, warnings
    return None, False, warnings


def load_betaflight_defaults(
    firmware_support: Mapping[str, Any] | None = None,
    *,
    version: Any = None,
) -> dict[str, Any]:
    """Return versioned defaults plus metadata without raising on unknown input."""
    profile, compatibility_mode, inherited_warnings = _profile_from_support_or_version(
        firmware_support,
        version,
    )
    warnings = list(dict.fromkeys(str(w) for w in inherited_warnings if str(w).strip()))
    generated = get_firmware_default_profile(profile) if profile is not None else None
    if generated is None or not generated.get("defaults"):
        reason = "betaflight_defaults_profile_unavailable"
        if profile == "4.6":
            reason = "betaflight_4_6_no_official_release"
            generated = get_firmware_default_profile("4.6")
        provenance = copy.deepcopy((generated or {}).get("provenance") or {})
        return {
            "defaults": {"filters": {}, "pid": {}, "d_min": {}, "meta": {}},
            "metadata": {
                "defaults_available": False,
                "defaults_profile_used": profile,
                "compatibility_mode": False,
                "known_fields_count": 0,
                "unknown_required_fields": ["defaults_profile"],
                "warnings": list(dict.fromkeys(warnings + [reason])),
                "fallback_reason": reason,
                "provenance": provenance or {
                    "source_label": "unavailable",
                    "source_type": "unavailable",
                    "verified": False,
                    "notes": "No supported defaults profile could be selected.",
                    "inherited_from": None,
                    "confidence": "low",
                    "blockers": [reason],
                },
                "firmware_coverage": get_firmware_coverage_summary(),
            },
        }

    defaults = copy.deepcopy(generated["defaults"])
    meta_warnings = warnings + _PROFILE_WARNINGS.get(profile, [])
    provenance = copy.deepcopy(generated.get("provenance") or {})
    if provenance and provenance.get("verified") is not True:
        source_label = str(provenance.get("source_label") or profile)
        meta_warnings.append(f"defaults_provenance_unverified:{source_label}")
    meta_warnings.extend(str(b) for b in provenance.get("blockers", []) if str(b).strip())
    defaults["meta"] = {
        "defaults_profile_used": profile,
        "compatibility_mode": compatibility_mode or bool(provenance.get("compatibility_mode")),
        "defaults_provenance": provenance,
    }
    return {
        "defaults": defaults,
        "metadata": {
            "defaults_available": True,
            "defaults_profile_used": profile,
            "compatibility_mode": compatibility_mode or bool(provenance.get("compatibility_mode")),
            "known_fields_count": _leaf_count(defaults),
            "unknown_required_fields": [],
            "warnings": list(dict.fromkeys(meta_warnings)),
            "fallback_reason": None,
            "provenance": provenance,
            "firmware_coverage": get_firmware_coverage_summary(),
        },
    }


__all__ = ["get_defaults_provenance_summary", "load_betaflight_defaults"]
