# GyroCore WU4: adapted from AeroTuner backend/analysis/motor_prop_physics.py
"""
Prop diameter class from motor electrical frequency and DC bus (KV × V) vs observed RPM.

``load_factor = (KV * battery_voltage) / rpm`` compares no-load speed to measured fundamental;
higher values imply heavier loading (larger / more aggressive props). Combined with
fundamental Hz bands to reduce single-signal ambiguity.
"""

from __future__ import annotations

import math
from typing import Any

_PROP_LABELS = ("3", "5", "7+")


def estimate_prop_class_from_motor_physics(
    fundamental_hz: Any,
    kv: Any,
    battery_voltage_v: Any,
    *,
    load_low_max: float = 1.12,
    load_mid_max: float = 1.38,
    freq_small_bias_hz: float = 250.0,
    freq_large_bias_hz: float = 150.0,
) -> dict[str, Any]:
    """
    Returns ``estimated_prop_class`` (``\"3\"`` | ``\"5\"`` | ``\"7+\"``), ``load_factor``,
    and ``confidence`` (0..1). Missing or non-physical inputs yield nulls and zero confidence.
    """
    empty: dict[str, Any] = {
        "estimated_prop_class": None,
        "load_factor": None,
        "confidence": 0.0,
    }

    try:
        f_hz = float(fundamental_hz) if fundamental_hz is not None else float("nan")
    except (TypeError, ValueError):
        f_hz = float("nan")
    try:
        kv_f = float(kv) if kv is not None else float("nan")
    except (TypeError, ValueError):
        kv_f = float("nan")
    try:
        vbat = float(battery_voltage_v) if battery_voltage_v is not None else float("nan")
    except (TypeError, ValueError):
        vbat = float("nan")

    if (
        not math.isfinite(f_hz)
        or not math.isfinite(kv_f)
        or not math.isfinite(vbat)
        or f_hz <= 0
        or kv_f <= 0
        or vbat <= 0
    ):
        return empty

    rpm = f_hz * 60.0
    if not math.isfinite(rpm) or rpm <= 0:
        return empty

    no_load_rpm = kv_f * vbat
    if not math.isfinite(no_load_rpm) or no_load_rpm <= 0:
        return empty

    load_factor = no_load_rpm / rpm
    if not math.isfinite(load_factor) or load_factor <= 0:
        return empty

    # Load-only ordinal: 0 = small props (low load factor), 1 = mid, 2 = large props (high LF).
    if load_factor <= load_low_max:
        o_load = 0
    elif load_factor <= load_mid_max:
        o_load = 1
    else:
        o_load = 2

    # Frequency ordinal: high Hz → small props (0), mid band → 5", low Hz → 7+ (2).
    if f_hz > freq_small_bias_hz:
        o_freq = 0
    elif f_hz >= freq_large_bias_hz:
        o_freq = 1
    else:
        o_freq = 2

    combined = int(round(0.5 * (float(o_load) + float(o_freq))))
    combined = max(0, min(2, combined))
    prop_class = _PROP_LABELS[combined]

    disagreement = abs(o_load - o_freq) / 2.0
    conf = 0.52 + 0.38 * (1.0 - disagreement)

    # Sharpen confidence when load_factor sits away from tier boundaries.
    band_margin = min(
        abs(load_factor - load_low_max),
        abs(load_factor - load_mid_max),
    )
    margin_boost = min(0.12, band_margin * 0.35)
    conf += margin_boost

    if freq_large_bias_hz < f_hz < freq_small_bias_hz:
        conf += 0.04

    conf = max(0.0, min(1.0, conf))

    return {
        "estimated_prop_class": prop_class,
        "load_factor": round(load_factor, 4),
        "confidence": round(conf, 4),
    }
