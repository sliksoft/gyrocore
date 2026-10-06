"""Embedded multi-log BBL metadata (blackbox_decode ``--index``).

Adapted from AeroTuner ``backend/services/embedded_bbl_log.py`` (WU3).
Session/route redecode helpers are intentionally omitted.

Index conventions:
- ``index`` / ``selected_embedded_log_index`` / ``recommended_embedded_log_index``: **0-based**
  internal indices passed to decode (CLI uses ``--index N+1``).
- ``display_index`` in ``embedded_log_entries``: **1-based** labels for user-facing "Flight N".
"""

from __future__ import annotations

import re
from typing import Any

_EMBEDDED_LOG_TABLE_ROW_RE = re.compile(
    r"^\s*(\d+)\s+(-?\d+)\s+(\d+)\s*$",
    re.MULTILINE,
)

# Ignore tiny setup/header fragments when recommending (e.g. 379-byte index 0).
_MIN_EMBEDDED_LOG_BYTES = 1000


def parse_embedded_log_table(stderr: str | None) -> list[dict[str, Any]]:
    """
    Parse blackbox_decode stderr table:

    Index  Start offset  Size (bytes)
        1             0           379
    """
    if not stderr:
        return []
    entries: list[dict[str, Any]] = []
    for match in _EMBEDDED_LOG_TABLE_ROW_RE.finditer(stderr):
        try:
            display_index = int(match.group(1))
            start_offset = int(match.group(2))
            size_bytes = int(match.group(3))
        except (TypeError, ValueError):
            continue
        if display_index < 1:
            continue
        entries.append(
            {
                "index": display_index - 1,
                "display_index": display_index,
                "start_offset": start_offset,
                "size_bytes": size_bytes,
            }
        )
    return entries


def recommend_embedded_log_index(entries: list[dict[str, Any]]) -> int:
    """Lightweight recommendation: largest meaningful log; tie-break higher index."""
    if not entries:
        return 0
    usable = [
        row
        for row in entries
        if isinstance(row.get("size_bytes"), int)
        and int(row["size_bytes"]) >= _MIN_EMBEDDED_LOG_BYTES
    ]
    pool = usable if usable else entries
    best = max(
        pool,
        key=lambda row: (int(row.get("size_bytes") or 0), int(row.get("index") or 0)),
    )
    return int(best["index"])


def build_embedded_log_metadata(
    entries: list[dict[str, Any]],
    *,
    selected_index: int,
    selection_mode: str = "auto",
) -> dict[str, Any]:
    count = len(entries)
    sel = int(selected_index)
    return {
        "embedded_log_count": count,
        "embedded_log_entries": entries,
        "recommended_embedded_log_index": recommend_embedded_log_index(entries),
        "selected_embedded_log_index": sel,
        "embedded_log_selection_mode": (
            selection_mode if selection_mode in {"auto", "manual"} else "auto"
        ),
    }
