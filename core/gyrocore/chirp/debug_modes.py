"""CHIRP debug-mode index lookup (mirror of Betaflight Configurator).

Upstream:

- ``src/js/debug_modes_table.ts`` ``FIRMWARE_DEBUG_MODES`` (per-API enum lists)
- ``src/js/utils/debugModes.ts`` ``resolveTableVersion`` / ``getDebugModeIndex``
- ``src/js/blackbox/chirp_bbl_parser.ts`` ``validateDebugModeIsChirp``
- ``src/js/data_storage.ts`` ``API_VERSION_MAX_SUPPORTED`` (``1.49.0``)

Only the CHIRP slot is mirrored; values are locked by
``tests/fixtures/chirp/wu7/upstream_math_reference.json`` (``debugModes``).
"""

from __future__ import annotations

import re

API_VERSION_MAX_SUPPORTED = "1.49.0"

# Table version -> index of "CHIRP" in FIRMWARE_DEBUG_MODES[version] (-1: absent).
CHIRP_DEBUG_INDEX_BY_TABLE_VERSION: dict[str, int] = {
    "1.44.0": -1,
    "1.45.0": -1,
    "1.46.0": -1,
    "1.47.0": 97,
    "1.48.0": 96,
    "1.49.0": 96,
}

_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _semver(value: str | None) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    m = _SEMVER.match(value.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _resolve_table_version(api_version: str | None) -> str:
    versions = sorted(CHIRP_DEBUG_INDEX_BY_TABLE_VERSION, key=lambda v: _semver(v) or (0, 0, 0))
    oldest = versions[0]
    parsed = _semver(api_version)
    if parsed is None:
        return oldest
    resolved = oldest
    for candidate in versions:
        if parsed >= (_semver(candidate) or (0, 0, 0)):
            resolved = candidate
    return resolved


def chirp_debug_mode_index(api_version: str | None) -> int:
    """``getDebugModeIndex("CHIRP", apiVersion)``; -1 when the table has no CHIRP slot."""
    return CHIRP_DEBUG_INDEX_BY_TABLE_VERSION[_resolve_table_version(api_version)]


def effective_chirp_api_version(log_api_version: str | None, caller_api_version: str | None) -> str:
    """API version ``validateDebugModeIsChirp`` uses: log, then caller, then max supported."""
    if log_api_version and log_api_version != "0.0.0":
        return log_api_version
    if caller_api_version and caller_api_version != "0.0.0":
        return caller_api_version
    return API_VERSION_MAX_SUPPORTED


__all__ = [
    "API_VERSION_MAX_SUPPORTED",
    "CHIRP_DEBUG_INDEX_BY_TABLE_VERSION",
    "chirp_debug_mode_index",
    "effective_chirp_api_version",
]
