# GyroCore WU4: adapted from AeroTuner backend/services/hardware_input_normalize.py
"""
Normalize wizard / API ``user_inputs["hardware"]`` for analysis.

- Coerces motor KV, cell count, motor poles to numeric forms
- Preserves ``hardware_sources`` provenance while canonicalizing substantive values
- Adds ``hardware_confidence`` (0–1) and ``hardware_normalized`` summary (additive; backward compatible)
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

from gyrocore.analysis.context_validation import (
    _normalize_frame_label,
    _nominal_battery_voltage_ui,
    _parse_battery_cells_ui,
    _parse_kv_ui,
    _safe_str,
    aggregate_hardware_source_from_sources,
    frame_ordinal_from_label,
    resolve_hardware_sources,
)
from gyrocore.analysis._support.hardware_class import normalize_hardware_class
from gyrocore.analysis._support.hardware_plausibility import evaluate_hardware_plausibility


def _parse_kv_to_int(kv_raw: Any) -> int | None:
    v = _parse_kv_ui(kv_raw)
    if v is None:
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return int(round(v))


def _frame_inches_from_label(norm_label: str | None) -> float | None:
    if not norm_label:
        return None
    s = norm_label.strip().lower()
    if "micro" in s or "2-3" in s:
        return 2.5
    if s.startswith("5") or '5"' in s:
        return 5.0
    if "10+" in s or s.startswith("10"):
        return 10.0
    if s.startswith("7") or "7+" in s:
        return 7.0
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        x = float(m.group(1))
    except (TypeError, ValueError):
        return None
    if math.isfinite(x) and 2.0 <= x <= 12.0:
        return x
    return None


def build_hardware_hash(hardware: dict) -> str:
    """
    Stable SHA-256 digest of the hardware inputs that affect ERPM / validation / tuning.

    Uses the same coercions as ``normalize_user_inputs_hardware`` so equivalent string forms
    (e.g. ``\"2400\"`` vs ``2400``) map to one hash.
    """
    if not isinstance(hardware, dict):
        hardware = {}

    kv_int: int | None = None
    mkv = hardware.get("motor_kv_value")
    if isinstance(mkv, (int, float)) and math.isfinite(float(mkv)):
        try:
            kv_int = int(round(float(mkv)))
        except (TypeError, ValueError):
            kv_int = None
    elif isinstance(mkv, str) and mkv.strip():
        kv_int = _parse_kv_to_int(mkv)
    if kv_int is None:
        kv_int = _parse_kv_to_int(hardware.get("motor_kv"))
    if kv_int is None:
        kv_int = _parse_kv_to_int(hardware.get("motors_kv"))

    cells = hardware.get("cells")
    if not isinstance(cells, int) or not (1 <= cells <= 12):
        cells = _parse_battery_cells_ui(hardware.get("battery"))

    poles = _coerce_motor_poles_int(hardware.get("motor_poles"))
    poles_confirmed = hardware.get("motor_poles_confirmed") is True
    poles_source = hardware.get("motor_poles_source")
    if not isinstance(poles_source, str):
        poles_source = None

    payload = {
        "cells": cells if isinstance(cells, int) else None,
        "motor_kv_value": kv_int,
        "motor_poles": poles,
        "motor_poles_confirmed": bool(poles_confirmed),
        "motor_poles_source": poles_source.strip().lower() if poles_source else None,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def coalesce_user_inputs_hardware_for_cache(ui: dict[str, Any] | None) -> dict[str, Any]:
    """
    Single mapping for cache hashing: nested ``hardware`` plus legacy top-level keys the
    pipeline may read when the nested block is absent or incomplete.
    """
    if not isinstance(ui, dict):
        return {}
    out: dict[str, Any] = {}
    hw = ui.get("hardware")
    if isinstance(hw, dict):
        out.update(hw)
    if not str(out.get("motor_kv") or "").strip() and ui.get("motor_kv") is not None:
        out["motor_kv"] = ui.get("motor_kv")
    if ui.get("motors_kv") is not None:
        out["motors_kv"] = ui.get("motors_kv")
    if not str(out.get("battery") or "").strip() and ui.get("battery") is not None:
        out["battery"] = ui.get("battery")
    if out.get("motor_poles") is None and ui.get("motor_poles") is not None:
        out["motor_poles"] = ui.get("motor_poles")
    if out.get("cells") is None and ui.get("cells") is not None:
        out["cells"] = ui.get("cells")
    return out


def _coerce_motor_poles_int(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        return None
    if n >= 2 and n % 2 == 0:
        return n
    return None


def _pack_voltage_estimate_v(cells: int | None) -> float | None:
    """Full-charge style estimate (4.2 V/cell), matches common 6S ≈ 25.2 V."""
    if cells is None or cells < 1:
        return None
    return round(float(cells) * 4.2, 2)


def _normalize_prop_structured(hw: dict[str, Any]) -> None:
    raw = hw.get("prop_structured")
    if not isinstance(raw, dict):
        return
    out: dict[str, Any] = {}

    size_raw = raw.get("size")
    unit_raw = _safe_str(raw.get("sizeUnit"))
    unit = unit_raw.lower() if unit_raw else None
    size_value: float | None = None
    if isinstance(size_raw, (int, float)):
        size_value = float(size_raw)
    elif isinstance(size_raw, str):
        try:
            size_value = float(size_raw.strip())
        except ValueError:
            size_value = None
    if size_value is not None and math.isfinite(size_value) and size_value > 0:
        if unit == "mm":
            hw["prop_size"] = round(size_value / 25.4, 3)
            out["size"] = str(size_raw).strip()
            out["sizeUnit"] = "mm"
        elif unit in {"inch", "custom"}:
            hw["prop_size"] = round(size_value, 3)
            out["size"] = str(size_raw).strip()
            out["sizeUnit"] = unit

    blades_raw = raw.get("blades")
    try:
        blades = int(float(blades_raw))
    except (TypeError, ValueError):
        blades = None
    if blades in (2, 3, 4, 5):
        hw["prop_blades"] = blades
        out["blades"] = blades

    pitch_raw = raw.get("pitch")
    if isinstance(pitch_raw, str):
        ptxt = pitch_raw.strip().lower()
        if ptxt == "unknown":
            out["pitch"] = "unknown"
        elif ptxt == "custom":
            out["pitch"] = "custom"
    elif isinstance(pitch_raw, (int, float)) and math.isfinite(float(pitch_raw)):
        pitch_val = round(float(pitch_raw), 3)
        if pitch_val > 0:
            hw["prop_pitch"] = pitch_val
            out["pitch"] = pitch_val

    raw_label = _safe_str(raw.get("rawLabel"))
    if raw_label:
        hw["prop_raw_label"] = raw_label
        out["rawLabel"] = raw_label

    if out:
        hw["prop_structured"] = out


def _compute_hardware_confidence(
    hs: dict[str, str],
    *,
    frame_ok: bool,
    kv_ok: bool,
    bat_ok: bool,
    poles_ok: bool,
) -> float:
    """
    0–1 score: repaired per-field sources (user vs detected vs default) plus small bonus for poles.

    After source repair, ``user`` on a field with a parsed value implies high trust; ``default``
    on a field means missing/placeholder (low contribution).
    """
    weights = {"frame": 0.34, "motor_kv": 0.33, "battery": 0.33}
    acc = 0.0
    wsum = 0.0
    for key, ok in (
        ("frame", frame_ok),
        ("motor_kv", kv_ok),
        ("battery", bat_ok),
    ):
        w = weights[key]
        wsum += w
        if not ok:
            continue
        src = str(hs.get(key) or "default")
        if src == "user":
            acc += 1.0 * w
        elif src == "detected":
            acc += 0.82 * w
        else:
            acc += 0.38 * w
    base = acc / wsum if wsum > 0 else 0.0
    if poles_ok:
        base = min(1.0, base + 0.06)
    return round(max(0.0, min(1.0, base)), 3)


def normalize_user_inputs_hardware(user_inputs: dict[str, Any] | None) -> None:
    """
    Mutate ``user_inputs["hardware"]`` in place: typing, canonical strings, repaired sources,
    ``hardware_confidence``, and ``hardware_normalized``.
    """
    if not isinstance(user_inputs, dict):
        return
    raw_hw = user_inputs.get("hardware")
    if not isinstance(raw_hw, dict):
        return
    hw: dict[str, Any] = raw_hw

    hardware_class = normalize_hardware_class(hw.get("hardware_class"))
    if hardware_class:
        hw["hardware_class"] = hardware_class
    else:
        hw.pop("hardware_class", None)

    _normalize_prop_structured(hw)

    frame_raw = hw.get("frame")
    frame_str = _safe_str(frame_raw)
    frame_norm = _normalize_frame_label(frame_str) if frame_str else None
    if frame_norm:
        hw["frame"] = frame_norm

    kv_int = _parse_kv_to_int(hw.get("motor_kv"))
    if kv_int is not None:
        hw["motor_kv"] = str(kv_int)
        hw["motor_kv_value"] = kv_int

    cells = _parse_battery_cells_ui(hw.get("battery"))
    if cells is not None:
        hw["cells"] = cells
        hw["nominal_voltage_v"] = _nominal_battery_voltage_ui(cells)
        hw["pack_voltage_estimate_v"] = _pack_voltage_estimate_v(cells)

    poles = _coerce_motor_poles_int(hw.get("motor_poles"))
    if poles is not None:
        hw["motor_poles"] = poles

    stator = _safe_str(hw.get("motor_stator"))
    if stator:
        hw["motor_stator"] = stator

    hs = resolve_hardware_sources(
        hardware_sources=hw.get("hardware_sources"),
        hardware_source=hw.get("hardware_source"),
    )

    frame_ok = (
        frame_norm is not None and frame_ordinal_from_label(frame_norm) is not None
    )
    kv_ok = kv_int is not None
    bat_ok = cells is not None

    hw["hardware_sources"] = dict(hs)
    hw["hardware_source"] = aggregate_hardware_source_from_sources(hs)

    plausibility = evaluate_hardware_plausibility(hw)
    if isinstance(plausibility, dict):
        hw["hardware_plausibility"] = plausibility

    frame_inches = _frame_inches_from_label(frame_norm)
    hw_conf = _compute_hardware_confidence(
        hs,
        frame_ok=frame_ok,
        kv_ok=kv_ok,
        bat_ok=bat_ok,
        poles_ok=poles is not None,
    )
    try:
        plausibility_mult = float(plausibility.get("confidence_multiplier")) if isinstance(plausibility, dict) else 1.0
    except (TypeError, ValueError):
        plausibility_mult = 1.0
    if math.isfinite(plausibility_mult) and 0.0 < plausibility_mult <= 1.0:
        hw_conf = round(max(0.0, min(1.0, hw_conf * plausibility_mult)), 3)
    hw["hardware_confidence"] = hw_conf

    hw["hardware_normalized"] = {
        "kv": kv_int,
        "cells": cells,
        "stator": stator,
        "frame": frame_inches,
        "motor_poles": poles,
        "nominal_voltage_v": hw.get("nominal_voltage_v"),
        "pack_voltage_estimate_v": hw.get("pack_voltage_estimate_v"),
        "confidence": hw_conf,
        "source": hw["hardware_source"],
        "plausibility_status": plausibility.get("status") if isinstance(plausibility, dict) else None,
        "plausibility_confidence_impact": plausibility.get("confidence_impact") if isinstance(plausibility, dict) else None,
    }
