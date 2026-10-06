"""GyroCore Blackbox decode / log-ingest foundation (WU3).

Trusted explicit local paths by default. No AeroTuner upload-root jail.
Does not perform flight analysis or tuning.
"""

from __future__ import annotations

from .decoder import decode_bbl, decode_runtime_status
from .embedded import (
    build_embedded_log_metadata,
    parse_embedded_log_table,
    recommend_embedded_log_index,
)
from .inspect import inspect_log
from .locator import resolve_blackbox_decode
from .models import DecodeResult, InspectLogResult
from .paths import validate_bbl_path

__all__ = [
    "DecodeResult",
    "InspectLogResult",
    "build_embedded_log_metadata",
    "decode_bbl",
    "decode_runtime_status",
    "inspect_log",
    "parse_embedded_log_table",
    "recommend_embedded_log_index",
    "resolve_blackbox_decode",
    "validate_bbl_path",
]
