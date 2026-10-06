# GyroCore WU4: adapted from AeroTuner backend/analysis/erpm_units.py
from __future__ import annotations

import math
from typing import Any


def _positive_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def resolve_pole_pairs(*, motor_poles: Any = None, pole_pairs: Any = None) -> float | None:
    """Resolve usable pole-pair count from explicit pole_pairs or motor_poles."""
    pp = _positive_float(pole_pairs)
    if pp is not None:
        return pp

    poles = _positive_float(motor_poles)
    if poles is None:
        return None
    if abs(poles - round(poles)) > 1e-9:
        return None
    n_poles = int(round(poles))
    if n_poles < 2 or n_poles % 2 != 0:
        return None
    return float(n_poles) / 2.0


def has_pole_pair_conflict(*, motor_poles: Any = None, pole_pairs: Any = None) -> bool:
    """True when explicit pole_pairs disagrees with motor_poles/2."""
    pp = _positive_float(pole_pairs)
    poles = _positive_float(motor_poles)
    if pp is None or poles is None:
        return False
    if abs(poles - round(poles)) > 1e-9:
        return False
    n_poles = int(round(poles))
    if n_poles < 2 or n_poles % 2 != 0:
        return False
    implied = float(n_poles) / 2.0
    return abs(pp - implied) > 1e-9


def to_mechanical_hz(
    hz: Any,
    *,
    motor_poles: Any = None,
    pole_pairs: Any = None,
    already_mechanical_hz: bool = False,
) -> float | None:
    """Convert Hz to mechanical space when input is electrical ERPM-derived Hz."""
    value = _positive_float(hz)
    if value is None:
        return None
    if already_mechanical_hz:
        return value
    pp = resolve_pole_pairs(motor_poles=motor_poles, pole_pairs=pole_pairs)
    if pp is None:
        return None
    return value / pp
