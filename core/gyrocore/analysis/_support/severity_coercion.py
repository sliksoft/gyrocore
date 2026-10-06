# GyroCore WU4: adapted from AeroTuner backend/services/severity_coercion.py
"""Shared coercion for problem severity labels used by safety helpers."""

from __future__ import annotations

import math
from typing import Any

_SEVERITY_LABEL_FLOAT: dict[str, float] = {
    "critical": 1.0,
    "high": 1.0,
    "medium": 0.5,
    "low": 0.0,
}


def coerce_problem_severity(value: Any, default: float = 0.0) -> float:
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, str):
        label = value.strip().lower()
        if label in _SEVERITY_LABEL_FLOAT:
            return _SEVERITY_LABEL_FLOAT[label]
        value = label
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(out):
        return default
    return out
