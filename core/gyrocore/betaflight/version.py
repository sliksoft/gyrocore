"""Betaflight firmware support policy for paste-ready tuning output."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_VERSION_RE = re.compile(r"(\d{1,4})\.(\d{1,2})(?:\.(\d{1,3}))?")
_UNKNOWN_TEXT = {"", "unknown", "none", "null", "n/a", "na", "undefined"}


def _empty_support(raw_version: Any, reason: str = "betaflight_firmware_unknown") -> dict[str, Any]:
    return {
        "raw_version": raw_version,
        "normalized_version": None,
        "version_family": None,
        "support_level": "unknown",
        "cli_mode": "diagnostic_only",
        "cli_allowed": False,
        "engine_profile": None,
        "reason": reason,
        "warnings": [reason],
    }


def classify_betaflight_version(version: Any) -> dict[str, Any]:
    raw_version = version
    if version is None or isinstance(version, bool):
        return _empty_support(raw_version)
    text = str(version).strip()
    if text.lower() in _UNKNOWN_TEXT:
        return _empty_support(raw_version)
    match = _VERSION_RE.search(text)
    if not match:
        return _empty_support(raw_version, "betaflight_firmware_malformed")

    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    normalized = f"{major}.{minor}.{patch}"
    family = f"{major}.{minor}"
    warnings: list[str] = []

    if major >= 2000:
        if major == 2025 and minor == 12:
            warnings.append("betaflight_date_based_2025_12_official_source")
            return {
                "raw_version": raw_version,
                "normalized_version": normalized,
                "version_family": family,
                "support_level": "full",
                "cli_mode": "full_cli",
                "cli_allowed": True,
                "engine_profile": "2025.12",
                "reason": "betaflight_2025_12_official_support_candidate",
                "warnings": warnings,
            }
        warnings.append("betaflight_modern_profile_mapped_to_4_6")
        return {
            "raw_version": raw_version,
            "normalized_version": normalized,
            "version_family": family,
            "support_level": "full",
            "cli_mode": "full_cli",
            "cli_allowed": True,
            "engine_profile": "4.6",
            "reason": "betaflight_modern_full_support",
            "warnings": warnings,
        }
    if major >= 5:
        warnings.append("betaflight_modern_profile_mapped_to_4_6")
        return {
            "raw_version": raw_version,
            "normalized_version": normalized,
            "version_family": family,
            "support_level": "full",
            "cli_mode": "full_cli",
            "cli_allowed": True,
            "engine_profile": "4.6",
            "reason": "betaflight_5_full_support",
            "warnings": warnings,
        }
    if (major, minor) <= (4, 2):
        reason = "betaflight_version_unsupported_legacy"
        return {
            "raw_version": raw_version,
            "normalized_version": normalized,
            "version_family": family,
            "support_level": "diagnostic_only",
            "cli_mode": "diagnostic_only",
            "cli_allowed": False,
            "engine_profile": None,
            "reason": reason,
            "warnings": [reason],
        }
    if (major, minor) == (4, 3):
        return {
            "raw_version": raw_version,
            "normalized_version": normalized,
            "version_family": family,
            "support_level": "limited",
            "cli_mode": "limited_cli",
            "cli_allowed": True,
            "engine_profile": "4.4",
            "reason": "betaflight_4_3_limited_support",
            "warnings": ["betaflight_4_3_limited_support"],
        }
    if (major, minor) == (4, 4):
        profile = "4.4"
    elif (major, minor) == (4, 5):
        profile = "4.5"
    elif (major, minor) >= (4, 6):
        profile = "4.6"
        warnings.append("betaflight_4_6_no_official_release")
        return {
            "raw_version": raw_version,
            "normalized_version": normalized,
            "version_family": family,
            "support_level": "limited",
            "cli_mode": "limited_cli",
            "cli_allowed": True,
            "engine_profile": profile,
            "reason": "betaflight_4_6_no_official_release",
            "warnings": warnings,
        }
    else:
        return _empty_support(raw_version)
    return {
        "raw_version": raw_version,
        "normalized_version": normalized,
        "version_family": family,
        "support_level": "full",
        "cli_mode": "full_cli",
        "cli_allowed": True,
        "engine_profile": profile,
        "reason": f"betaflight_{profile.replace('.', '_')}_full_support",
        "warnings": warnings,
    }


def classify_firmware_metadata(firmware_meta: Mapping[str, Any] | None) -> dict[str, Any]:
    meta = firmware_meta if isinstance(firmware_meta, Mapping) else {}
    name = str(meta.get("name") or "").strip().lower()
    version = meta.get("version")
    if name and "betaflight" not in name and "btfl" not in name:
        out = _empty_support(version, "betaflight_firmware_unknown")
        out["firmware_name"] = meta.get("name")
        return out
    out = classify_betaflight_version(version)
    if meta.get("name") is not None:
        out["firmware_name"] = meta.get("name")
    return out


def betaflight_support_trace_entry(support: Mapping[str, Any]) -> dict[str, str] | None:
    if not isinstance(support, Mapping):
        return None
    reason = str(support.get("reason") or "").strip()
    if not reason:
        return None
    if support.get("cli_allowed") is not True:
        status = "blocked"
    elif support.get("support_level") == "limited":
        status = "warning"
    else:
        status = "ok"
    return {
        "step": "betaflight-support",
        "status": status,
        "detail": reason[:240],
    }
