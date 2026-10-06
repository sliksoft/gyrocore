"""Safe-tune clamps (WU10).

Donor: AeroTuner ``backend/services/tuning_safe_v2.py``
(``DEFAULT_MAX_DELTA``, ``apply_to_baseline``, ``apply_safety``,
``_apply_hard_clamp_ranges_to_config``) plus thermal envelope.

GyroCore Autotune-only bridges (documented in AEROTUNER_SAFETY_PARITY.md):

- ``d_max`` uses the same per-axis step cap as D (donor had no d_max step).
- Filter Hz of ``0`` (firmware OFF) is not raised to donor advisory minima.
- Firmware ``PID_GAIN_MAX`` / ``F_GAIN_MAX`` / ``DYN_LPF_MAX_HZ`` are additional ceilings.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping

from gyrocore.betaflight.simplified_tuning import (
    DYN_LPF_MAX_HZ,
    F_GAIN_MAX,
    LPF_MAX_HZ,
    PID_GAIN_MAX,
)

from gyrocore.safety.thermal import (
    clamp_targets_to_baseline_thermal,
    should_enforce_baseline_envelope,
)
from gyrocore.safety.types import SafetyCheck, SafetyVerdict

DEFAULT_MAX_DELTA: dict[str, Any] = {
    "filters": {
        "gyro_lpf1_static_hz": 44,
        "gyro_lpf1_dyn_min_hz": 50,
        "gyro_lpf1_dyn_max_hz": 60,
        "gyro_lpf2_static_hz": 40,
        "dterm_lpf1_dyn_min_hz": 20,
        "dterm_lpf1_dyn_max_hz": 30,
        "dterm_lpf2_static_hz": 30,
        "dyn_notch_count": 1,
        "dyn_notch_min_hz": 40,
        "dyn_notch_max_hz": 80,
        "dyn_notch_width_percent": 5,
        "rpm_filter_harmonics": 1,
        "rpm_filter_min_hz": 20,
        "rpm_filter_max_hz": 100,
        "rpm_filter_fade_range_hz": 20,
        "feedforward_boost": 5,
        "feedforward_smooth_factor": 5,
        "feedforward_jitter_factor": 5,
        "feedforward_transition": 5,
        "rc_smoothing": 1,
        "rc_smoothing_feedforward": 5,
        "dyn_idle_min_rpm": 10,
        "anti_gravity_gain": 1000,
        "anti_gravity_cutoff": 2,
        "anti_gravity_p_gain": 10,
        "iterm_relax": 1,
        "iterm_rotation": 1,
        "tpa_rate": 5,
        "tpa_breakpoint": 50,
        "throttle_boost": 5,
        "motor_output_limit": 5,
    },
    "pid": {
        "roll": {"p": 4, "i": 8, "d": 6, "ff": 8, "d_max": 6},
        "pitch": {"p": 4, "i": 8, "d": 6, "ff": 8, "d_max": 6},
        "yaw": {"p": 4, "i": 8, "d": 6, "ff": 8, "d_max": 6},
    },
}

DONOR_PID_HARD_RANGES = {
    "p": (10, 100),
    "d": (5, 85),
    "ff": (0, 220),
}

FIRMWARE_PID_HARD_RANGES = {
    "p": (0, PID_GAIN_MAX),
    "i": (0, PID_GAIN_MAX),
    "d": (0, PID_GAIN_MAX),
    "d_max": (0, PID_GAIN_MAX),
    "ff": (0, F_GAIN_MAX),
}

CONFIDENCE_BLEND_THRESHOLD = 0.4
HARDWARE_WEIGHT_D_SCALE_KG = 800.0
HARDWARE_WEIGHT_D_FACTOR = 0.9


def _deep_merge_template(base: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(base)


def _get_filter_max_delta(max_delta: Mapping[str, Any], key: str, default: float) -> float:
    fd = max_delta.get("filters") if isinstance(max_delta, Mapping) else None
    if not isinstance(fd, Mapping):
        return default
    try:
        v = float(fd.get(key, default))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v) or v < 0:
        return default
    return v


def _get_pid_max_delta(
    max_delta: Mapping[str, Any],
    axis: str,
    comp: str,
    default: float,
) -> float:
    pd = max_delta.get("pid") if isinstance(max_delta, Mapping) else None
    if not isinstance(pd, Mapping):
        return default
    ax = pd.get(axis)
    if not isinstance(ax, Mapping):
        return default
    try:
        v = float(ax.get(comp, default))
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v) or v < 0:
        return default
    return v


def scale_max_delta(max_delta: Mapping[str, Any], scale: float) -> dict[str, Any]:
    out = copy.deepcopy(dict(max_delta))
    try:
        s = float(scale)
    except (TypeError, ValueError):
        s = 1.0
    if not math.isfinite(s):
        s = 1.0
    s = max(0.0, min(1.0, s))
    filt = out.get("filters")
    if isinstance(filt, dict):
        for key, val in list(filt.items()):
            try:
                filt[key] = float(val) * s
            except (TypeError, ValueError):
                continue
    pid = out.get("pid")
    if isinstance(pid, dict):
        for axis, block in list(pid.items()):
            if not isinstance(block, dict):
                continue
            for comp, val in list(block.items()):
                try:
                    block[comp] = float(val) * s
                except (TypeError, ValueError):
                    continue
    return out


def apply_to_baseline(
    base_config: Mapping[str, Any],
    targets: Mapping[str, Any],
    max_delta: Mapping[str, Any],
) -> dict[str, Any]:
    """Donor step clamp. GyroCore adds ``d_max`` using the D step cap when missing."""
    out = _deep_merge_template(dict(base_config))
    if not isinstance(targets, Mapping):
        return out

    bf = out.get("filters")
    tf = targets.get("filters")
    if isinstance(bf, dict) and isinstance(tf, Mapping):
        for key, tgt in tf.items():
            if key not in bf:
                continue
            if not isinstance(bf[key], (int, float)):
                continue
            try:
                cur = float(bf[key])
                tv = float(tgt)
            except (TypeError, ValueError):
                continue
            md = _get_filter_max_delta(max_delta, key, 0.0)
            delta = tv - cur
            delta = max(-md, min(md, delta))
            if str(key) == "dyn_notch_count":
                bf[key] = int(round(cur + delta))
            else:
                bf[key] = cur + delta

    bp = out.get("pid")
    tp = targets.get("pid")
    if isinstance(bp, dict) and isinstance(tp, Mapping):
        for axis in ("roll", "pitch", "yaw"):
            if axis not in bp or not isinstance(bp[axis], dict):
                continue
            t_ax = tp.get(axis)
            if not isinstance(t_ax, Mapping):
                continue
            block = bp[axis]
            for comp in ("p", "i", "d", "ff", "d_max"):
                if comp not in t_ax or comp not in block:
                    continue
                if not isinstance(block[comp], (int, float)):
                    continue
                try:
                    cur = float(block[comp])
                    tv = float(t_ax[comp])
                except (TypeError, ValueError):
                    continue
                fallback = _get_pid_max_delta(max_delta, axis, "d", 0.0) if comp == "d_max" else 0.0
                md = _get_pid_max_delta(max_delta, axis, comp, fallback)
                delta = tv - cur
                delta = max(-md, min(md, delta))
                block[comp] = cur + delta
    return out


def _blend_toward_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
    factor: float,
) -> dict[str, Any]:
    out = _deep_merge_template(current)
    bf_b = baseline.get("filters") if isinstance(baseline.get("filters"), dict) else {}
    bf_o = out.get("filters") if isinstance(out.get("filters"), dict) else {}
    for k, v in list(bf_o.items()):
        if k not in bf_b or not isinstance(v, (int, float)):
            continue
        try:
            b = float(bf_b[k])
            c = float(v)
        except (TypeError, ValueError):
            continue
        bf_o[k] = b + factor * (c - b)

    pb_b = baseline.get("pid") if isinstance(baseline.get("pid"), dict) else {}
    pb_o = out.get("pid") if isinstance(out.get("pid"), dict) else {}
    for axis in ("roll", "pitch", "yaw"):
        if axis not in pb_o or not isinstance(pb_o[axis], dict):
            continue
        if axis not in pb_b or not isinstance(pb_b[axis], dict):
            continue
        for comp in ("p", "i", "d", "ff", "d_max"):
            if comp not in pb_o[axis]:
                continue
            v = pb_o[axis][comp]
            if comp not in pb_b[axis] or not isinstance(v, (int, float)):
                continue
            try:
                b = float(pb_b[axis][comp])
                c = float(v)
            except (TypeError, ValueError):
                continue
            pb_o[axis][comp] = b + factor * (c - b)
    return out


def _is_zero_hz_off(value: Any) -> bool:
    try:
        return float(value) <= 1e-6
    except (TypeError, ValueError):
        return False


def _apply_hard_clamp_ranges_to_config(
    out: dict[str, Any],
    *,
    skip_zero_hz_min: bool = False,
    preserve_firmware_zeros: bool = False,
    apply_donor_pid_advisory: bool = True,
) -> list[str]:
    limits: list[str] = []
    filt = out.get("filters")
    if isinstance(filt, dict):
        g1 = "gyro_lpf1_static_hz"
        if g1 in filt and isinstance(filt[g1], (int, float)):
            v = float(filt[g1])
            if skip_zero_hz_min and _is_zero_hz_off(v):
                filt[g1] = 0.0
            else:
                lo, hi = 120, 300
                if v < lo:
                    limits.append(f"{g1}_clamped_min_{lo}")
                    v = float(lo)
                elif v > hi:
                    limits.append(f"{g1}_clamped_max_{hi}")
                    v = float(hi)
                filt[g1] = v

        for key in ("gyro_lpf1_dyn_min_hz", "gyro_lpf1_dyn_max_hz"):
            if key not in filt or not isinstance(filt[key], (int, float)):
                continue
            v = float(filt[key])
            if skip_zero_hz_min and _is_zero_hz_off(v):
                filt[key] = 0.0
                continue
            lo, hi = 0, min(600, DYN_LPF_MAX_HZ)
            if v < lo:
                limits.append(f"{key}_clamped_min_{lo}")
                v = float(lo)
            elif v > hi:
                limits.append(f"{key}_clamped_max_{hi}")
                v = float(hi)
            filt[key] = v

        g2 = "gyro_lpf2_static_hz"
        if g2 in filt and isinstance(filt[g2], (int, float)):
            v = float(filt[g2])
            if v <= 0.0:
                filt[g2] = 0.0
            else:
                lo, hi = 80, min(500, LPF_MAX_HZ)
                if v < lo:
                    limits.append(f"{g2}_clamped_min_{lo}")
                    v = float(lo)
                elif v > hi:
                    limits.append(f"{g2}_clamped_max_{hi}")
                    v = float(hi)
                filt[g2] = v

        dm = "dterm_lpf1_dyn_min_hz"
        if dm in filt and isinstance(filt[dm], (int, float)):
            v = float(filt[dm])
            if skip_zero_hz_min and _is_zero_hz_off(v):
                filt[dm] = 0.0
            else:
                lo, hi = 70, 150
                if v < lo:
                    limits.append(f"{dm}_clamped_min_{lo}")
                    v = float(lo)
                elif v > hi:
                    limits.append(f"{dm}_clamped_max_{hi}")
                    v = float(hi)
                filt[dm] = v

        dx = "dterm_lpf1_dyn_max_hz"
        if dx in filt and isinstance(filt[dx], (int, float)):
            v = float(filt[dx])
            if skip_zero_hz_min and _is_zero_hz_off(v):
                filt[dx] = 0.0
            else:
                lo, hi = 80, 300
                if v < lo:
                    limits.append(f"{dx}_clamped_min_{lo}")
                    v = float(lo)
                elif v > hi:
                    limits.append(f"{dx}_clamped_max_{hi}")
                    v = float(hi)
                filt[dx] = v

        d2 = "dterm_lpf2_static_hz"
        if d2 in filt and isinstance(filt[d2], (int, float)):
            v = float(filt[d2])
            if v <= 0.0:
                filt[d2] = 0.0
            else:
                lo, hi = 80, 250
                if v < lo:
                    limits.append(f"{d2}_clamped_min_{lo}")
                    v = float(lo)
                elif v > hi:
                    limits.append(f"{d2}_clamped_max_{hi}")
                    v = float(hi)
                filt[d2] = v

        scalar_ranges = {
            "dyn_notch_width_percent": (0, 20),
            "rpm_filter_min_hz": (20, 1000),
            "rpm_filter_max_hz": (100, 2000),
            "rpm_filter_fade_range_hz": (0, 500),
            "dyn_idle_min_rpm": (0, 200),
            "anti_gravity_gain": (0, 20000),
            "anti_gravity_cutoff": (0, 250),
            "anti_gravity_p_gain": (0, 1000),
            "feedforward_smooth_factor": (0, 100),
            "feedforward_jitter_factor": (0, 100),
            "feedforward_boost": (0, 100),
            "feedforward_transition": (0, 100),
            "rc_smoothing": (0, 1),
            "rc_smoothing_feedforward": (0, 100),
            "iterm_relax": (0, 3),
            "iterm_rotation": (0, 1),
            "tpa_rate": (0, 100),
            "tpa_breakpoint": (1000, 2000),
            "throttle_boost": (0, 100),
            "motor_output_limit": (1, 100),
        }
        for key, (lo, hi) in scalar_ranges.items():
            if key not in filt or not isinstance(filt[key], (int, float)):
                continue
            v = float(filt[key])
            if v < lo:
                limits.append(f"{key}_clamped_min_{lo}")
                v = float(lo)
            elif v > hi:
                limits.append(f"{key}_clamped_max_{hi}")
                v = float(hi)
            filt[key] = v

        gdm = filt.get("gyro_lpf1_dyn_min_hz")
        gdx = filt.get("gyro_lpf1_dyn_max_hz")
        if isinstance(gdm, (int, float)) and isinstance(gdx, (int, float)):
            if float(gdm) > 1e-6 and float(gdx) < float(gdm):
                filt["gyro_lpf1_dyn_max_hz"] = float(gdm)
                limits.append("gyro_lpf1_dyn_max_hz_raised_to_dyn_min")

        dmn = filt.get("dterm_lpf1_dyn_min_hz")
        dmx = filt.get("dterm_lpf1_dyn_max_hz")
        if isinstance(dmn, (int, float)) and isinstance(dmx, (int, float)):
            if float(dmn) > 1e-6 and float(dmx) < float(dmn) + 10.0:
                filt["dterm_lpf1_dyn_max_hz"] = float(dmn) + 10.0
                limits.append("dterm_lpf1_dyn_max_hz_raised_to_dyn_min_plus_10")

    pid = out.get("pid")
    if isinstance(pid, dict):
        for axis in ("roll", "pitch", "yaw"):
            ax = pid.get(axis)
            if not isinstance(ax, dict):
                continue
            if apply_donor_pid_advisory:
                for comp, lo, hi in (
                    ("p", 10, 100),
                    ("d", 5, 85),
                    ("ff", 0, 220),
                ):
                    if comp not in ax or not isinstance(ax[comp], (int, float)):
                        continue
                    v = float(ax[comp])
                    # Autotune path: firmware-legal 0 (yaw D) is not raised to
                    # donor advisory minima.
                    if preserve_firmware_zeros and lo > 0 and _is_zero_hz_off(v):
                        continue
                    if v < lo:
                        limits.append(f"{axis}_{comp}_clamped_min_{lo}")
                        v = float(lo)
                    elif v > hi:
                        limits.append(f"{axis}_{comp}_clamped_max_{hi}")
                        v = float(hi)
                    ax[comp] = v
            for comp, (lo, hi) in FIRMWARE_PID_HARD_RANGES.items():
                if comp not in ax or not isinstance(ax[comp], (int, float)):
                    continue
                v = float(ax[comp])
                if v < lo:
                    limits.append(f"{axis}_{comp}_firmware_clamped_min_{lo}")
                    v = float(lo)
                elif v > hi:
                    limits.append(f"{axis}_{comp}_firmware_clamped_max_{hi}")
                    v = float(hi)
                ax[comp] = v
    return limits


def apply_safety(
    config: dict[str, Any],
    hardware: Mapping[str, Any] | None = None,
    confidence: float | None = None,
    *,
    baseline: dict[str, Any] | None = None,
    skip_zero_hz_min: bool = False,
    preserve_firmware_zeros: bool = False,
    apply_donor_pid_advisory: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    limits: list[str] = []
    out = _deep_merge_template(config)

    conf_f: float | None = None
    if confidence is not None:
        try:
            conf_f = float(confidence)
        except (TypeError, ValueError):
            conf_f = None
        if conf_f is not None and not math.isfinite(conf_f):
            conf_f = None

    if conf_f is not None and conf_f < CONFIDENCE_BLEND_THRESHOLD and baseline is not None:
        out = _blend_toward_baseline(out, baseline, 0.5)
        limits.append("confidence_blend_50pct_toward_baseline")

    hw = hardware if isinstance(hardware, Mapping) else None
    if hw is not None:
        try:
            w = float(hw.get("weight", 0.0))
        except (TypeError, ValueError):
            w = 0.0
        if math.isfinite(w) and w > HARDWARE_WEIGHT_D_SCALE_KG:
            pid = out.get("pid")
            if isinstance(pid, dict):
                for axis in ("roll", "pitch", "yaw"):
                    ax = pid.get(axis)
                    if isinstance(ax, dict) and "d" in ax and isinstance(ax["d"], (int, float)):
                        try:
                            ax["d"] = float(ax["d"]) * HARDWARE_WEIGHT_D_FACTOR
                        except (TypeError, ValueError):
                            pass
                    if isinstance(ax, dict) and "d_max" in ax and isinstance(ax["d_max"], (int, float)):
                        try:
                            ax["d_max"] = float(ax["d_max"]) * HARDWARE_WEIGHT_D_FACTOR
                        except (TypeError, ValueError):
                            pass
            limits.append("hardware_weight_d_scaled_90pct")

    limits.extend(
        _apply_hard_clamp_ranges_to_config(
            out,
            skip_zero_hz_min=skip_zero_hz_min or preserve_firmware_zeros,
            preserve_firmware_zeros=preserve_firmware_zeros or skip_zero_hz_min,
            apply_donor_pid_advisory=apply_donor_pid_advisory,
        )
    )
    return out, limits


def apply_safety_autotune(
    config: dict[str, Any],
    hardware: Mapping[str, Any] | None = None,
    confidence: float | None = None,
    *,
    baseline: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Autotune-path apply_safety: keep firmware OFF (0 Hz); still apply donor PID advisory ranges."""
    return apply_safety(
        config,
        hardware,
        confidence,
        baseline=baseline,
        skip_zero_hz_min=True,
        preserve_firmware_zeros=True,
        apply_donor_pid_advisory=True,
    )


def record_numeric_clamps(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    rule_prefix: str,
) -> list[SafetyCheck]:
    checks: list[SafetyCheck] = []
    bp = before.get("pid") if isinstance(before.get("pid"), Mapping) else {}
    ap = after.get("pid") if isinstance(after.get("pid"), Mapping) else {}
    for axis in ("roll", "pitch", "yaw"):
        bax = bp.get(axis) if isinstance(bp.get(axis), Mapping) else {}
        aax = ap.get(axis) if isinstance(ap.get(axis), Mapping) else {}
        for comp in ("p", "i", "d", "ff", "d_max"):
            if comp not in bax or comp not in aax:
                continue
            try:
                bv, av = float(bax[comp]), float(aax[comp])
            except (TypeError, ValueError):
                continue
            if abs(bv - av) > 1e-9:
                checks.append(
                    SafetyCheck(
                        rule_id=f"{rule_prefix}:{axis}.{comp}",
                        verdict=SafetyVerdict.WARN,
                        message=f"{axis}.{comp} clamped",
                        before=bv,
                        after=av,
                    )
                )
    bf = before.get("filters") if isinstance(before.get("filters"), Mapping) else {}
    af = after.get("filters") if isinstance(after.get("filters"), Mapping) else {}
    for key in set(bf) | set(af):
        if key not in bf or key not in af:
            continue
        try:
            bv, av = float(bf[key]), float(af[key])
        except (TypeError, ValueError):
            continue
        if abs(bv - av) > 1e-9:
            checks.append(
                SafetyCheck(
                    rule_id=f"{rule_prefix}:filter.{key}",
                    verdict=SafetyVerdict.WARN,
                    message=f"{key} clamped",
                    before=bv,
                    after=av,
                )
            )
    return checks


def apply_thermal_if_needed(
    config: Mapping[str, Any],
    baseline: Mapping[str, Any],
    analysis: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], list[str]]:
    locks: list[str] = []
    enforce = should_enforce_baseline_envelope(analysis)
    out = clamp_targets_to_baseline_thermal(
        config, baseline, thermal_risk=enforce, locks=locks
    )
    return out, locks


__all__ = [
    "CONFIDENCE_BLEND_THRESHOLD",
    "DEFAULT_MAX_DELTA",
    "DONOR_PID_HARD_RANGES",
    "FIRMWARE_PID_HARD_RANGES",
    "apply_safety",
    "apply_safety_autotune",
    "apply_thermal_if_needed",
    "apply_to_baseline",
    "record_numeric_clamps",
    "scale_max_delta",
]
