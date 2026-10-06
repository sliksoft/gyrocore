# GyroCore WU4: adapted from AeroTuner backend/analysis/frame_inference_debug.py
"""
Debug-only payload for log-derived frame size inference.

Exposes the same internal signals that feed ``estimate_detected_context`` plus
supporting gyro / motor / throttle context. Does not alter inference.
"""

from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

import numpy as np

from gyrocore.analysis.context_validation import (
    _erpm_confirms_gyro_peak,
    _hf_ratio,
    apply_rpm_harmonic_correction_for_frame_detection,
    compute_merged_gyro_hz_for_frame_detection,
    _resolve_motor_pole_pairs_from_context,
)
from gyrocore.analysis._support.rpm_kv_confidence_policy import apply_rpm_kv_confidence_policy
from gyrocore.analysis.motor_fft_harmonics import (
    estimate_motor_fundamental_from_fft_peaks_indexed,
    validate_motor_fundamental_vs_kv_rpm,
)
from gyrocore.analysis.motor_prop_physics import estimate_prop_class_from_motor_physics

_LOG = logging.getLogger(__name__)


def _throttle_avg_max(samples: list[dict]) -> tuple[float | None, float | None]:
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
    raw_min = min(raw_vals)
    norm_list: list[float] = []
    for v in raw_vals:
        if raw_max > 1.5:
            norm = (v - 1000.0) / 1000.0
        else:
            norm = v
        norm_list.append(max(0.0, min(1.0, norm)))
    return (
        round(float(sum(norm_list) / len(norm_list)), 4),
        round(float(max(norm_list)), 4),
    )


def _throttle_p95_normalized(samples: list[dict]) -> float | None:
    """Same 0–1 throttle normalization as ``_throttle_avg_max``; returns 95th percentile or None."""
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
        return None
    raw_max = max(raw_vals)
    norm_list: list[float] = []
    for v in raw_vals:
        if raw_max > 1.5:
            norm = (v - 1000.0) / 1000.0
        else:
            norm = v
        norm_list.append(max(0.0, min(1.0, norm)))
    if not norm_list:
        return None
    return round(float(np.percentile(np.asarray(norm_list, dtype=float), 95)), 4)


def _motor_mean_max_normalized(motor_data: list[list[float]] | None) -> tuple[float | None, float | None]:
    if not motor_data:
        return None, None
    data = np.asarray(motor_data, dtype=float)
    if data.size == 0:
        return None, None
    if float(np.max(data)) > 100.0:
        data = (data - 1000.0) / 1000.0
    data = np.clip(data, 0.0, 1.0)
    return round(float(np.mean(data)), 4), round(float(np.max(data)), 4)


def _parse_kv(kv_raw: Any) -> float | None:
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


def _parse_battery_cell_count(bat_raw: Any) -> int | None:
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


def _nominal_battery_voltage_v(cells: int | None) -> float | None:
    if cells is None:
        return None
    return round(float(cells) * 3.7, 2)


def _indexed_fft_peaks(
    signal_analysis: dict[str, Any] | None,
    *,
    limit: int = 32,
) -> list[dict[str, Any]]:
    """Merged FFT peak list with index and amplitude (for wrong-peak diagnostics)."""
    out: list[dict[str, Any]] = []
    if not isinstance(signal_analysis, dict):
        return out
    fft_peaks = signal_analysis.get("fft_peaks")
    if isinstance(fft_peaks, list) and fft_peaks:
        for i, p in enumerate(fft_peaks):
            if len(out) >= limit:
                break
            if not isinstance(p, dict):
                continue
            try:
                f = float(p.get("freq", 0) or 0)
                a = float(p.get("amplitude", 0) or 0)
                bw = p.get("bandwidth_hz")
                bw_f = round(float(bw), 3) if bw is not None else None
            except (TypeError, ValueError):
                continue
            if f <= 0:
                continue
            row: dict[str, Any] = {
                "peak_index": i,
                "frequency_hz": round(f, 3),
                "amplitude": round(a, 4),
            }
            if bw_f is not None:
                row["bandwidth_hz"] = bw_f
            out.append(row)
        return out

    pf = signal_analysis.get("peak_frequencies") or []
    pa = signal_analysis.get("peak_amplitudes") or []
    if not isinstance(pf, list):
        return out
    for i, rawf in enumerate(pf):
        if len(out) >= limit:
            break
        try:
            f = float(rawf)
        except (TypeError, ValueError):
            continue
        if f <= 0:
            continue
        try:
            a = float(pa[i]) if isinstance(pa, list) and i < len(pa) else 0.0
        except (TypeError, ValueError):
            a = 0.0
        out.append(
            {
                "peak_index": i,
                "frequency_hz": round(f, 3),
                "amplitude": round(a, 4),
            },
        )
    return out


def _log_gyro_merge_validation(gyro_merge_validation: dict[str, Any]) -> None:
    ax = gyro_merge_validation.get("axis_peaks_hz") or {}
    merged = gyro_merge_validation.get("merged_hz_for_frame_model")
    roll = ax.get("roll") if isinstance(ax, dict) else None
    pitch = ax.get("pitch") if isinstance(ax, dict) else None
    yaw = ax.get("yaw") if isinstance(ax, dict) else None
    payload = {
        "roll": roll,
        "pitch": pitch,
        "yaw": yaw,
        "merged": merged,
    }
    try:
        _LOG.info("GYRO RAW VS MERGED %s", json.dumps(payload, default=str))
    except (TypeError, ValueError):
        _LOG.info("GYRO RAW VS MERGED %s", str(payload))

    try:
        m = float(merged) if merged is not None else None
        r = float(roll) if roll is not None else None
        p = float(pitch) if pitch is not None else None
        y = float(yaw) if yaw is not None else None
    except (TypeError, ValueError):
        return
    if m is None or r is None or p is None or y is None:
        return
    if (
        abs(m - r) > 50.0
        and abs(m - p) > 50.0
        and abs(m - y) > 50.0
    ):
        _LOG.warning(
            "Merged gyro frequency inconsistent with axis peaks (see GYRO RAW VS MERGED payload=%s)",
            json.dumps(payload, default=str),
        )


def _harmonic_spacing_hz(erpm_analysis: dict[str, Any] | None) -> float | None:
    if not isinstance(erpm_analysis, dict):
        return None
    hh = erpm_analysis.get("harmonics_hz")
    if not isinstance(hh, list):
        return None
    spacings: list[float] = []
    for row in hh:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        try:
            h1 = float(row[0]) if row[0] is not None else None
            h2 = float(row[1]) if row[1] is not None else None
        except (TypeError, ValueError):
            continue
        if (
            h1 is not None
            and h2 is not None
            and math.isfinite(h1)
            and math.isfinite(h2)
            and h1 > 0
            and h2 > h1
        ):
            spacings.append(h2 - h1)
    if not spacings:
        return None
    return round(float(sum(spacings) / len(spacings)), 3)


def build_debug_frame_analysis(
    *,
    signal_analysis: dict[str, Any] | None,
    engine_metrics: dict[str, Any] | None,
    erpm_analysis: dict[str, Any] | None,
    detected_context: dict[str, Any],
    input_context: dict[str, Any] | None,
    motor_stats: dict[str, Any] | None,
    motor_data: list[list[float]] | None,
    samples: list[dict],
    noise_level_str: str,
) -> dict[str, Any]:
    ui = input_context if isinstance(input_context, dict) else {}
    kv = _parse_kv(ui.get("motor_kv"))
    cells = _parse_battery_cell_count(ui.get("battery"))
    bat_v = _nominal_battery_voltage_v(cells)
    thr_avg, thr_max = _throttle_avg_max(samples)
    thr_p95 = _throttle_p95_normalized(samples)

    ea0 = erpm_analysis if isinstance(erpm_analysis, dict) else {}
    try:
        erpm_dom_for_merge = (
            float(ea0.get("dominant_frequency"))
            if ea0.get("dominant_frequency") is not None
            else None
        )
    except (TypeError, ValueError):
        erpm_dom_for_merge = None
    if erpm_dom_for_merge is not None and (
        not math.isfinite(erpm_dom_for_merge) or erpm_dom_for_merge <= 0
    ):
        erpm_dom_for_merge = None

    pole_pairs = _resolve_motor_pole_pairs_from_context(ui)
    merged_gyro_hz, gyro_axis_meta = compute_merged_gyro_hz_for_frame_detection(
        signal_analysis,
        kv=kv,
        battery_voltage_v=bat_v,
        throttle_avg=thr_avg,
        throttle_p95=thr_p95,
        erpm_dom_hz=erpm_dom_for_merge,
        pole_pairs=pole_pairs,
    )
    _rpm_al = gyro_axis_meta.get("rpm_alignment") if isinstance(gyro_axis_meta, dict) else None
    corrected_gyro_hz, harmonic_corrected = apply_rpm_harmonic_correction_for_frame_detection(
        merged_gyro_hz,
        _rpm_al if isinstance(_rpm_al, dict) else None,
    )
    if isinstance(gyro_axis_meta, dict):
        gyro_axis_meta["original_gyro_hz"] = merged_gyro_hz
        gyro_axis_meta["corrected_gyro_hz"] = corrected_gyro_hz
        gyro_axis_meta["harmonic_corrected"] = harmonic_corrected

    # Suppress KV/throttle-model mismatch when measured ERPM independently
    # confirms the gyro peak.  Guard against circularity: when merged Hz was
    # derived from ERPM (no real gyro axis peaks) the check is circular.
    if (
        isinstance(gyro_axis_meta, dict)
        and gyro_axis_meta.get("rpm_mismatch") is True
        and gyro_axis_meta.get("gyro_hz_fallback") != "erpm_dominant"
        and erpm_dom_for_merge is not None
        and merged_gyro_hz is not None
        and _erpm_confirms_gyro_peak(
            float(merged_gyro_hz),
            float(erpm_dom_for_merge),
            pole_pairs,
            float(ea0.get("confidence") or 0.0),
            str(ea0.get("erpm_scale_assumption") or "unknown"),
        )
    ):
        gyro_axis_meta["rpm_mismatch_suppressed_by_erpm_confirmation"] = True
        apply_rpm_kv_confidence_policy(
            gyro_axis_meta,
            hardware_class=(
                (ui.get("hardware") or {}).get("hardware_class")
                if isinstance(ui.get("hardware"), dict)
                else None
            )
            or ui.get("hardware_class"),
        )

    axp = gyro_axis_meta.get("axis_peaks_hz") or {}
    r_ = axp.get("roll")
    p_ = axp.get("pitch")
    y_ = axp.get("yaw")
    _axis_vals = [v for v in (r_, p_, y_) if v is not None]
    _avg = (
        round(float(sum(_axis_vals) / len(_axis_vals)), 3) if _axis_vals else None
    )
    gyro_block = {
        "peak_freq_roll": r_,
        "peak_freq_pitch": p_,
        "peak_freq_yaw": y_,
        "avg_peak_freq": _avg,
    }

    m_mean, m_max = _motor_mean_max_normalized(motor_data)
    if m_mean is None and isinstance(motor_stats, dict):
        try:
            mo = motor_stats.get("mean_output")
            if mo is not None:
                m_mean = round(float(mo), 4)
        except (TypeError, ValueError):
            pass

    est_rpm: float | None = None
    if kv is not None and bat_v is not None and thr_avg is not None:
        est_rpm = round(kv * bat_v * thr_avg, 1)

    hf = _hf_ratio(engine_metrics)
    ea = erpm_analysis if isinstance(erpm_analysis, dict) else {}
    try:
        erpm_dom = float(ea.get("dominant_frequency")) if ea.get("dominant_frequency") is not None else None
    except (TypeError, ValueError):
        erpm_dom = None
    if erpm_dom is not None and (not math.isfinite(erpm_dom) or erpm_dom <= 0):
        erpm_dom = None

    try:
        erpm_conf = float(ea.get("confidence") or 0.0)
    except (TypeError, ValueError):
        erpm_conf = None
    if erpm_conf is not None and not math.isfinite(erpm_conf):
        erpm_conf = None

    fft_peaks_indexed = _indexed_fft_peaks(signal_analysis)
    motor_fft = estimate_motor_fundamental_from_fft_peaks_indexed(fft_peaks_indexed)
    kv_fft_rpm = validate_motor_fundamental_vs_kv_rpm(
        motor_fft.get("fundamental_hz") if isinstance(motor_fft, dict) else None,
        kv,
        bat_v,
        thr_avg,
    )
    prop_physics = estimate_prop_class_from_motor_physics(
        motor_fft.get("fundamental_hz") if isinstance(motor_fft, dict) else None,
        kv,
        bat_v,
    )
    gyro_merge_validation: dict[str, Any] = {
        **gyro_axis_meta,
        "fft_peaks_indexed": fft_peaks_indexed,
        "motor_fundamental_fft": motor_fft,
        "kv_fft_rpm_validation": kv_fft_rpm,
        "prop_physics": prop_physics,
        "pole_pairs_used": pole_pairs,
    }
    for _auth_key in (
        "cli_motor_poles",
        "motor_poles_effective",
        "pole_pairs_effective",
        "motor_poles_source",
        "motor_poles_authority",
        "motor_poles_authority_reason",
        "rpm_alignment_source",
        "fallback_motor_poles",
    ):
        if _auth_key in ui:
            gyro_merge_validation[_auth_key] = ui.get(_auth_key)
    _hw = ui.get("hardware") if isinstance(ui.get("hardware"), dict) else {}
    _hardware_class = _hw.get("hardware_class") or ui.get("hardware_class")
    apply_rpm_kv_confidence_policy(
        gyro_merge_validation,
        hardware_class=_hardware_class,
    )
    _log_gyro_merge_validation(gyro_merge_validation)

    dc = detected_context if isinstance(detected_context, dict) else {}
    try:
        frame_conf = float(dc.get("confidence") or 0.0)
    except (TypeError, ValueError):
        frame_conf = None

    n_block = (
        engine_metrics.get("noise")
        if isinstance(engine_metrics, dict) and isinstance(engine_metrics.get("noise"), dict)
        else {}
    )
    try:
        noise_hf_ratio = float(n_block.get("hf_ratio") or 0.0)
    except (TypeError, ValueError):
        noise_hf_ratio = None
    if noise_hf_ratio is not None and math.isfinite(noise_hf_ratio):
        noise_hf_ratio = round(max(0.0, min(1.0, noise_hf_ratio)), 4)
    else:
        noise_hf_ratio = None

    return {
        "gyro": {
            "peak_freq_roll": gyro_block["peak_freq_roll"],
            "peak_freq_pitch": gyro_block["peak_freq_pitch"],
            "peak_freq_yaw": gyro_block["peak_freq_yaw"],
            "avg_peak_freq": gyro_block["avg_peak_freq"],
        },
        "motor": {
            "avg_output": m_mean,
            "max_output": m_max,
        },
        "throttle": {
            "avg": thr_avg,
            "max": thr_max,
        },
        "derived": {
            "estimated_rpm": est_rpm,
            "harmonic_spacing": _harmonic_spacing_hz(erpm_analysis),
            "kv_fft_rpm_validation": kv_fft_rpm,
            "prop_physics": prop_physics,
        },
        "hardware": {
            "kv": kv,
            "battery_voltage": bat_v,
            "battery_cell_count": cells,
        },
        "noise_level": str(noise_level_str).upper(),
        "noise_hf_ratio": noise_hf_ratio,
        "result": {
            "estimated_frame_size": dc.get("estimated_frame_size"),
            "confidence": round(frame_conf, 4) if frame_conf is not None else None,
        },
        "frame_model_signals": {
            "erpm_dominant_hz": round(erpm_dom, 3) if erpm_dom is not None else None,
            "merged_gyro_hz_for_frame_model": round(corrected_gyro_hz, 3)
            if corrected_gyro_hz is not None
            else None,
            "hf_ratio_for_frame_model": round(hf, 4) if hf is not None else None,
            "erpm_confidence": round(erpm_conf, 4) if erpm_conf is not None else None,
        },
        "gyro_merge_validation": gyro_merge_validation,
    }
