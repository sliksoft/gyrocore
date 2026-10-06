"""Resolve the ``blackbox_decode`` executable from CoreConfig / PATH.

Domain code does not read environment variables. Callers/adapters may populate
``CoreConfig.blackbox_decode_path`` from ``AEROTUNER_BLACKBOX_DECODE`` outside Core.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from gyrocore.config import CoreConfig
from gyrocore.errors import DecodeError


def resolve_blackbox_decode(config: CoreConfig | None = None) -> Path:
    """
    Resolve decoder executable.

    Order:
    1. ``config.blackbox_decode_path`` when set
    2. ``PATH`` lookup for ``blackbox_decode``
    """
    cfg = config or CoreConfig.defaults()
    override = cfg.blackbox_decode_path
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_file():
            raise DecodeError(f"blackbox_decode_path is not a file: {candidate}")
        return candidate.resolve()
    found = shutil.which("blackbox_decode")
    if not found:
        raise DecodeError(
            "blackbox_decode not found on PATH; set CoreConfig.blackbox_decode_path"
        )
    return Path(found)
