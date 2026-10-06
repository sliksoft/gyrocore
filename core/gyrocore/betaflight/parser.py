"""Parse Betaflight blackbox headers (decoded CSV / preamble / header fallbacks) into a tuning profile."""

from __future__ import annotations

import csv
import io
from typing import Any


def empty_tuning_profile() -> dict[str, Any]:
    return {
        "pid": {
            "roll": {"p": None, "i": None, "d": None, "ff": None},
            "pitch": {"p": None, "i": None, "d": None, "ff": None},
            "yaw": {"p": None, "i": None, "d": None, "ff": None},
        },
        "filters": {
            "gyro_lpf1_static_hz": None,
            "gyro_lpf1_dyn_min_hz": None,
            "gyro_lpf1_dyn_max_hz": None,
            "gyro_lpf1_dyn_expo": None,
            "gyro_lpf2_static_hz": None,
            "gyro_lpf1_dyn_hz": None,
            "gyro_notch_hz": None,
            "gyro_notch_cutoff": None,
            "gyro_notch1_hz": None,
            "gyro_notch1_cutoff": None,
            "gyro_notch2_hz": None,
            "gyro_notch2_cutoff": None,
            "dyn_notch_count": None,
            "dyn_notch_q": None,
            "dyn_notch_min_hz": None,
            "dyn_notch_max_hz": None,
            "dyn_notch_width_percent": None,
            "dterm_lpf1_static_hz": None,
            "dterm_lpf1_dyn_min_hz": None,
            "dterm_lpf1_dyn_max_hz": None,
            "dterm_lpf1_dyn_expo": None,
            "dterm_notch_hz": None,
            "dterm_notch_cutoff": None,
            "dterm_lpf2_static_hz": None,
            "yaw_lowpass_hz": None,
            "rpm_filter": None,
            "rpm_filter_harmonics": None,
            "rpm_filter_min_hz": None,
            "rpm_filter_max_hz": None,
            "rpm_filter_fade_range_hz": None,
            "rpm_filter_lpf_hz": None,
            "rpm_filter_q": None,
            "dshot_bidir": None,
            "motor_poles": None,
            "dyn_idle_min_rpm": None,
            "transient_throttle_limit": None,
            "anti_gravity_gain": None,
            "anti_gravity_cutoff": None,
            "anti_gravity_p_gain": None,
            "feedforward_smooth_factor": None,
            "feedforward_jitter_factor": None,
            "feedforward_boost": None,
            "feedforward_transition": None,
            "ff_interpolate_sp": None,
            "rc_smoothing": None,
            "rc_smoothing_auto_factor": None,
            "rc_smoothing_feedforward": None,
            "iterm_relax": None,
            "iterm_rotation": None,
            "tpa_rate": None,
            "tpa_breakpoint": None,
            "throttle_boost": None,
            "motor_output_limit": None,
        },
        "rates": {
            "rc_rates": None,
            "rc_expo": None,
            "rates": None,
            "rate_limits": None,
        },
        "meta": {
            "firmware": None,
            "craft_name": None,
            "feature_3d": None,
            "pid_profile": None,
            "rate_profile": None,
            "pid_profile_name": None,
            "rate_profile_name": None,
        },
    }


def _split_int_triple(s: str) -> tuple[int | None, int | None, int | None]:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) < 3:
        return (None, None, None)
    out: list[int | None] = []
    for p in parts[:3]:
        try:
            out.append(int(float(p)))
        except ValueError:
            out.append(None)
    return (out[0], out[1], out[2])


def _parse_int(val: str | None) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(float(val))
    except ValueError:
        return None


def _parse_bool(val: str | None) -> bool | None:
    if val is None:
        return None
    s = str(val).strip().strip('"').strip("'").lower()
    if s in {"on", "true", "yes", "1", "enabled", "enable"}:
        return True
    if s in {"off", "false", "no", "0", "disabled", "disable", "none"}:
        return False
    return None


def parse_tuning_headers(headers_text: str | None) -> dict[str, Any]:
    out = empty_tuning_profile()
    if not headers_text or not headers_text.strip():
        return out

    text = headers_text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return out

    flat: dict[str, str] = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        key = row[0].strip()
        val = row[1].strip().strip('"')
        if not key:
            continue
        flat[key.lower()] = val

    def set_pid(axis: str, key: str) -> None:
        raw = flat.get(key)
        if not raw:
            return
        p, i, d = _split_int_triple(raw)
        out["pid"][axis]["p"] = p
        out["pid"][axis]["i"] = i
        out["pid"][axis]["d"] = d

    set_pid("roll", "rollpid")
    set_pid("pitch", "pitchpid")
    set_pid("yaw", "yawpid")

    ff = flat.get("ff_weight")
    if ff:
        fr, fp, fy = _split_int_triple(ff)
        out["pid"]["roll"]["ff"] = fr
        out["pid"]["pitch"]["ff"] = fp
        out["pid"]["yaw"]["ff"] = fy

    filt = out["filters"]
    for src, dst in (
        ("gyro_lpf1_static_hz", "gyro_lpf1_static_hz"),
        ("gyro_lpf1_dyn_min_hz", "gyro_lpf1_dyn_min_hz"),
        ("gyro_lpf1_dyn_max_hz", "gyro_lpf1_dyn_max_hz"),
        ("gyro_lpf2_static_hz", "gyro_lpf2_static_hz"),
        ("dyn_notch_count", "dyn_notch_count"),
        ("dyn_notch_q", "dyn_notch_q"),
        ("dyn_notch_min_hz", "dyn_notch_min_hz"),
        ("dyn_notch_max_hz", "dyn_notch_max_hz"),
        ("dyn_notch_width_percent", "dyn_notch_width_percent"),
        ("dterm_lpf1_static_hz", "dterm_lpf1_static_hz"),
        ("dterm_lpf1_dyn_min_hz", "dterm_lpf1_dyn_min_hz"),
        ("dterm_lpf1_dyn_max_hz", "dterm_lpf1_dyn_max_hz"),
        ("dterm_notch_hz", "dterm_notch_hz"),
        ("dterm_notch_cutoff", "dterm_notch_cutoff"),
        ("dterm_lpf2_static_hz", "dterm_lpf2_static_hz"),
        ("yaw_lowpass_hz", "yaw_lowpass_hz"),
        ("rpm_filter_harmonics", "rpm_filter_harmonics"),
        ("rpm_filter_min_hz", "rpm_filter_min_hz"),
        ("rpm_filter_max_hz", "rpm_filter_max_hz"),
        ("rpm_filter_fade_range_hz", "rpm_filter_fade_range_hz"),
        ("rpm_filter_q", "rpm_filter_q"),
        ("motor_poles", "motor_poles"),
        ("dyn_idle_min_rpm", "dyn_idle_min_rpm"),
        ("transient_throttle_limit", "transient_throttle_limit"),
        ("anti_gravity_gain", "anti_gravity_gain"),
        ("anti_gravity_cutoff", "anti_gravity_cutoff"),
        ("anti_gravity_p_gain", "anti_gravity_p_gain"),
        ("feedforward_smooth_factor", "feedforward_smooth_factor"),
        ("feedforward_jitter_factor", "feedforward_jitter_factor"),
        ("feedforward_boost", "feedforward_boost"),
        ("feedforward_transition", "feedforward_transition"),
        ("ff_interpolate_sp", "ff_interpolate_sp"),
        ("rc_smoothing", "rc_smoothing"),
        ("rc_smoothing_auto_factor", "rc_smoothing_auto_factor"),
        ("rc_smoothing_feedforward", "rc_smoothing_feedforward"),
        ("iterm_relax", "iterm_relax"),
        ("iterm_rotation", "iterm_rotation"),
        ("tpa_rate", "tpa_rate"),
        ("tpa_breakpoint", "tpa_breakpoint"),
        ("throttle_boost", "throttle_boost"),
        ("motor_output_limit", "motor_output_limit"),
    ):
        if src in flat:
            filt[dst] = _parse_int(flat[src])

    for src, dst in (
        ("rpm_filter", "rpm_filter"),
        ("dshot_bidir", "dshot_bidir"),
    ):
        if src in flat:
            filt[dst] = _parse_bool(flat[src])

    if "gyro_lpf1_dyn_hz" in flat:
        filt["gyro_lpf1_dyn_hz"] = flat["gyro_lpf1_dyn_hz"]
    if "gyro_notch_hz" in flat:
        filt["gyro_notch_hz"] = flat["gyro_notch_hz"]
    if "gyro_notch_cutoff" in flat:
        filt["gyro_notch_cutoff"] = flat["gyro_notch_cutoff"]

    rates = out["rates"]
    for src, dst in (
        ("rc_rates", "rc_rates"),
        ("rc_expo", "rc_expo"),
        ("rates", "rates"),
        ("rate_limits", "rate_limits"),
    ):
        if src in flat:
            rates[dst] = flat[src]

    if "firmware revision" in flat:
        out["meta"]["firmware"] = flat["firmware revision"]
    if "craft name" in flat:
        out["meta"]["craft_name"] = flat["craft name"]
    for key in ("pid_profile", "profile"):
        if key in flat:
            out["meta"]["pid_profile"] = _parse_int(flat[key])
            break
    for key in ("rate_profile", "rateprofile"):
        if key in flat:
            out["meta"]["rate_profile"] = _parse_int(flat[key])
            break
    if "pid_profile_name" in flat:
        out["meta"]["pid_profile_name"] = flat["pid_profile_name"]
    if "rate_profile_name" in flat:
        out["meta"]["rate_profile_name"] = flat["rate_profile_name"]
    for key in ("feature_3d", "3d", "feature 3d"):
        if key in flat:
            out["meta"]["feature_3d"] = _parse_bool(flat[key])
            break

    return out


def tuning_profile_cli_strictly_valid(tuning: dict[str, Any]) -> bool:
    """
    True when blackbox header tuning looks complete enough to skip a separate CLI dump.

    Requires full PID triple (P, I, D) on roll, pitch, and yaw, plus at least one gyro LPF
    field from headers — matching what Betaflight normally logs in the CSV header block.
    """
    if not isinstance(tuning, dict):
        return False
    pid = tuning.get("pid") or {}
    for axis in ("roll", "pitch", "yaw"):
        block = pid.get(axis)
        if not isinstance(block, dict):
            return False
        if (
            block.get("p") is None
            or block.get("i") is None
            or block.get("d") is None
        ):
            return False
    filt = tuning.get("filters") or {}
    if filt.get("gyro_lpf1_static_hz") is None and filt.get(
        "gyro_lpf2_static_hz",
    ) is None:
        return False
    return True
