# GyroCore WU4: adapted from AeroTuner backend/analysis/context_validation.py
"""
Align user-declared hardware with log-derived estimates (frame class, style, inertia).

Uses per-axis gyro FFT peaks (motor-relevant band), motor electrical frequency (ERPM), and HF noise share.
Heuristics are intentionally conservative: confidence drops when signals are missing or contradictory.
"""

from __future__ import annotations

import logging
import math
import re
import statistics
from typing import Any, Mapping
from gyrocore.analysis._support.hardware_class import normalize_hardware_class
from gyrocore.analysis._support.hardware_profile import get_hardware_profile

_LOG = logging.getLogger(__name__)

# Per-axis gyro FFT peaks below this are treated as frame / drift noise, not motor band.
GYRO_AXIS_PEAK_MIN_HZ = 80.0

# ERPM dominant frequency from analysis is electrical (commutation) Hz. Mechanical fundamental
# (motor Hz) is electrical / pole_pairs (typical FPV 14-magnet outrunner ≈ 7 pole pairs).
DEFAULT_ERPM_POLE_PAIRS = 7

from gyrocore.analysis.motor_fft_harmonics import (
    estimate_motor_fundamental_from_fft_peaks_indexed,
    fft_peaks_indexed_from_signal_analysis,
    rpm_alignment_for_merged_gyro_hz,
)


# Ordinal frame buckets: micro (2–3"), mid (5"), large (7" and 10+")
_FRAME_LABEL_TO_ORD: dict[str, int] = {
    '2-3"': 0,
    "2-3": 0,
    "micro": 0,
    '5"': 1,
    "5": 1,
    '7"': 2,
    "7": 2,
    '10+"': 2,
    "10+": 2,
    "10": 2,
}

_FRAME_ORD_TO_LABEL = ('micro (2-3")', '5"', '7"+')


def _safe_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _normalize_frame_label(label: str | None) -> str | None:
    if not label:
        return None
    s = label.strip()
    key = s.lower().replace("inch", '"').strip()
    if key in _FRAME_LABEL_TO_ORD:
        for k, ordv in _FRAME_LABEL_TO_ORD.items():
            if k.lower().replace(" ", "") == key.replace(" ", ""):
                return _FRAME_ORD_TO_LABEL[ordv]
    # direct match
    for k, ordv in _FRAME_LABEL_TO_ORD.items():
        if k.lower() == key:
            return _FRAME_ORD_TO_LABEL[ordv]
    if re.match(r"^2[-‐]3", s, re.I):
        return _FRAME_ORD_TO_LABEL[0]
    if s.startswith("5"):
        return _FRAME_ORD_TO_LABEL[1]
    if s.startswith("7") or s.startswith("10"):
        return _FRAME_ORD_TO_LABEL[2]
    return s


def frame_ordinal_from_label(label: str | None) -> int | None:
    """0=micro, 1=5\", 2=7+ ."""
    if not label:
        return None
    s = label.strip().lower()
    for k, o in _FRAME_LABEL_TO_ORD.items():
        if k.lower() == s:
            return o
    if "micro" in s or "2-3" in s or ('2' in s and '3' in s):
        return 0
    if s == '5"' or (s.startswith("5") and len(s) <= 6):
        return 1
    if "7+" in s or "10+" in s or s.startswith("7") or s.startswith("10"):
        return 2
    nl = _normalize_frame_label(label)
    if nl in _FRAME_ORD_TO_LABEL:
        return list(_FRAME_ORD_TO_LABEL).index(nl)
    return None


def _normalize_hardware_source(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("user", "detected", "default"):
        return s
    return None


def _coerce_field_hardware_source(val: Any) -> str:
    s = _normalize_hardware_source(val)
    return s if s else "user"


def resolve_hardware_sources(
    *,
    hardware_sources: Any = None,
    hardware_source: Any = None,
) -> dict[str, str]:
    """
    Per-field provenance for frame / motor_kv / battery.
    Prefers ``hardware_sources``; falls back to legacy aggregate ``hardware_source``; else all user.
    """
    if isinstance(hardware_sources, dict):
        return {
            "frame": _coerce_field_hardware_source(hardware_sources.get("frame")),
            "motor_kv": _coerce_field_hardware_source(hardware_sources.get("motor_kv")),
            "battery": _coerce_field_hardware_source(hardware_sources.get("battery")),
        }
    agg = _normalize_hardware_source(hardware_source)
    if agg:
        return {"frame": agg, "motor_kv": agg, "battery": agg}
    return {"frame": "user", "motor_kv": "user", "battery": "user"}


def hardware_sources_from_hardware_block(hw: dict[str, Any] | None) -> dict[str, str]:
    h = hw if isinstance(hw, dict) else {}
    return resolve_hardware_sources(
        hardware_sources=h.get("hardware_sources"),
        hardware_source=h.get("hardware_source"),
    )


def hardware_sources_from_user_inputs(user_inputs: dict[str, Any] | None) -> dict[str, str]:
    ui = user_inputs if isinstance(user_inputs, dict) else {}
    if isinstance(ui.get("hardware"), dict):
        from gyrocore.analysis._support.hardware_input_normalize import (
            normalize_user_inputs_hardware,
        )

        normalize_user_inputs_hardware(ui)
    hw = ui.get("hardware") if isinstance(ui.get("hardware"), dict) else {}
    return hardware_sources_from_hardware_block(hw)


def aggregate_hardware_source_from_sources(sources: Mapping[str, Any]) -> str:
    """Worst-of rollup for UI / legacy (default beats detected beats user)."""
    f = str(sources.get("frame") or "user")
    k = str(sources.get("motor_kv") or "user")
    b = str(sources.get("battery") or "user")
    if "default" in (f, k, b):
        return "default"
    if "detected" in (f, k, b):
        return "detected"
    return "user"


def hardware_source_from_user_inputs(user_inputs: dict[str, Any] | None) -> str:
    """UI / legacy aggregate: worst-of over ``hardware_sources`` (or legacy single field)."""
    return aggregate_hardware_source_from_sources(
        hardware_sources_from_user_inputs(user_inputs),
    )


def _hardware_source_for_field(
    hw: Mapping[str, Any] | None,
    field: str,
    aliases: tuple[str, ...] = (),
) -> str | None:
    h = hw if isinstance(hw, Mapping) else {}
    keys = (field, *aliases)
    for key in keys:
        raw = h.get(f"{key}_source")
        src = _normalize_hardware_source(raw)
        if src:
            return src
    sources = h.get("hardware_sources")
    if isinstance(sources, Mapping):
        for key in keys:
            src = _normalize_hardware_source(sources.get(key))
            if src:
                return src
    return _normalize_hardware_source(h.get("hardware_source"))


def build_input_context(user_inputs: dict[str, Any] | None) -> dict[str, Any]:
    ui = user_inputs if isinstance(user_inputs, dict) else {}
    if isinstance(ui.get("hardware"), dict):
        from gyrocore.analysis._support.hardware_input_normalize import (
            normalize_user_inputs_hardware,
        )

        normalize_user_inputs_hardware(ui)
    hw = ui.get("hardware") if isinstance(ui.get("hardware"), dict) else {}
    goals = ui.get("goals")
    if not isinstance(goals, list):
        goals = None

    fs = hw.get("frame") if hw and hw.get("frame") is not None else hw.get("frame_size")
    frame_norm = _normalize_frame_label(_safe_str(fs)) if fs is not None else None
    hardware_class = normalize_hardware_class(hw.get("hardware_class"))
    derived_frame_size_source = None
    if frame_norm is None and _safe_str(fs) is None and hardware_class:
        profile = get_hardware_profile(hardware_class)
        if profile is not None:
            frame_norm = profile.frame_size_label
            derived_frame_size_source = "hardware_class"

    hs = hardware_sources_from_hardware_block(hw)
    out: dict[str, Any] = {
        "hardware_class": hardware_class,
        "frame_size": frame_norm or _safe_str(fs),
        "motor_kv": _safe_str(hw.get("motor_kv")),
        "battery": _safe_str(hw.get("battery")),
        "weight": _safe_str(hw.get("weight")),
        "style": _safe_str(ui.get("style")),
        "goals": goals,
        "hardware_sources": hs,
        "hardware_source": aggregate_hardware_source_from_sources(hs),
    }
    if derived_frame_size_source:
        out["frame_size_source"] = derived_frame_size_source
    if hw and hw.get("motor_poles") is not None:
        out["motor_poles"] = hw.get("motor_poles")
    _mps = _hardware_source_for_field(hw, "motor_poles", ("pole_pairs",))
    if _mps:
        out["motor_poles_source"] = _mps
    if hw and hw.get("motor_poles_confirmed") is True and _mps != "default":
        out["motor_poles_confirmed"] = True
    _ps = _hardware_source_for_field(hw, "prop_size", ("prop", "prop_diameter"))
    if _ps:
        out["prop_size_source"] = _ps
    _prop_size = hw.get("prop_size") if hw else None
    if _prop_size is not None:
        out["prop_size"] = _prop_size
    _mv = hw.get("motor_kv_value")
    if isinstance(_mv, int) and _mv > 0:
        out["motor_kv_value"] = _mv
    _cells = hw.get("cells")
    if isinstance(_cells, int) and 1 <= _cells <= 12:
        out["cells"] = _cells
    _pvest = hw.get("pack_voltage_estimate_v")
    if isinstance(_pvest, (int, float)) and math.isfinite(float(_pvest)):
        out["pack_voltage_estimate_v"] = round(float(_pvest), 2)
    _hc = hw.get("hardware_confidence")
    if isinstance(_hc, (int, float)) and math.isfinite(float(_hc)):
        out["hardware_confidence"] = round(float(max(0.0, min(1.0, float(_hc)))), 3)
    _hn = hw.get("hardware_normalized")
    if isinstance(_hn, dict):
        out["hardware_normalized"] = _hn
    _hp = hw.get("hardware_plausibility")
    if isinstance(_hp, dict):
        out["hardware_plausibility"] = _hp
    return out


def _hf_ratio(engine_metrics: dict[str, Any] | None) -> float | None:
    if not isinstance(engine_metrics, dict):
        return None
    nb = engine_metrics.get("noise")
    if not isinstance(nb, dict):
        return None
    r = nb.get("hf_ratio")
    try:
        v = float(r)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    return max(0.0, min(1.0, v))


def _hf_proxy_from_signal_analysis(signal_analysis: dict[str, Any] | None) -> float | None:
    """HF energy share when engine ``hf_ratio`` is not built yet (FFT bundle only)."""
    sa = signal_analysis if isinstance(signal_analysis, dict) else {}
    try:
        te = float(sa.get("total_energy") or 0.0)
    except (TypeError, ValueError):
        te = 0.0
    if te <= 0.0:
        return None
    try:
        hf_e = float(sa.get("hf_energy") or 0.0)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, hf_e / te))


def classify_detected_hardware_signal_tier(
    *,
    uncorrected_merged_gyro_hz: float | None,
    corrected_gyro_hz: float | None,
    rpm_alignment: Any,
    hf_ratio: float | None,
    erpm_hz: float | None,
    erpm_conf_raw: float | None,
) -> str:
    """
    ``high`` | ``medium`` | ``low`` for signal-aware scaling when hardware is log-inferred.

    Priority: missing merged gyro line or RPM alignment → ``low``; very low HF texture → ``low``;
    weak HF or weak ERPM confidence → at least ``medium``.
    """
    merged_ok = False
    if uncorrected_merged_gyro_hz is not None:
        try:
            m = float(uncorrected_merged_gyro_hz)
            merged_ok = math.isfinite(m) and m > 0.0
        except (TypeError, ValueError):
            merged_ok = False
    rpm_ok = isinstance(rpm_alignment, dict) and bool(rpm_alignment)
    gyro_line_ok = _corrected_gyro_hz_valid(corrected_gyro_hz)

    if not merged_ok:
        return "low"
    if not rpm_ok:
        return "low"
    if hf_ratio is not None and hf_ratio < 0.15:
        return "low"
    if hf_ratio is not None and hf_ratio < 0.22:
        return "medium"
    try:
        ec = float(erpm_conf_raw) if erpm_conf_raw is not None else None
    except (TypeError, ValueError):
        ec = None
    if ec is not None and (not math.isfinite(ec) or ec < 0.42):
        return "medium"
    if not gyro_line_ok:
        if erpm_hz is None:
            return "medium"
        try:
            ez = float(erpm_hz)
        except (TypeError, ValueError):
            return "medium"
        if not math.isfinite(ez) or ez <= 0.0:
            return "medium"
    return "high"


def build_hardware_signal_bundle_for_adjust(
    *,
    user_inputs: dict[str, Any] | None,
    signal_analysis: dict[str, Any] | None,
    erpm_analysis: dict[str, Any] | None,
    samples: list[dict] | None,
    engine_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build signals used for adaptive ``detected`` confidence (unified score + frame/RPM heuristics).
    """
    ui = user_inputs if isinstance(user_inputs, dict) else {}
    ic = build_input_context(ui)
    ea = erpm_analysis if isinstance(erpm_analysis, dict) else {}
    try:
        raw_erpm_conf = float(ea.get("confidence") or 0.0)
    except (TypeError, ValueError):
        raw_erpm_conf = None
    dom_motor = ea.get("dominant_frequency")
    try:
        erpm_hz = float(dom_motor) if dom_motor is not None else None
    except (TypeError, ValueError):
        erpm_hz = None
    if erpm_hz is not None and (not math.isfinite(erpm_hz) or erpm_hz <= 0):
        erpm_hz = None

    kv = _parse_kv_ui(ic.get("motor_kv"))
    cells = _parse_battery_cells_ui(ic.get("battery"))
    bat_v = _nominal_battery_voltage_ui(cells)
    thr_avg, thr_p95 = _throttle_avg_p95_from_samples(
        samples if isinstance(samples, list) else None,
    )
    pole_pairs = _resolve_motor_pole_pairs_from_context(ic)
    unc_merged, gyro_meta = compute_merged_gyro_hz_for_frame_detection(
        signal_analysis,
        kv=kv,
        battery_voltage_v=bat_v,
        throttle_avg=thr_avg,
        throttle_p95=thr_p95,
        erpm_dom_hz=erpm_hz,
        pole_pairs=pole_pairs,
    )
    rpm_al = (
        gyro_meta.get("rpm_alignment")
        if isinstance(gyro_meta, dict)
        else None
    )
    corr_hz, _ = apply_rpm_harmonic_correction_for_frame_detection(
        unc_merged,
        rpm_al if isinstance(rpm_al, dict) else None,
    )
    hf_used = _hf_ratio(engine_metrics)
    if hf_used is None:
        hf_used = _hf_proxy_from_signal_analysis(signal_analysis)

    tier = classify_detected_hardware_signal_tier(
        uncorrected_merged_gyro_hz=unc_merged,
        corrected_gyro_hz=corr_hz,
        rpm_alignment=rpm_al,
        hf_ratio=hf_used,
        erpm_hz=erpm_hz,
        erpm_conf_raw=raw_erpm_conf,
    )
    merged_ok = False
    if unc_merged is not None:
        try:
            mf = float(unc_merged)
            merged_ok = math.isfinite(mf) and mf > 0.0
        except (TypeError, ValueError):
            merged_ok = False
    rpm_ok = isinstance(rpm_al, dict) and bool(rpm_al)
    return {
        "detected_quality": tier,
        "merged_gyro_hz_ok": merged_ok,
        "rpm_alignment_present": rpm_ok,
        "hf_ratio_used": hf_used,
        "erpm_hz_present": erpm_hz is not None,
    }


def _dominant_peak_freq_hz_from_axis_block(
    block: Any,
) -> tuple[float | None, dict[str, Any]]:
    """
    Strongest FFT peak (Hz) on one gyro axis from peaks with ``freq`` / ``frequency_hz`` >= 80 Hz.

    Returns ``(selected_hz | None, debug)`` with raw/filtered counts and selected frequency.
    """
    dbg: dict[str, Any] = {
        "min_freq_hz": GYRO_AXIS_PEAK_MIN_HZ,
        "raw_peak_count": 0,
        "filtered_peak_count_ge_min": 0,
        "selected_peak_freq_hz": None,
    }
    if not isinstance(block, dict):
        return None, dbg
    peaks = block.get("peaks") or []
    if not isinstance(peaks, list) or not peaks:
        return None, dbg

    dbg["raw_peak_count"] = sum(1 for p in peaks if isinstance(p, dict))

    valid: list[tuple[float, float]] = []
    for p in peaks:
        if not isinstance(p, dict):
            continue
        raw_f = p.get("frequency_hz")
        if raw_f is None:
            raw_f = p.get("freq")
        try:
            f = float(raw_f) if raw_f is not None else float("nan")
            a = float(p.get("amplitude", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(f) or not math.isfinite(a) or f < GYRO_AXIS_PEAK_MIN_HZ:
            continue
        valid.append((f, a))

    dbg["filtered_peak_count_ge_min"] = len(valid)

    if not valid:
        _LOG.debug(
            "gyro_axis_fft: no_peak_ge_%.0f_Hz raw_peak_count=%s",
            GYRO_AXIS_PEAK_MIN_HZ,
            dbg["raw_peak_count"],
        )
        return None, dbg

    best_f, _ = max(valid, key=lambda t: t[1])
    sel = round(float(best_f), 3)
    dbg["selected_peak_freq_hz"] = sel
    _LOG.debug(
        "gyro_axis_fft: filtered_peak_count_ge_min=%s selected_peak_hz=%.3f",
        len(valid),
        sel,
    )
    return sel, dbg


def _parse_kv_ui(kv_raw: Any) -> float | None:
    if kv_raw is None:
        return None
    s = str(kv_raw).strip().lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    return v


def _parse_battery_cells_ui(bat_raw: Any) -> int | None:
    if bat_raw is None:
        return None
    s = str(bat_raw).strip().lower()
    m = re.search(r"(\d+)\s*s\b", s)
    if not m:
        return None
    try:
        n = int(m.group(1))
    except (TypeError, ValueError):
        return None
    if 1 <= n <= 12:
        return n
    return None


def _nominal_battery_voltage_ui(cells: int | None) -> float | None:
    if cells is None:
        return None
    return round(float(cells) * 3.7, 2)


def _linear_p95(sorted_vals: list[float]) -> float:
    n = len(sorted_vals)
    if n == 0:
        return float("nan")
    if n == 1:
        return float(sorted_vals[0])
    idx = (n - 1) * 0.95
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo >= hi:
        return float(sorted_vals[min(lo, n - 1)])
    t = idx - lo
    return float(sorted_vals[lo] * (1.0 - t) + sorted_vals[hi] * t)


def _throttle_avg_p95_from_samples(samples: list[dict] | None) -> tuple[float | None, float | None]:
    """Normalized 0–1 throttle mean and ~p95 (same scaling as frame debug)."""
    if not isinstance(samples, list) or not samples:
        return None, None
    raw_vals: list[float] = []
    for s in samples:
        if not isinstance(s, dict):
            continue
        raw = s.get("throttle")
        if raw is None:
            continue
        try:
            raw_vals.append(float(raw))
        except (TypeError, ValueError):
            continue
    if not raw_vals:
        return None, None
    raw_max = max(raw_vals)
    norm_list: list[float] = []
    for v in raw_vals:
        if raw_max > 1.5:
            norm = (v - 1000.0) / 1000.0
        else:
            norm = v
        norm_list.append(max(0.0, min(1.0, norm)))
    if not norm_list:
        return None, None
    avg = round(float(sum(norm_list) / len(norm_list)), 4)
    p95 = round(_linear_p95(sorted(norm_list)), 4)
    return avg, p95


def _finite_axis_peak_hz(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f <= 0:
        return None
    return f


def _harmonic_axis_peak_ratio_filter(
    ordered_axes_freqs: list[tuple[str, float]],
) -> tuple[list[tuple[str, float]], list[float], list[float], bool]:
    """
    Drop axis peaks that are ~2× or ~3× some **smaller** axis peak (±15% on each integer ratio).

    For peaks ``f, g`` with ``g < f``: if ``f / g ≈ 2`` or ``≈ 3``, treat ``f`` as a harmonic of ``g``.
    The ``f / g ≈ 0.5`` case (larger ``g``) is the same relationship seen from the smaller peak.
    Returns ``(present, original_vals, adjusted_vals, harmonic_filter_applied)``.
    """
    original_vals = [float(f) for _, f in ordered_axes_freqs]
    if len(original_vals) < 2:
        return list(ordered_axes_freqs), list(original_vals), list(original_vals), False

    values = original_vals
    n = len(values)

    def is_harmonic_index(i: int) -> bool:
        f = values[i]
        for j, g in enumerate(values):
            if i == j or g <= 0 or not (g < f):
                continue
            ratio = f / g
            for k in (2, 3):
                if abs(ratio - float(k)) <= 0.15 * float(k):
                    return True
        return False

    is_harmonic = [is_harmonic_index(i) for i in range(n)]
    kept = [ordered_axes_freqs[i] for i in range(n) if not is_harmonic[i]]
    adjusted_vals = [float(f) for _, f in kept]

    if not adjusted_vals:
        return list(ordered_axes_freqs), list(original_vals), list(original_vals), False

    removed = n - len(kept)
    applied = removed > 0
    return kept, list(original_vals), adjusted_vals, applied


def _per_axis_peak_freqs_hz(
    signal_analysis: dict[str, Any] | None,
) -> tuple[dict[str, float | None], dict[str, Any]]:
    axes = (
        (signal_analysis or {}).get("axes")
        if isinstance(signal_analysis, dict)
        else None
    )
    out: dict[str, float | None] = {"roll": None, "pitch": None, "yaw": None}
    selection: dict[str, Any] = {
        "min_freq_hz": GYRO_AXIS_PEAK_MIN_HZ,
        "axes": {},
    }
    if not isinstance(axes, dict):
        return out, selection
    for axis_name in ("roll", "pitch", "yaw"):
        fv, adbg = _dominant_peak_freq_hz_from_axis_block(axes.get(axis_name))
        out[axis_name] = fv
        selection["axes"][axis_name] = adbg
    return out, selection


def _finite_erpm_dom_hz(erpm_dom_hz: Any) -> float | None:
    if erpm_dom_hz is None:
        return None
    try:
        e = float(erpm_dom_hz)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(e) or e <= 0:
        return None
    return e


def _resolve_motor_pole_pairs_from_context(input_context: dict | None) -> float:
    """
    Resolve motor pole pairs from input_context.

    Expected input:
        input_context["motor_poles"] = any positive even integer (e.g. 10, 12, 14, 16, 18)
        input_context["pole_pairs_effective"] = pre-resolved authority (preferred)

    Rules:
    - ``pole_pairs_effective`` from motor_poles authority wins when present
    - n (even, ≥ 2) → n / 2  (10→5, 12→6, 14→7, 16→8, 18→9, …)
    - uploaded CLI present but motor_poles missing → no silent default authority
    - missing / invalid / odd / source=default → fallback to DEFAULT_ERPM_POLE_PAIRS
    - NEVER crash
    """
    if not isinstance(input_context, dict):
        return float(DEFAULT_ERPM_POLE_PAIRS)
    eff = input_context.get("pole_pairs_effective")
    if eff is not None:
        try:
            pp = float(eff)
            if math.isfinite(pp) and pp > 0:
                return pp
        except (TypeError, ValueError):
            pass
    if (
        input_context.get("uploaded_cli_present") is True
        and input_context.get("motor_poles_authority") == "missing_from_uploaded_cli"
    ):
        return float(DEFAULT_ERPM_POLE_PAIRS)
    if _normalize_hardware_source(input_context.get("motor_poles_source")) == "default":
        return float(DEFAULT_ERPM_POLE_PAIRS)
    src = str(input_context.get("motor_poles_source") or "").strip().lower()
    if src in {"cli", "cli_baseline", "uploaded_cli", "uploaded_cli_dump_text", "uploaded_cli_tune"}:
        raw_cli = input_context.get("motor_poles")
        if raw_cli is not None and not isinstance(raw_cli, bool):
            try:
                n = int(float(raw_cli))
            except (TypeError, ValueError):
                n = 0
            if n >= 2 and n % 2 == 0:
                return float(n) / 2.0
    raw = input_context.get("motor_poles")
    if raw is None:
        return float(DEFAULT_ERPM_POLE_PAIRS)
    if isinstance(raw, bool):
        return float(DEFAULT_ERPM_POLE_PAIRS)
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        return float(DEFAULT_ERPM_POLE_PAIRS)
    if n >= 2 and n % 2 == 0:
        return float(n) / 2.0
    return float(DEFAULT_ERPM_POLE_PAIRS)


def pole_pairs_metadata_from_context(input_context: dict | None) -> dict[str, Any]:
    """
    Additive pole-pair provenance for ERPM→mechanical Hz (does not change pair resolution math).
    """
    pp = float(_resolve_motor_pole_pairs_from_context(input_context))
    out: dict[str, Any] = {
        "pole_pairs": pp,
        "pole_pairs_source": "default_fallback",
        "pole_count": None,
        "motor_poles_confirmed": None,
    }
    if not isinstance(input_context, dict):
        return out
    for key in (
        "cli_motor_poles",
        "motor_poles_effective",
        "pole_pairs_effective",
        "motor_poles_source",
        "motor_poles_authority",
        "motor_poles_authority_reason",
        "rpm_alignment_source",
        "fallback_motor_poles",
        "motor_poles_pipeline_issue",
    ):
        if key in input_context:
            out[key] = input_context.get(key)
    auth = str(input_context.get("motor_poles_authority") or "").strip().lower()
    if auth == "uploaded_cli":
        out["pole_pairs_source"] = "cli_motor_poles"
    elif auth == "user_confirmed":
        out["pole_pairs_source"] = "user_motor_poles"
    if "motor_poles_confirmed" in input_context:
        out["motor_poles_confirmed"] = input_context.get("motor_poles_confirmed")
    if _normalize_hardware_source(input_context.get("motor_poles_source")) == "default":
        out["motor_poles_source"] = "default"
        return out
    raw = input_context.get("motor_poles")
    if raw is None:
        return out
    if isinstance(raw, bool):
        return out
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        return out
    if n >= 2 and n % 2 == 0:
        out["pole_count"] = n
        if out.get("pole_pairs_source") == "default_fallback":
            out["pole_pairs_source"] = "user_motor_poles"
    return out


def _effective_erpm_pole_pairs(pole_pairs: float | None) -> float:
    """Use caller pole_pairs when finite and positive; else DEFAULT_ERPM_POLE_PAIRS."""
    if pole_pairs is None:
        return float(DEFAULT_ERPM_POLE_PAIRS)
    try:
        pf = float(pole_pairs)
    except (TypeError, ValueError):
        return float(DEFAULT_ERPM_POLE_PAIRS)
    if not math.isfinite(pf) or pf <= 0:
        return float(DEFAULT_ERPM_POLE_PAIRS)
    return pf


def _erpm_electrical_hz_to_motor_hz(
    erpm_electrical_hz: float,
    *,
    pole_pairs: float = DEFAULT_ERPM_POLE_PAIRS,
) -> float | None:
    """Electrical ERPM line frequency (Hz) → mechanical fundamental (Hz)."""
    if not math.isfinite(erpm_electrical_hz) or erpm_electrical_hz <= 0:
        return None
    try:
        pp = float(pole_pairs)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(pp) or pp <= 0:
        return None
    return erpm_electrical_hz / pp


def _gyro_hz_corrected_with_motor_fundamental(
    gyro_hz: float | None,
    signal_analysis: dict[str, Any] | None,
    *,
    min_fundamental_confidence: float = 0.42,
) -> tuple[float | None, dict[str, Any]]:
    """
    If merged gyro Hz sits on a strong FFT harmonic line (2f–4f), snap to inferred fundamental f0.

    Uses merged ``fft_peaks`` harmonic structure so frame bucketing is not biased by 2×/3× motor lines.
    """
    empty_meta = {
        "fundamental_hz": None,
        "harmonic_count": 0,
        "confidence": 0.0,
    }
    indexed = fft_peaks_indexed_from_signal_analysis(signal_analysis)
    est = estimate_motor_fundamental_from_fft_peaks_indexed(indexed)
    meta = {**empty_meta, **est} if isinstance(est, dict) else empty_meta
    try:
        conf = float(meta.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    raw_f0 = meta.get("fundamental_hz")
    try:
        f0 = float(raw_f0) if raw_f0 is not None else None
    except (TypeError, ValueError):
        f0 = None
    if f0 is None or not math.isfinite(f0) or f0 <= 0 or conf < min_fundamental_confidence:
        return gyro_hz, meta
    if gyro_hz is None:
        return round(f0, 3), meta
    try:
        g = float(gyro_hz)
    except (TypeError, ValueError):
        return gyro_hz, meta
    if not math.isfinite(g) or g <= 0:
        return gyro_hz, meta
    for k in (2, 3, 4):
        target = f0 * float(k)
        tol = max(6.0, min(16.0, 0.032 * max(g, target)))
        if abs(g - target) <= tol:
            return round(f0, 3), meta
    return gyro_hz, meta


def apply_rpm_harmonic_correction_for_frame_detection(
    gyro_hz: float | None,
    rpm_alignment: dict[str, Any] | None,
) -> tuple[float | None, bool]:
    """
    Apply KV/RPM harmonic correction (÷2 or ×2) to merged gyro Hz for **frame** bucketing only.

    Uses ``rpm_alignment`` from ``rpm_alignment_for_merged_gyro_hz`` (``harmonic_match``, ``ratio``).
    ERPM analysis and HF ratio are unchanged elsewhere.
    """
    corrected_gyro_hz = gyro_hz
    harmonic_corrected = False
    if gyro_hz is None or not isinstance(rpm_alignment, dict):
        return corrected_gyro_hz, harmonic_corrected
    ratio = rpm_alignment.get("ratio")
    harmonic = rpm_alignment.get("harmonic_match")
    if harmonic and ratio is not None:
        try:
            r = float(ratio)
        except (TypeError, ValueError):
            return corrected_gyro_hz, harmonic_corrected
        if not math.isfinite(r):
            return corrected_gyro_hz, harmonic_corrected
        try:
            g = float(gyro_hz)
        except (TypeError, ValueError):
            return corrected_gyro_hz, harmonic_corrected
        if not math.isfinite(g) or g <= 0:
            return corrected_gyro_hz, harmonic_corrected
        if 1.8 <= r <= 2.2:
            corrected_gyro_hz = g / 2.0
            harmonic_corrected = True
        elif 0.45 <= r <= 0.6:
            corrected_gyro_hz = g * 2.0
            harmonic_corrected = True
    if corrected_gyro_hz is not None:
        try:
            cg = float(corrected_gyro_hz)
        except (TypeError, ValueError):
            return gyro_hz, False
        if math.isfinite(cg) and cg > 0:
            corrected_gyro_hz = round(cg, 3)
        else:
            corrected_gyro_hz = None
    return corrected_gyro_hz, harmonic_corrected


def _erpm_confirms_gyro_peak(
    gyro_hz: float,
    erpm_electrical_hz: float,
    pole_pairs: float,
    erpm_confidence: float,
    erpm_scale_assumption: str,
    *,
    max_relative_delta: float = 0.08,
    min_erpm_confidence: float = 0.65,
) -> bool:
    """
    True when ERPM telemetry independently confirms the gyro motor-noise peak.

    Used to suppress KV/throttle-model ratio mismatches when two independent
    sensors agree.  Caller must NOT call this when the merged gyro Hz was
    derived from ERPM (gyro_hz_fallback == "erpm_dominant") — in that case
    there is no independent gyro signal and the check would be circular.
    """
    if not (math.isfinite(gyro_hz) and gyro_hz > 0):
        return False
    if not (math.isfinite(erpm_electrical_hz) and erpm_electrical_hz > 0):
        return False
    if not (math.isfinite(pole_pairs) and pole_pairs > 0):
        return False
    erpm_motor_hz = erpm_electrical_hz / pole_pairs
    denom = max(erpm_motor_hz, gyro_hz, 1e-6)
    if abs(erpm_motor_hz - gyro_hz) / denom > max_relative_delta:
        return False
    if erpm_scale_assumption in {"ambiguous", "unknown", "conflicting"}:
        return False
    return math.isfinite(erpm_confidence) and erpm_confidence >= min_erpm_confidence


def _finalize_merged_gyro_hz_pipeline(
    merged: float,
    signal_analysis: dict[str, Any] | None,
    meta: dict[str, Any],
    *,
    kv: Any,
    battery_voltage_v: Any,
    throttle_avg: Any,
    throttle_p95: Any,
) -> float | None:
    # Raw merged motor-line Hz (median / ERPM fallback) before FFT-fundamental snap — used only
    # for frame bucket ordinal mapping, not for rpm_alignment / debug motor fundamental fields.
    try:
        _raw_m = float(merged)
    except (TypeError, ValueError):
        meta["gyro_primary_hz_for_frame_ordinal"] = None
    else:
        meta["gyro_primary_hz_for_frame_ordinal"] = (
            round(_raw_m, 3)
            if math.isfinite(_raw_m) and _raw_m > 0.0
            else None
        )

    merged_corr, fund_meta = _gyro_hz_corrected_with_motor_fundamental(
        merged,
        signal_analysis,
    )
    meta["motor_fundamental_fft"] = fund_meta
    meta["merged_hz_for_frame_model"] = (
        round(float(merged_corr), 3)
        if merged_corr is not None and math.isfinite(float(merged_corr))
        else None
    )

    align, rpm_mismatch = rpm_alignment_for_merged_gyro_hz(
        float(merged_corr) if merged_corr is not None else None,
        kv,
        battery_voltage_v,
        throttle_avg,
        throttle_p95,
    )
    meta["rpm_alignment"] = align
    meta["rpm_mismatch"] = bool(rpm_mismatch)

    if merged_corr is not None:
        try:
            mv = float(merged_corr)
        except (TypeError, ValueError):
            return None
        if math.isfinite(mv) and mv > 0:
            return round(mv, 3)
    return None


def compute_merged_gyro_hz_for_frame_detection(
    signal_analysis: dict[str, Any] | None,
    *,
    outlier_threshold_hz: float = 50.0,
    kv: Any = None,
    battery_voltage_v: Any = None,
    throttle_avg: Any = None,
    throttle_p95: Any = None,
    erpm_dom_hz: Any = None,
    pole_pairs: float | None = None,
) -> tuple[float | None, dict[str, Any]]:
    """
    Single merged gyro Hz for frame bucketing: **only** per-axis FFT peaks (roll/pitch/yaw).

    Peaks below ``GYRO_AXIS_PEAK_MIN_HZ`` (80 Hz) are ignored so frame noise (~20–60 Hz) is not
    mistaken for motor lines. If no axis yields a peak in the motor band, ``erpm_dom_hz``
    (electrical Hz) may be used as a fallback: it is converted to mechanical Hz as
    ``erpm_dom_hz / pole_pairs`` (``pole_pairs`` or ``DEFAULT_ERPM_POLE_PAIRS``) before merge;
    the converted value must be
    ``>= GYRO_AXIS_PEAK_MIN_HZ``. Otherwise the merged gyro Hz is ``None``.

    Harmonic guard: before outlier filtering, drops any peak that is ~2× or ~3× another **smaller**
    axis peak (±15% on the integer ratio), then runs the existing median / outlier pass on the
    remaining peaks. If filtering would remove everything, the original peaks are restored.

    When KV / battery / throttle inputs are supplied, ``rpm_alignment`` may flag a KV/RPM harmonic
    (``harmonic_match`` / ``ratio``). The returned merged Hz is after motor-fundamental FFT snap
    (for ``rpm_alignment`` / debug). ``gyro_primary_hz_for_frame_ordinal`` in meta is the raw
    merged line before that snap; frame ordinal mapping uses that primary Hz, not harmonic-corrected
    or fundamental-snapped values. ``merged_hz_for_frame_model`` remains **debug only**.
    """
    _eff_pp = _effective_erpm_pole_pairs(pole_pairs)
    peaks, peak_sel = _per_axis_peak_freqs_hz(signal_analysis)
    r0, p0, y0 = peaks["roll"], peaks["pitch"], peaks["yaw"]

    ordered: list[tuple[str, float]] = []
    for ax, raw in (("roll", r0), ("pitch", p0), ("yaw", y0)):
        fv = _finite_axis_peak_hz(raw)
        if fv is not None:
            ordered.append((ax, float(fv)))

    original_axis_peaks = [f for _, f in ordered]
    harmonic_filter_applied = False
    if len(ordered) < 2:
        present = list(ordered)
        adjusted_axis_peaks = list(original_axis_peaks)
    else:
        present, original_axis_peaks, adjusted_axis_peaks, harmonic_filter_applied = (
            _harmonic_axis_peak_ratio_filter(ordered)
        )

    axis_peaks_hz: dict[str, float | None] = {"roll": None, "pitch": None, "yaw": None}
    for ax, f in present:
        axis_peaks_hz[ax] = round(float(f), 3)

    meta: dict[str, Any] = {
        "axis_peaks_hz": axis_peaks_hz,
        "method": "median_of_filtered_axis_fft_peaks",
        "outlier_threshold_hz": outlier_threshold_hz,
        "axis_values_used_after_filter": [],
        "dropped_axes": [],
        "filter_note": None,
        "merged_hz_for_frame_model": None,
        "motor_fundamental_fft": None,
        "original_axis_peaks": list(original_axis_peaks),
        "adjusted_axis_peaks": list(adjusted_axis_peaks),
        "harmonic_filter_applied": bool(harmonic_filter_applied),
        "rpm_alignment": None,
        "rpm_mismatch": False,
        "gyro_fft_peak_selection": peak_sel,
        "gyro_primary_hz_for_frame_ordinal": None,
    }

    if not present:
        erpm_elec = _finite_erpm_dom_hz(erpm_dom_hz)
        motor_fb: float | None = None
        if erpm_elec is not None:
            motor_fb = _erpm_electrical_hz_to_motor_hz(
                float(erpm_elec),
                pole_pairs=_eff_pp,
            )
        if (
            erpm_elec is not None
            and motor_fb is not None
            and math.isfinite(motor_fb)
            and motor_fb >= GYRO_AXIS_PEAK_MIN_HZ
        ):
            meta["gyro_hz_fallback"] = "erpm_dominant"
            meta["gyro_hz_fallback_erpm_electrical_hz"] = round(float(erpm_elec), 3)
            meta["gyro_hz_fallback_pole_pairs"] = int(round(_eff_pp))
            meta["gyro_hz_fallback_motor_hz"] = round(float(motor_fb), 3)
            meta["filter_note"] = "no_axis_peaks_ge_min_hz_used_erpm_dominant"
            _LOG.info(
                "gyro_fft merged_gyro: erpm_fallback erpm_electrical_hz=%s pole_pairs=%s "
                "motor_hz=%s",
                meta["gyro_hz_fallback_erpm_electrical_hz"],
                meta["gyro_hz_fallback_pole_pairs"],
                meta["gyro_hz_fallback_motor_hz"],
            )
            merged_out = _finalize_merged_gyro_hz_pipeline(
                float(motor_fb),
                signal_analysis,
                meta,
                kv=kv,
                battery_voltage_v=battery_voltage_v,
                throttle_avg=throttle_avg,
                throttle_p95=throttle_p95,
            )
            _LOG.info(
                "gyro_fft merged_gyro: erpm_fallback merged_out_hz=%s "
                "filtered_peak_counts roll=%s pitch=%s yaw=%s",
                merged_out,
                peak_sel["axes"].get("roll", {}).get("filtered_peak_count_ge_min"),
                peak_sel["axes"].get("pitch", {}).get("filtered_peak_count_ge_min"),
                peak_sel["axes"].get("yaw", {}).get("filtered_peak_count_ge_min"),
            )
            return merged_out, meta

        align, rmm = rpm_alignment_for_merged_gyro_hz(
            None, kv, battery_voltage_v, throttle_avg, throttle_p95
        )
        meta["rpm_alignment"] = align
        meta["rpm_mismatch"] = bool(rmm)
        _LOG.info(
            "gyro_fft merged_gyro: no_valid_axis_peaks merged_hz=None "
            "filtered_peak_counts roll=%s pitch=%s yaw=%s",
            peak_sel["axes"].get("roll", {}).get("filtered_peak_count_ge_min"),
            peak_sel["axes"].get("pitch", {}).get("filtered_peak_count_ge_min"),
            peak_sel["axes"].get("yaw", {}).get("filtered_peak_count_ge_min"),
        )
        return None, meta

    freqs = [f for _, f in present]
    med0 = float(statistics.median(freqs))
    kept = [(ax, f) for ax, f in present if abs(f - med0) <= outlier_threshold_hz]
    dropped = [ax for ax, f in present if abs(f - med0) > outlier_threshold_hz]

    if not kept:
        merged = med0
        meta["axis_values_used_after_filter"] = list(freqs)
        meta["dropped_axes"] = [ax for ax, _ in present]
        meta["filter_note"] = "all_axes_outliers_vs_median_using_full_median"
    else:
        kept_freqs = [f for _, f in kept]
        merged = float(statistics.median(kept_freqs))
        meta["axis_values_used_after_filter"] = kept_freqs
        meta["dropped_axes"] = dropped

    merged_out = _finalize_merged_gyro_hz_pipeline(
        merged,
        signal_analysis,
        meta,
        kv=kv,
        battery_voltage_v=battery_voltage_v,
        throttle_avg=throttle_avg,
        throttle_p95=throttle_p95,
    )
    _LOG.info(
        "gyro_fft merged_gyro: axis_peaks=%s merged_selected_hz=%s "
        "filtered_peak_counts roll=%s pitch=%s yaw=%s",
        axis_peaks_hz,
        merged_out,
        peak_sel["axes"].get("roll", {}).get("filtered_peak_count_ge_min"),
        peak_sel["axes"].get("pitch", {}).get("filtered_peak_count_ge_min"),
        peak_sel["axes"].get("yaw", {}).get("filtered_peak_count_ge_min"),
    )
    return merged_out, meta


def _corrected_gyro_hz_valid(corrected_gyro_hz: float | None) -> bool:
    if corrected_gyro_hz is None:
        return False
    try:
        g = float(corrected_gyro_hz)
    except (TypeError, ValueError):
        return False
    return math.isfinite(g) and g > 0.0


def _frame_erpm_weights_from_sources(
    hardware_sources: Mapping[str, Any] | None,
) -> tuple[float, float]:
    """Returns ``(weight_gyro, weight_erpm)`` in ``(0, 1]`` for signal trust."""
    wg = 1.0
    we = 1.0
    if not isinstance(hardware_sources, dict):
        return wg, we
    if str(hardware_sources.get("frame") or "user") != "user":
        wg *= 0.9
    if str(hardware_sources.get("motor_kv") or "user") != "user":
        we *= 0.8
    return wg, we


def _weighted_frame_ordinal_and_source(
    o_gyro: int,
    o_erpm: int,
    weight_gyro: float,
    weight_erpm: float,
) -> tuple[int, str]:
    """Vote ordinals by hardware-weighted evidence; tie-break toward higher ERPM weight."""
    votes: dict[int, float] = {0: 0.0, 1: 0.0, 2: 0.0}
    votes[o_gyro] += max(0.0, weight_gyro)
    votes[o_erpm] += max(0.0, weight_erpm)
    max_v = max(votes.values())
    candidates = [k for k in (0, 1, 2) if votes[k] >= max_v - 1e-12]
    if len(candidates) == 1:
        win = candidates[0]
    else:
        g_at = votes[o_gyro] if o_gyro in candidates else -1.0
        e_at = votes[o_erpm] if o_erpm in candidates else -1.0
        if e_at > g_at:
            win = o_erpm
        elif g_at > e_at:
            win = o_gyro
        else:
            win = o_erpm if weight_erpm >= weight_gyro else o_gyro
    g_win = max(0.0, weight_gyro) if o_gyro == win else 0.0
    e_win = max(0.0, weight_erpm) if o_erpm == win else 0.0
    if e_win > g_win:
        src = "erpm"
    elif g_win > e_win:
        src = "gyro"
    else:
        src = "erpm" if weight_erpm >= weight_gyro else "gyro"
    return win, src


def _ordinal_from_primary_line_hz(
    primary_hz: float,
    *,
    allow_high_line_micro: bool,
) -> int:
    """
    Map one dominant line frequency (Hz) to frame ordinal 0..2.

    Bands: ``>=380`` Hz → micro, ``>=140`` Hz → 5\", else 7\"+.
    ``allow_high_line_micro`` is kept for call-site compatibility; micro is only from ``>=380``.
    """
    _ = allow_high_line_micro
    # Real-world motor-line bands: micro very high Hz; 5" mid-high; 7"+ lower Hz.
    if primary_hz >= 380.0:
        return 0  # micro (2–3")
    if primary_hz >= 140.0:
        return 1  # 5"
    return 2  # 7"+


def _motor_hz_explainable_for_hw(
    observed_hz: float,
    kv: float,
    vbat: float,
    *,
    throttle_min: float = 0.20,
    throttle_max: float = 0.90,
) -> bool:
    """True when observed motor Hz falls in the KV×Vbat operating range at typical throttle.

    Used to distinguish a genuine frame-ordinal conflict (observed Hz outside what the
    declared KV/cells can produce at any sane throttle) from a frequency-band artifact
    (high-KV or large-frame motor whose operating point happens to land in an adjacent
    Hz band at the log's actual throttle).  throttle_min=0.20 avoids matching idle
    spoolup; throttle_max=0.90 caps at near-full.
    """
    if not (math.isfinite(observed_hz) and observed_hz > 0):
        return False
    if not (math.isfinite(kv) and kv > 0 and math.isfinite(vbat) and vbat > 0):
        return False
    expected_low = kv * vbat * throttle_min / 60.0
    expected_high = kv * vbat * throttle_max / 60.0
    return expected_low <= observed_hz <= expected_high


def _gyro_erpm_frame_summary_empty() -> dict[str, Any]:
    return {
        "gyro_ordinal": None,
        "erpm_ordinal": None,
        "agreement": None,
        "conflict_resolution": None,
        "gyro_hz": None,
        "erpm_motor_hz": None,
        "ratio": None,
    }


def _is_plausible_high_harmonic_correction(raw_hz: Any, corrected_hz: Any) -> bool:
    """True when raw Hz is conservatively near 2x, 3x, or 4x the corrected line."""
    try:
        raw = float(raw_hz)
        corrected = float(corrected_hz)
    except (TypeError, ValueError):
        return False
    if (
        not math.isfinite(raw)
        or not math.isfinite(corrected)
        or raw <= 0.0
        or corrected <= 0.0
        or corrected >= raw
    ):
        return False
    for harmonic in (2, 3, 4):
        target = corrected * float(harmonic)
        tol = max(6.0, min(16.0, 0.032 * max(raw, target)))
        if abs(raw - target) <= tol:
            return True
    return False


def _estimate_frame_ordinal(
    erpm_dom_hz: float | None,
    corrected_gyro_hz: float | None,
    hf_ratio: float | None,
    erpm_confidence: float | None,
    *,
    harmonic_match: Any = None,
    hardware_sources: Mapping[str, Any] | None = None,
    pole_pairs: float | None = None,
    gyro_primary_hz: float | None = None,
) -> tuple[int, float, str, dict[str, Any]]:
    """
    Frame ordinal 0..2 (micro..7+) and confidence 0..1.

    Gyro and ERPM mechanical lines both use ``_ordinal_from_primary_line_hz`` with
    ``allow_high_line_micro=False`` so the same Hz maps to the same bucket. When harmonic/fundamental
    correction moves a raw high gyro line downward, the corrected line drives the frame ordinal;
    otherwise the raw ``gyro_primary_hz`` remains the ordinal input.

    When both lines exist: if ordinals agree, that ordinal is used (``frame_model_source`` is
    ``\"gyro\"``). On disagreement, if the gyro primary line and ERPM mechanical Hz are far apart
    (relative mismatch > 32%), the gyro bucket wins; otherwise ERPM's ordinal wins (legacy tie-break).

    If only one line exists, it alone selects the ordinal. ``harmonic_match`` may reduce
    confidence but never removes ERPM from ordinal selection when ``erpm_motor_primary`` exists.

    ``erpm_dom_hz`` is **electrical** Hz; ``erpm_motor_primary`` is mechanical via
    ``/ pole_pairs`` (or ``DEFAULT_ERPM_POLE_PAIRS``).

    Returns ``(ordinal, confidence, frame_model_source, inference_meta)`` where
    ``frame_model_source`` is ``\"gyro\"`` or ``\"erpm\"``, and ``inference_meta`` is additive-only.
    """
    _eff_pp = _effective_erpm_pole_pairs(pole_pairs)
    weight_gyro, weight_erpm = _frame_erpm_weights_from_sources(hardware_sources)
    gyro_ok = _corrected_gyro_hz_valid(corrected_gyro_hz)
    harmonic_match_flag = bool(harmonic_match)

    inference_mode = "unknown"
    reason_codes: list[str] = []
    gyro_erpm_summary = _gyro_erpm_frame_summary_empty()

    if _corrected_gyro_hz_valid(corrected_gyro_hz) and _corrected_gyro_hz_valid(
        gyro_primary_hz
    ):
        try:
            corr_for_ord = float(corrected_gyro_hz)  # type: ignore[arg-type]
            raw_for_ord = float(gyro_primary_hz)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            corr_for_ord = raw_for_ord = float("nan")
        if (
            math.isfinite(corr_for_ord)
            and math.isfinite(raw_for_ord)
            and abs(corr_for_ord - raw_for_ord) > 1e-6
            and corr_for_ord < raw_for_ord
            and _is_plausible_high_harmonic_correction(raw_for_ord, corr_for_ord)
        ):
            gyro_hz_for_ordinal = corr_for_ord
            reason_codes.append("gyro_harmonic_corrected_for_frame_ordinal")
        else:
            gyro_hz_for_ordinal = raw_for_ord
    elif _corrected_gyro_hz_valid(gyro_primary_hz):
        gyro_hz_for_ordinal = float(gyro_primary_hz)  # type: ignore[arg-type]
    elif _corrected_gyro_hz_valid(corrected_gyro_hz):
        gyro_hz_for_ordinal = float(corrected_gyro_hz)  # type: ignore[arg-type]
    else:
        gyro_hz_for_ordinal = None
    if gyro_hz_for_ordinal is not None:
        _LOG.debug("gyro_hz_used_for_frame=%s", gyro_hz_for_ordinal)

    erpm_motor_primary: float | None = None
    if erpm_dom_hz is not None and erpm_dom_hz > 0 and math.isfinite(float(erpm_dom_hz)):
        em = _erpm_electrical_hz_to_motor_hz(float(erpm_dom_hz), pole_pairs=_eff_pp)
        if em is not None and math.isfinite(em) and em > 0:
            erpm_motor_primary = float(em)

    if gyro_ok and erpm_motor_primary is not None:
        inference_mode = "gyro_erpm"
        reason_codes.append("gyro_erpm_both_signals")
        _g_ord = (
            float(gyro_hz_for_ordinal)
            if gyro_hz_for_ordinal is not None
            else float(corrected_gyro_hz)
        )
        o_gyro = _ordinal_from_primary_line_hz(_g_ord, allow_high_line_micro=False)
        o_erpm = _ordinal_from_primary_line_hz(
            float(erpm_motor_primary), allow_high_line_micro=False
        )
        gyro_erpm_summary["gyro_ordinal"] = int(o_gyro)
        gyro_erpm_summary["erpm_ordinal"] = int(o_erpm)
        gyro_erpm_summary["gyro_hz"] = round(float(_g_ord), 4)
        gyro_erpm_summary["erpm_motor_hz"] = round(float(erpm_motor_primary), 4)
        try:
            g_ln = float(gyro_hz_for_ordinal) if gyro_hz_for_ordinal is not None else float(_g_ord)
            e_ln = float(erpm_motor_primary)
            if math.isfinite(g_ln) and math.isfinite(e_ln):
                denom = max(abs(g_ln), abs(e_ln), 1e-6)
                gyro_erpm_summary["ratio"] = round(abs(g_ln - e_ln) / denom, 4)
        except (TypeError, ValueError):
            pass
        if o_gyro == o_erpm:
            o = o_gyro
            source = "gyro"
            gyro_erpm_summary["agreement"] = True
            gyro_erpm_summary["conflict_resolution"] = None
            reason_codes.append("ordinal_agreement")
            _LOG.debug(
                "frame_model gyro+erpm agree: o=%s src=%s o_gyro=o_erpm=%s",
                o,
                source,
                o_gyro,
            )
        else:
            gyro_erpm_summary["agreement"] = False
            # When the gyro FFT motor line and ERPM mechanical line land in different buckets but
            # the two Hz values are far apart (harmonic / alias / wrong ERPM dominant), the ERPM
            # electrical→mechanical map can disagree with the gyro line; trust the gyro primary Hz
            # bucket. The 32% boundary is a conservative empirical cutoff: <=32% keeps the legacy
            # ERPM tie-break for nearby lines, while >32% treats the disagreement as large enough
            # for the independent gyro primary line to win. Do not tune this without fixture logs.
            use_gyro_on_conflict = False
            if gyro_hz_for_ordinal is not None and erpm_motor_primary is not None:
                try:
                    g_line = float(gyro_hz_for_ordinal)
                    e_line = float(erpm_motor_primary)
                except (TypeError, ValueError):
                    g_line = e_line = float("nan")
                if (
                    math.isfinite(g_line)
                    and math.isfinite(e_line)
                    and g_line >= GYRO_AXIS_PEAK_MIN_HZ
                    and e_line > 0.0
                ):
                    denom = max(g_line, e_line, 1e-6)
                    if abs(g_line - e_line) / denom > 0.32:
                        use_gyro_on_conflict = True
            if use_gyro_on_conflict:
                o = o_gyro
                source = "gyro"
                gyro_erpm_summary["conflict_resolution"] = "gyro_primary_vs_erpm_hz_mismatch"
                reason_codes.append("conflict_resolved_gyro_hz_mismatch")
                _LOG.debug(
                    "frame_model gyro+erpm conflict: o_gyro=%s o_erpm=%s "
                    "frame_conflict_resolved_by=gyro_primary_vs_erpm_hz_mismatch -> o=%s src=%s",
                    o_gyro,
                    o_erpm,
                    o,
                    source,
                )
            else:
                o = o_erpm
                source = "erpm"
                gyro_erpm_summary["conflict_resolution"] = "erpm_tie_break"
                reason_codes.append("conflict_resolved_erpm_tie_break")
                _LOG.debug(
                    "frame_model gyro+erpm conflict: o_gyro=%s o_erpm=%s "
                    "frame_conflict_resolved_by=erpm -> o=%s src=%s",
                    o_gyro,
                    o_erpm,
                    o,
                    source,
                )
    elif erpm_motor_primary is not None:
        inference_mode = "erpm_only"
        reason_codes.append("erpm_mechanical_line_primary")
        _LOG.debug(
            "frame_model erpm_primary: erpm_electrical_hz=%s pole_pairs=%s motor_hz=%s",
            round(float(erpm_dom_hz), 3),
            _eff_pp,
            round(erpm_motor_primary, 3),
        )
        primary = erpm_motor_primary
        o = _ordinal_from_primary_line_hz(primary, allow_high_line_micro=False)
        source = "erpm"
        gyro_erpm_summary["erpm_ordinal"] = int(o)
        gyro_erpm_summary["erpm_motor_hz"] = round(float(erpm_motor_primary), 4)
    elif gyro_ok:
        inference_mode = "gyro_only"
        reason_codes.append("gyro_line_primary")
        primary = (
            float(gyro_hz_for_ordinal)
            if gyro_hz_for_ordinal is not None
            else float(corrected_gyro_hz)
        )
        o = _ordinal_from_primary_line_hz(primary, allow_high_line_micro=False)
        source = "gyro"
        gyro_erpm_summary["gyro_ordinal"] = int(o)
        gyro_erpm_summary["gyro_hz"] = round(float(primary), 4)
    else:
        # No usable line frequency: HF-only soft score (legacy blend without ERPM/gyro lines).
        inference_mode = "hf_texture_fallback"
        reason_codes.append("hf_texture_primary")
        score = 0.0
        weight = 0.0
        if hf_ratio is not None:
            if hf_ratio >= 0.38:
                score += -0.5
            elif hf_ratio >= 0.22:
                score += 0.05
            else:
                score += 0.4
            weight += 0.85
        if weight <= 0:
            reason_codes.append("hf_texture_insufficient_weight")
            meta_early = {
                "frame_inference_mode": inference_mode,
                "frame_detection_reason_codes": list(reason_codes),
                "gyro_erpm_frame_summary": _gyro_erpm_frame_summary_empty(),
            }
            return 1, 0.15, "erpm", meta_early
        avg = score / weight
        if avg < -0.25:
            o = 0
        elif avg > 0.35:
            o = 2
        else:
            o = 1
        base_conf = min(1.0, weight / 2.75) * 0.75
        base_conf *= math.sqrt(max(1e-6, weight_gyro * weight_erpm))
        meta_hf = {
            "frame_inference_mode": inference_mode,
            "frame_detection_reason_codes": list(reason_codes),
            "gyro_erpm_frame_summary": _gyro_erpm_frame_summary_empty(),
        }
        return o, max(0.12, min(0.95, base_conf)), "erpm", meta_hf

    # Confidence: HF texture only (same shape as before) — not used for ordinal when gyro/erpm primary.
    score = 0.0
    weight = 0.0
    if hf_ratio is not None:
        if hf_ratio >= 0.38:
            score += -0.5
        elif hf_ratio >= 0.22:
            score += 0.05
        else:
            score += 0.4
        weight += 0.85

    if weight <= 0:
        base_conf = 0.35
    else:
        base_conf = min(1.0, weight / 2.75)

    if harmonic_match_flag and gyro_ok:
        base_conf *= 0.82
    elif erpm_confidence is not None:
        try:
            ec = max(0.0, min(1.0, float(erpm_confidence)))
        except (TypeError, ValueError):
            ec = 0.0
        base_conf = base_conf * (0.55 + 0.45 * ec)
    else:
        base_conf *= 0.75

    if erpm_dom_hz is None and not gyro_ok:
        base_conf *= 0.5

    if gyro_ok and erpm_motor_primary is None:
        base_conf *= max(0.35, min(1.0, weight_gyro))
    elif erpm_motor_primary is not None and not gyro_ok:
        base_conf *= max(0.35, min(1.0, weight_erpm))
    elif gyro_ok and erpm_motor_primary is not None:
        base_conf *= max(0.35, min(1.0, math.sqrt(weight_gyro * weight_erpm)))

    meta_out = {
        "frame_inference_mode": inference_mode,
        "frame_detection_reason_codes": list(reason_codes),
        "gyro_erpm_frame_summary": gyro_erpm_summary,
    }
    return o, max(0.12, min(0.95, base_conf)), source, meta_out


def _estimate_style(
    unified_propwash: dict[str, Any] | None,
    oscillation_val: float,
    erpm_dom_hz: float | None,
) -> str:
    """Loose labels aligned with frontend: Freestyle | Racing | Cinematic | Long Range."""
    pw = "moderate"
    if isinstance(unified_propwash, dict):
        pw = str(unified_propwash.get("level") or "moderate").lower()
    osc = float(oscillation_val or 0.0)
    if pw in ("none", "mild") and osc < 18.0:
        return "Cinematic"
    if osc >= 55.0 or pw in ("severe", "high", "heavy"):
        return "Racing"
    if erpm_dom_hz is not None and erpm_dom_hz < 160.0 and osc < 35.0:
        return "Long Range"
    return "Freestyle"


def _inertia_class(frame_ordinal: int) -> str:
    return ("low", "medium", "high")[max(0, min(2, frame_ordinal))]


def _build_frame_detection_summary(inference_meta: Mapping[str, Any]) -> str:
    mode = str(inference_meta.get("frame_inference_mode") or "unknown")
    codes = inference_meta.get("frame_detection_reason_codes")
    parts = [mode]
    if isinstance(codes, list) and codes:
        parts.append(",".join(str(c) for c in codes[:8]))
    return ": ".join(parts)


def estimate_detected_context(
    *,
    signal_analysis: dict[str, Any] | None,
    engine_metrics: dict[str, Any] | None,
    erpm_analysis: dict[str, Any] | None,
    unified_propwash: dict[str, Any] | None,
    oscillation_val: float,
    input_context: dict[str, Any] | None = None,
    samples: list[dict] | None = None,
) -> dict[str, Any]:
    ea = erpm_analysis if isinstance(erpm_analysis, dict) else {}
    dom_motor = ea.get("dominant_frequency")
    try:
        erpm_hz = float(dom_motor) if dom_motor is not None else None
    except (TypeError, ValueError):
        erpm_hz = None
    if erpm_hz is not None and (not math.isfinite(erpm_hz) or erpm_hz <= 0):
        erpm_hz = None

    try:
        raw_erpm_conf = float(ea.get("confidence") or 0.0)
    except (TypeError, ValueError):
        raw_erpm_conf = None
    erpm_conf = raw_erpm_conf

    ui = input_context if isinstance(input_context, dict) else {}
    _hs = resolve_hardware_sources(
        hardware_sources=ui.get("hardware_sources"),
        hardware_source=ui.get("hardware_source"),
    )
    _kv_src = _hs.get("motor_kv", "user")
    if erpm_conf is not None and _kv_src == "default":
        try:
            erpm_conf = max(0.0, min(1.0, float(erpm_conf) * 0.82))
        except (TypeError, ValueError):
            pass

    kv = _parse_kv_ui(ui.get("motor_kv"))
    cells = _parse_battery_cells_ui(ui.get("battery"))
    bat_v = _nominal_battery_voltage_ui(cells)
    thr_avg, thr_p95 = _throttle_avg_p95_from_samples(
        samples if isinstance(samples, list) else None,
    )
    pole_pairs = _resolve_motor_pole_pairs_from_context(ui)
    pole_pairs_meta = pole_pairs_metadata_from_context(ui)

    uncorrected_merged_gyro_hz, gyro_frame_meta = compute_merged_gyro_hz_for_frame_detection(
        signal_analysis,
        kv=kv,
        battery_voltage_v=bat_v,
        throttle_avg=thr_avg,
        throttle_p95=thr_p95,
        erpm_dom_hz=erpm_hz,
        pole_pairs=pole_pairs,
    )
    rpm_alignment = (
        gyro_frame_meta.get("rpm_alignment")
        if isinstance(gyro_frame_meta, dict)
        else None
    )
    corrected_gyro_hz, harmonic_corrected = apply_rpm_harmonic_correction_for_frame_detection(
        uncorrected_merged_gyro_hz,
        rpm_alignment if isinstance(rpm_alignment, dict) else None,
    )
    if isinstance(gyro_frame_meta, dict):
        gyro_frame_meta["original_gyro_hz"] = uncorrected_merged_gyro_hz
        gyro_frame_meta["corrected_gyro_hz"] = corrected_gyro_hz
        gyro_frame_meta["harmonic_corrected"] = harmonic_corrected
        mh_dbg = gyro_frame_meta.get("merged_hz_for_frame_model")
        if corrected_gyro_hz is not None and mh_dbg is not None:
            try:
                cg_f = float(corrected_gyro_hz)
                if not math.isfinite(cg_f) or cg_f <= 0:
                    raise ValueError
                mh_f = float(mh_dbg)
                if math.isfinite(mh_f) and abs(cg_f - mh_f) > 20.0:
                    gyro_frame_meta["frame_model_using_corrected"] = True
            except (TypeError, ValueError):
                pass
        og_dbg = gyro_frame_meta.get("gyro_primary_hz_for_frame_ordinal")
        if corrected_gyro_hz is not None and og_dbg is not None:
            try:
                cg_f = float(corrected_gyro_hz)
                if not math.isfinite(cg_f) or cg_f <= 0:
                    raise ValueError
                og_f = float(og_dbg)
                if math.isfinite(og_f) and abs(cg_f - og_f) > 20.0:
                    gyro_frame_meta["frame_model_using_corrected"] = True
            except (TypeError, ValueError):
                pass

    # Suppress KV/throttle-model mismatch when measured ERPM independently
    # confirms the gyro peak.  Guard against circularity: when there are no
    # real gyro axis peaks the merged Hz is derived FROM erpm, so matching
    # ERPM against itself is not independent confirmation.
    if (
        isinstance(gyro_frame_meta, dict)
        and gyro_frame_meta.get("rpm_mismatch") is True
        and gyro_frame_meta.get("gyro_hz_fallback") != "erpm_dominant"
        and erpm_hz is not None
        and uncorrected_merged_gyro_hz is not None
        and _erpm_confirms_gyro_peak(
            float(uncorrected_merged_gyro_hz),
            float(erpm_hz),
            pole_pairs,
            float(raw_erpm_conf) if raw_erpm_conf is not None else 0.0,
            str(ea.get("erpm_scale_assumption") or "unknown"),
        )
    ):
        gyro_frame_meta["rpm_mismatch"] = False
        gyro_frame_meta["rpm_mismatch_suppressed_by_erpm_confirmation"] = True

    hf = _hf_ratio(engine_metrics)

    _tier = classify_detected_hardware_signal_tier(
        uncorrected_merged_gyro_hz=uncorrected_merged_gyro_hz,
        corrected_gyro_hz=corrected_gyro_hz,
        rpm_alignment=rpm_alignment,
        hf_ratio=hf,
        erpm_hz=erpm_hz,
        erpm_conf_raw=raw_erpm_conf,
    )
    if erpm_conf is not None and _kv_src == "detected":
        try:
            ec = float(erpm_conf)
            mult_kv = {"high": 0.93, "medium": 0.88, "low": 0.82}[_tier]
            erpm_conf = max(0.0, min(1.0, ec * mult_kv))
        except (TypeError, ValueError):
            pass

    gyro_primary_for_ord: float | None = None
    if isinstance(gyro_frame_meta, dict):
        _gp = gyro_frame_meta.get("gyro_primary_hz_for_frame_ordinal")
        if _gp is not None:
            try:
                _gpf = float(_gp)
                if math.isfinite(_gpf) and _gpf > 0.0:
                    gyro_primary_for_ord = _gpf
            except (TypeError, ValueError):
                pass

    fo, conf, frame_model_source, inference_meta = _estimate_frame_ordinal(
        erpm_hz,
        corrected_gyro_hz,
        hf,
        erpm_conf,
        harmonic_match=(
            rpm_alignment.get("harmonic_match")
            if isinstance(rpm_alignment, dict)
            else None
        ),
        hardware_sources=_hs,
        pole_pairs=pole_pairs,
        gyro_primary_hz=gyro_primary_for_ord,
    )

    # Hardware class ordinal integration: when the user-declared hardware class implies
    # a different frame family than the frequency-derived ordinal, and the observed motor
    # Hz is achievable for the declared KV×Vbat at typical flight throttle (20–90%),
    # treat the frequency-band assignment as a band artifact — high-KV whoops and
    # low-KV large-frame builds regularly fall in an adjacent Hz band at operating
    # throttle.  Only override when we can confirm the frequency IS explainable; when
    # the frequency is outside the plausible KV range the original ordinal stands and
    # compute_context_validation will still flag the genuine mismatch.
    _hw_class = ui.get("hardware_class")
    if _hw_class is not None:
        _hw_profile = get_hardware_profile(_hw_class)
        if _hw_profile is not None:
            _hw_class_ord: int = _hw_profile.frame_ordinal
            _rc: list[str] = list(inference_meta.get("frame_detection_reason_codes") or [])
            if (
                _hw_class_ord != fo
                and kv is not None
                and bat_v is not None
                and uncorrected_merged_gyro_hz is not None
                and _motor_hz_explainable_for_hw(
                    float(uncorrected_merged_gyro_hz), kv, bat_v
                )
            ):
                _old_fo = fo
                fo = _hw_class_ord
                frame_model_source = "hw_class"
                _rc.append("hw_class_overrides_frequency_band_artifact")
                inference_meta = {**inference_meta, "frame_detection_reason_codes": _rc}
                # Confidence penalty: larger when hardware provenance is uncertain.
                _hw_src_ok = all(
                    str(_hs.get(k) or "user") == "user"
                    for k in ("frame", "motor_kv", "battery")
                )
                _conf_mult = 0.88 if _hw_src_ok else 0.72
                conf = max(0.05, conf * _conf_mult)
                _LOG.info(
                    "estimate_detected_context: hw_class ordinal override "
                    "freq_hz=%.1f ord %s->%s hw_class=%s conf_mult=%.2f",
                    float(uncorrected_merged_gyro_hz),
                    _old_fo,
                    fo,
                    _hw_class,
                    _conf_mult,
                )
            elif _hw_class_ord == fo:
                _rc.append("hw_class_confirms_frequency_ordinal")
                inference_meta = {**inference_meta, "frame_detection_reason_codes": _rc}

    if isinstance(gyro_frame_meta, dict):
        gyro_frame_meta["frame_model_source"] = frame_model_source
    est_size = _FRAME_ORD_TO_LABEL[fo]
    style = _estimate_style(unified_propwash, oscillation_val, erpm_hz)

    _fr_src = _hs.get("frame", "user")
    try:
        conf = float(conf)
    except (TypeError, ValueError):
        conf = 0.0
    if conf == conf and conf > 0:
        if _fr_src == "default":
            conf = max(0.05, conf * 0.88)
            _LOG.info(
                "estimate_detected_context: scaling frame confidence (frame hardware_source=default)"
            )
        elif _fr_src == "detected":
            mult_fr = {"high": 0.96, "medium": 0.93, "low": 0.90}[_tier]
            conf = max(0.05, conf * mult_fr)

    _bat_src = _hs.get("battery", "user")
    if conf == conf and conf > 0:
        if _bat_src == "default":
            conf = max(0.05, conf * 0.97)
        elif _bat_src == "detected":
            mult_bat = {"high": 0.99, "medium": 0.985, "low": 0.98}[_tier]
            conf = max(0.05, conf * mult_bat)

    out: dict[str, Any] = {
        "estimated_frame_size": est_size,
        "estimated_style": style,
        "inertia_class": _inertia_class(fo),
        "confidence": round(conf, 3),
        "frame_model_source": frame_model_source,
        "pole_pairs_metadata": pole_pairs_meta,
        "frame_inference_mode": inference_meta.get("frame_inference_mode"),
        "frame_detection_reason_codes": inference_meta.get("frame_detection_reason_codes"),
        "frame_detection_summary": _build_frame_detection_summary(inference_meta),
        "gyro_erpm_frame_summary": inference_meta.get("gyro_erpm_frame_summary"),
    }
    rpm_summary: dict[str, Any] = {}
    if isinstance(rpm_alignment, dict):
        rpm_summary["harmonic_match"] = rpm_alignment.get("harmonic_match")
        rpm_summary["ratio"] = rpm_alignment.get("ratio")
        rpm_summary["throttle_used"] = rpm_alignment.get("throttle_used")
    if isinstance(gyro_frame_meta, dict) and "rpm_mismatch" in gyro_frame_meta:
        rpm_summary["rpm_mismatch"] = gyro_frame_meta.get("rpm_mismatch")
    if rpm_summary:
        out["rpm_alignment_summary"] = rpm_summary
    if (
        isinstance(gyro_frame_meta, dict)
        and gyro_frame_meta.get("frame_model_using_corrected") is True
    ):
        out["frame_model_using_corrected"] = True
    if isinstance(gyro_frame_meta, dict):
        mfft = gyro_frame_meta.get("motor_fundamental_fft")
        if isinstance(mfft, dict):
            out["motor_fundamental_fft"] = {
                "fundamental_hz": mfft.get("fundamental_hz"),
                "harmonic_count": mfft.get("harmonic_count"),
                "confidence": mfft.get("confidence"),
            }
    return out


def compute_context_validation(
    input_ctx: dict[str, Any],
    detected_ctx: dict[str, Any],
    *,
    mismatch_threshold_ord: int = 0,
    min_confidence_to_flag: float = 0.32,
) -> dict[str, Any]:
    """
    If |input_ord - detected_ord| > mismatch_threshold_ord and detection confidence is sufficient,
    report mismatch. Default threshold 0 = any bucket difference flags when confident.
    """
    fs = input_ctx.get("frame_size")
    user_ord = frame_ordinal_from_label(_safe_str(fs))
    det_label = detected_ctx.get("estimated_frame_size")
    det_ord = frame_ordinal_from_label(_safe_str(det_label))

    try:
        conf = float(detected_ctx.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0

    if user_ord is None:
        return {
            "mismatch": False,
            "message": "Select a frame size in setup to validate against this log.",
        }

    if det_ord is None or conf < min_confidence_to_flag:
        return {
            "mismatch": False,
            "message": "Not enough overlapping signals to validate frame size against your setup.",
        }

    gap = abs(int(user_ord) - int(det_ord))
    mismatch = gap > mismatch_threshold_ord
    return {
        "mismatch": bool(mismatch),
        "message": (
            "Detected flight behavior differs from selected hardware"
            if mismatch
            else "Log behavior matches selected frame class."
        ),
    }
