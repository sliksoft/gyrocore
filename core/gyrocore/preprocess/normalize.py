"""Gyro scale normalization extracted from AeroTuner ``backend/routes/analyze.py`` (WU4)."""

from __future__ import annotations

import math
from typing import Any

from gyrocore.analysis.erpm_analysis import normalize_erpm_for_sample
from gyrocore.parse.blackbox_csv import max_abs_gyro_triplet

# Blackbox: ``gyroADC`` columns are raw gyro integers; scaled ``gyro[i]`` are deg/s.
BETAFLIGHT_GYRO_ADC_TO_DEG_PER_SEC = 0.004
_GYRO_ADC_HEURISTIC_PEAK = 6000.0
_GYRO_SECOND_PASS_PEAK_DEG_S = 8000.0


def detect_gyro_scale(
    samples: list[dict],
    *,
    gyro_source_is_raw_adc: bool | None = None,
) -> float:
    """Multiplier to convert parser gx/gy/gz into deg/s for the analysis pipeline."""
    if gyro_source_is_raw_adc is True:
        return BETAFLIGHT_GYRO_ADC_TO_DEG_PER_SEC
    if gyro_source_is_raw_adc is False:
        return 1.0

    peak = max_abs_gyro_triplet(samples, max_rows=None)
    if peak is None:
        return 1.0
    if peak >= _GYRO_ADC_HEURISTIC_PEAK:
        return BETAFLIGHT_GYRO_ADC_TO_DEG_PER_SEC
    return 1.0


def correct_gyro_scale_if_needed(
    samples: list[dict],
    *,
    peak_threshold: float = _GYRO_SECOND_PASS_PEAK_DEG_S,
    already_scaled: bool = False,
) -> bool:
    if already_scaled:
        return False
    if not samples:
        return False
    n = min(1000, len(samples))
    try:
        peak = 0.0
        for s in samples[:n]:
            peak = max(
                peak,
                abs(float(s["gx"])),
                abs(float(s["gy"])),
                abs(float(s["gz"])),
            )
    except (KeyError, TypeError, ValueError):
        return False
    if peak <= peak_threshold:
        return False
    factor = BETAFLIGHT_GYRO_ADC_TO_DEG_PER_SEC
    for s in samples:
        try:
            s["gx"] = float(s["gx"]) * factor
            s["gy"] = float(s["gy"]) * factor
            s["gz"] = float(s["gz"]) * factor
        except (KeyError, TypeError, ValueError):
            continue
    return True


def normalize_samples(
    samples: list[dict],
    *,
    gyro_source_is_raw_adc: bool | None = None,
) -> tuple[float, bool]:
    """Apply gyro scale in place. Returns (primary_scale_applied, second_pass_applied)."""
    scale = detect_gyro_scale(samples, gyro_source_is_raw_adc=gyro_source_is_raw_adc)
    for s in samples:
        try:
            s["gx"] = float(s["gx"]) * scale
            s["gy"] = float(s["gy"]) * scale
            s["gz"] = float(s["gz"]) * scale
        except (KeyError, TypeError, ValueError):
            continue
    second = correct_gyro_scale_if_needed(
        samples,
        already_scaled=gyro_source_is_raw_adc is False,
    )
    return scale, second


def build_gyro_scale_metadata(
    *,
    gyro_source_is_raw_adc: bool | None,
    pre_normalize_peak: float | None,
    applied_scale: float,
    second_pass_applied: bool,
) -> dict[str, Any]:
    warnings: list[str] = []
    if gyro_source_is_raw_adc is True:
        assumption = "adc_header"
        reason = "gyro_source_is_raw_adc_true"
    elif gyro_source_is_raw_adc is False:
        assumption = "deg_s_header"
        reason = "gyro_source_is_raw_adc_false"
    elif applied_scale == BETAFLIGHT_GYRO_ADC_TO_DEG_PER_SEC:
        assumption = "legacy_peak_heuristic"
        reason = "peak_at_or_above_6000_no_header_hint"
        warnings.append(
            "Legacy gyro scale heuristic applied: peak gyro magnitude was at or above "
            "6000 with no gyroADC/gyro header hint, so values were scaled by 0.004 as "
            "raw ADC. Extreme freestyle logs above 6000 deg/s may be mis-scaled."
        )
    else:
        assumption = "deg_s_implicit"
        reason = "peak_below_6000_no_header_hint"

    if second_pass_applied:
        warnings.append(
            "Second-pass gyro scale correction applied: peak gyro still exceeded "
            "8000 deg/s after the primary scale, so an additional 0.004 ADC factor was applied."
        )

    return {
        "gyro_scale_assumption": assumption,
        "gyro_scale_reason": reason,
        "gyro_second_pass_applied": bool(second_pass_applied),
        "gyro_source_is_raw_adc": gyro_source_is_raw_adc,
        "gyro_applied_scale": float(applied_scale),
        "gyro_pre_normalize_peak": (
            round(float(pre_normalize_peak), 1)
            if pre_normalize_peak is not None and math.isfinite(float(pre_normalize_peak))
            else None
        ),
        "heuristic_warnings": warnings,
    }


def normalize_raw_samples(
    raw_samples: list[dict] | None,
    *,
    gyro_source_is_raw_adc: bool | None = None,
) -> tuple[list[dict], dict[str, Any]]:
    """
    Parser output → analysis pipeline: int time, scaled gyro, optional throttle/motors/setpoints.

    Donor name: ``_normalize_samples``.
    """
    normalized: list[dict] = []
    if not raw_samples:
        return normalized, build_gyro_scale_metadata(
            gyro_source_is_raw_adc=gyro_source_is_raw_adc,
            pre_normalize_peak=None,
            applied_scale=1.0,
            second_pass_applied=False,
        )

    for index, sample in enumerate(raw_samples, start=1):
        if not isinstance(sample, dict):
            continue

        if "gx" in sample and "gy" in sample and "gz" in sample:
            gx = sample.get("gx")
            gy = sample.get("gy")
            gz = sample.get("gz")
        elif "gyro_x" in sample and "gyro_y" in sample and "gyro_z" in sample:
            gx = sample.get("gyro_x")
            gy = sample.get("gyro_y")
            gz = sample.get("gyro_z")
        else:
            continue

        t_value = sample.get("t", index)
        throttle_raw = sample.get("throttle")
        if throttle_raw is None:
            throttle_raw = sample.get("throttle_value")
        if throttle_raw is None:
            rc3 = sample.get("rcCommand[3]")
            throttle_raw = rc3 if rc3 is not None else sample.get("rc3")

        normalized_sample: dict = {
            "t": int(float(t_value)),
            "gx": float(gx),
            "gy": float(gy),
            "gz": float(gz),
        }
        if throttle_raw is not None:
            try:
                normalized_sample["throttle"] = float(throttle_raw)
            except (TypeError, ValueError):
                pass
        motors = sample.get("motors")
        if isinstance(motors, (list, tuple)):
            normalized_sample["motors"] = list(motors)
        for key in ("setpoint_roll", "setpoint_pitch", "setpoint_yaw"):
            sp_raw = sample.get(key)
            if sp_raw is not None:
                try:
                    normalized_sample[key] = float(sp_raw)
                except (TypeError, ValueError):
                    pass
        for rc_key in ("rcCommand[0]", "rcCommand[1]", "rcCommand[2]"):
            rc_raw = sample.get(rc_key)
            if rc_raw is not None:
                try:
                    normalized_sample[rc_key] = float(rc_raw)
                except (TypeError, ValueError):
                    pass
        if sample.get("erpm") is not None:
            normalized_sample["erpm"] = normalize_erpm_for_sample(sample.get("erpm"))
        for pid_key in ("axisP", "axisI", "axisD", "axisF"):
            raw_pid = sample.get(pid_key)
            if not isinstance(raw_pid, (list, tuple)):
                continue
            pid_values: list[float | None] = []
            for raw_value in list(raw_pid[:3]) + [None] * max(0, 3 - len(raw_pid[:3])):
                try:
                    value = float(raw_value)
                except (TypeError, ValueError):
                    pid_values.append(None)
                    continue
                pid_values.append(value if math.isfinite(value) else None)
            if any(value is not None for value in pid_values):
                normalized_sample[pid_key] = pid_values
        normalized.append(normalized_sample)

    pre_peak = max_abs_gyro_triplet(normalized, max_rows=None)
    scale, second_pass = normalize_samples(
        normalized,
        gyro_source_is_raw_adc=gyro_source_is_raw_adc,
    )
    gyro_metadata = build_gyro_scale_metadata(
        gyro_source_is_raw_adc=gyro_source_is_raw_adc,
        pre_normalize_peak=pre_peak,
        applied_scale=scale,
        second_pass_applied=second_pass,
    )
    return normalized, gyro_metadata
