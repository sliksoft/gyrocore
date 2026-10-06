"""Betaflight CLI dump parsing and baseline validity (WU2 extract).

Extracted from AeroTuner ``backend/services/tuning_safe_v2.py`` parse/validation
surface only. Tune generation (``generate_cli``, ``generate_v2_safe_tune``,
``apply_safety``, etc.) is intentionally NOT migrated.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

_SET_LINE_RE = re.compile(
    r"^\s*set\s+([a-zA-Z0-9_]+)\s*=\s*(.+?)\s*$",
    re.IGNORECASE,
)

# CLI name -> (axis, component) for rate PID
# ``roll_f`` / ``pitch_f`` / ``yaw_f`` are common Betaflight aliases for feedforward (``*_ff``).
_PID_CLI_NAMES: dict[str, tuple[str, str]] = {
    "roll_p": ("roll", "p"),
    "roll_i": ("roll", "i"),
    "roll_d": ("roll", "d"),
    "roll_ff": ("roll", "ff"),
    "roll_f": ("roll", "ff"),
    "pitch_p": ("pitch", "p"),
    "pitch_i": ("pitch", "i"),
    "pitch_d": ("pitch", "d"),
    "pitch_ff": ("pitch", "ff"),
    "pitch_f": ("pitch", "ff"),
    "yaw_p": ("yaw", "p"),
    "yaw_i": ("yaw", "i"),
    "yaw_d": ("yaw", "d"),
    "yaw_ff": ("yaw", "ff"),
    "yaw_f": ("yaw", "ff"),
}

# Betaflight dumps / profile blocks often use ``p_roll`` / ``d_pitch`` / ``f_yaw`` naming.
# Parsed only; :func:`generate_cli` emits Betaflight ``p_roll``-style output keys.
_PID_CLI_BF_ALT_NAMES: dict[str, tuple[str, str]] = {
    "p_roll": ("roll", "p"),
    "p_pitch": ("pitch", "p"),
    "p_yaw": ("yaw", "p"),
    "i_roll": ("roll", "i"),
    "i_pitch": ("pitch", "i"),
    "i_yaw": ("yaw", "i"),
    "d_roll": ("roll", "d"),
    "d_pitch": ("pitch", "d"),
    "d_yaw": ("yaw", "d"),
    "f_roll": ("roll", "ff"),
    "f_pitch": ("pitch", "ff"),
    "f_yaw": ("yaw", "ff"),
    "ff_roll": ("roll", "ff"),
    "ff_pitch": ("pitch", "ff"),
    "ff_yaw": ("yaw", "ff"),
}

# Canonical output mapping: one entry per (axis, component) — no duplicates.
# Maps internal (axis, comp) to the Betaflight 4.4+ CLI key (component_axis format).
_PID_CLI_OUTPUT: tuple[tuple[str, str, str], ...] = (
    ("pitch", "d", "d_pitch"),
    ("pitch", "ff", "f_pitch"),
    ("pitch", "i", "i_pitch"),
    ("pitch", "p", "p_pitch"),
    ("roll", "d", "d_roll"),
    ("roll", "ff", "f_roll"),
    ("roll", "i", "i_roll"),
    ("roll", "p", "p_roll"),
    ("yaw", "d", "d_yaw"),
    ("yaw", "ff", "f_yaw"),
    ("yaw", "i", "i_yaw"),
    ("yaw", "p", "p_yaw"),
)

_D_MIN_CLI_NAMES: dict[str, str] = {
    "d_min_pitch": "pitch",
    "d_min_roll": "roll",
    "d_min_yaw": "yaw",
    "d_min_boost_gain": "boost_gain",
    "d_min_advance": "advance",
}

_FILTER_CLI_KEYS: frozenset[str] = frozenset(
    {
        "gyro_lpf1_static_hz",
        "gyro_lpf1_dyn_min_hz",
        "gyro_lpf1_dyn_max_hz",
        "gyro_lpf1_dyn_expo",
        "gyro_lpf2_static_hz",
        "gyro_notch1_hz",
        "gyro_notch1_cutoff",
        "gyro_notch2_hz",
        "gyro_notch2_cutoff",
        "dterm_lpf1_static_hz",
        "dterm_lpf1_dyn_min_hz",
        "dterm_lpf1_dyn_max_hz",
        "dterm_lpf1_dyn_expo",
        "dterm_lpf2_static_hz",
        "dterm_notch_hz",
        "dterm_notch_cutoff",
        "dyn_notch_count",
        "dyn_notch_min_hz",
        "dyn_notch_max_hz",
        "dyn_notch_q",
        "dyn_notch_width_percent",
        "yaw_lowpass_hz",
        "rpm_filter_harmonics",
        "rpm_filter_min_hz",
        "rpm_filter_max_hz",
        "rpm_filter_fade_range_hz",
        "rpm_filter_lpf_hz",
        "rpm_filter_q",
        "motor_poles",
        "dyn_idle_min_rpm",
        "transient_throttle_limit",
        "anti_gravity_gain",
        "anti_gravity_cutoff",
        "anti_gravity_p_gain",
        "feedforward_smooth_factor",
        "feedforward_jitter_factor",
        "feedforward_boost",
        "feedforward_transition",
        "ff_interpolate_sp",
        "rc_smoothing",
        "rc_smoothing_auto_factor",
        "rc_smoothing_feedforward",
        "iterm_relax",
        "iterm_rotation",
        "tpa_rate",
        "tpa_breakpoint",
        "throttle_boost",
        "motor_output_limit",
        "gyro_lpf1_type",
        "gyro_lpf2_type",
        "dterm_lpf1_type",
        "dterm_lpf2_type",
        "pid_process_denom",
        "motor_pwm_protocol",
        "blackbox_sample_rate",
        "blackbox_rate_denom",
        "simplified_master_multiplier",
        "simplified_pids_mode",
        "simplified_d_gain",
        "simplified_dmax_gain",
        "simplified_gyro_filter",
        "simplified_dterm_filter",
        "simplified_gyro_filter_multiplier",
        "simplified_dterm_filter_multiplier",
        "vbat_sag_compensation",
        "pidsum_limit",
        "pidsum_limit_yaw",
        "iterm_relax_cutoff",
        "feedforward_averaging",
    }
)

_FILTER_CLI_ENUM_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "gyro_lpf1_type",
        "gyro_lpf2_type",
        "dterm_lpf1_type",
        "dterm_lpf2_type",
        "motor_pwm_protocol",
        "simplified_pids_mode",
        "simplified_gyro_filter",
        "simplified_dterm_filter",
        "feedforward_averaging",
    }
)

_FILTER_CLI_FLOAT_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "simplified_master_multiplier",
        "simplified_d_gain",
        "simplified_dmax_gain",
        "simplified_gyro_filter",
        "simplified_dterm_filter",
        "simplified_gyro_filter_multiplier",
        "simplified_dterm_filter_multiplier",
        "iterm_relax_cutoff",
        "vbat_sag_compensation",
    }
)

_FILTER_CLI_BOOL_KEYS: frozenset[str] = frozenset(
    {
        "rpm_filter",
        "dshot_bidir",
    }
)

_FILTER_CLI_CONTEXT_ONLY_KEYS: frozenset[str] = frozenset(
    {
        "rpm_filter",
        "dshot_bidir",
        "motor_poles",
        "transient_throttle_limit",
        "ff_interpolate_sp",
        "rc_smoothing_auto_factor",
        "gyro_lpf1_type",
        "gyro_lpf2_type",
        "dterm_lpf1_type",
        "dterm_lpf2_type",
        "pid_process_denom",
        "motor_pwm_protocol",
        "blackbox_sample_rate",
        "blackbox_rate_denom",
        "simplified_master_multiplier",
        "simplified_pids_mode",
        "simplified_d_gain",
        "simplified_dmax_gain",
        "simplified_gyro_filter",
        "simplified_dterm_filter",
        "simplified_gyro_filter_multiplier",
        "simplified_dterm_filter_multiplier",
        "vbat_sag_compensation",
        "pidsum_limit",
        "pidsum_limit_yaw",
        "iterm_relax_cutoff",
        "feedforward_averaging",
    }
)
def _empty_config() -> dict[str, Any]:
    return {
        "filters": {},
        "pid": {"roll": {}, "pitch": {}, "yaw": {}},
        "meta": {},
        "_recognized_set_count": 0,
        "_raw_set_count": 0,
    }


def _coerce_number(raw: str) -> float | None:
    s = raw.strip().strip('"').strip("'")
    if not s:
        return None
    up = s.upper()
    if up in ("OFF", "NONE", "AUTO"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if not math.isfinite(v):
        return None
    return v


def _coerce_bool(raw: str) -> bool | None:
    s = raw.strip().strip('"').strip("'").upper()
    if s in ("ON", "TRUE", "YES", "1", "ENABLED", "ENABLE"):
        return True
    if s in ("OFF", "FALSE", "NO", "0", "DISABLED", "DISABLE", "NONE"):
        return False
    return None


def _coerce_enum(raw: str) -> str | None:
    s = str(raw or "").strip().strip('"').strip("'")
    if not s:
        return None
    return s.upper()


def parse_cli_dump(cli_dump: str | None) -> dict[str, Any]:
    """
    Parse a Betaflight ``dump`` / ``diff`` style text block (``set name = value`` lines).

    Returns ``{"filters": {...}, "pid": {"roll"|"pitch"|"yaw": {p|i|d|ff: number}}}}``.
    Accepts canonical ``roll_p`` / ``roll_ff`` names and common alternates ``p_roll`` /
    ``f_roll`` / ``ff_roll`` from profile dumps. Unrecognized keys are ignored.
    Non-numeric values (e.g. OFF) are skipped.
    """
    out = _empty_config()
    if not cli_dump or not str(cli_dump).strip():
        return out

    for line in str(cli_dump).splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if re.match(r"^feature\s+3d(?:\s|$)", s, re.IGNORECASE):
            out["meta"]["feature_3d"] = True
            out["_recognized_set_count"] += 1
            continue
        # Bare CLI commands (not "set X = Y"): board_name TARGET and manufacturer_id MFR
        board_name_match = re.match(r"^board_name\s+(\S+)\s*$", s, re.IGNORECASE)
        if board_name_match:
            out["meta"]["board_name"] = board_name_match.group(1).strip()
            out["_recognized_set_count"] += 1
            continue
        manufacturer_id_match = re.match(r"^manufacturer_id\s+(\S+)\s*$", s, re.IGNORECASE)
        if manufacturer_id_match:
            out["meta"]["manufacturer_id"] = manufacturer_id_match.group(1).strip()
            out["_recognized_set_count"] += 1
            continue
        profile_match = re.match(r"^profile\s+(\d+)\s*$", s, re.IGNORECASE)
        if profile_match:
            out["meta"]["pid_profile"] = int(profile_match.group(1))
            out["meta"]["profile_marker_count"] = int(out["meta"].get("profile_marker_count") or 0) + 1
            out["_recognized_set_count"] += 1
            continue
        rateprofile_match = re.match(r"^rateprofile\s+(\d+)\s*$", s, re.IGNORECASE)
        if rateprofile_match:
            out["meta"]["rate_profile"] = int(rateprofile_match.group(1))
            out["meta"]["rateprofile_marker_count"] = int(out["meta"].get("rateprofile_marker_count") or 0) + 1
            out["_recognized_set_count"] += 1
            continue
        m = _SET_LINE_RE.match(s)
        if not m:
            continue
        out["_raw_set_count"] += 1
        name = m.group(1).strip().lower()
        val_raw = m.group(2)
        if name in {"pid_profile_name", "rate_profile_name"}:
            out["meta"][name] = val_raw.strip().strip('"').strip("'")
            out["_recognized_set_count"] += 1
            continue
        if name in _FILTER_CLI_ENUM_CONTEXT_KEYS:
            enum_val = _coerce_enum(val_raw)
            if enum_val is not None:
                out["filters"][name] = enum_val
                out["_recognized_set_count"] += 1
            continue
        bool_val = _coerce_bool(val_raw)
        if name in _FILTER_CLI_BOOL_KEYS and bool_val is not None:
            out["filters"][name] = bool_val
            out["_recognized_set_count"] += 1
            continue

        num = _coerce_number(val_raw)
        if num is None:
            continue

        if name in _FILTER_CLI_KEYS:
            if name == "dyn_notch_count":
                out["filters"][name] = max(0, int(round(num)))
            elif name in _FILTER_CLI_FLOAT_CONTEXT_KEYS:
                out["filters"][name] = float(num)
            else:
                out["filters"][name] = int(round(num))
            out["_recognized_set_count"] += 1
            continue

        if name in {"pid_profile", "rate_profile"}:
            out["meta"][name] = int(round(num))
            out["_recognized_set_count"] += 1
            continue

        d_min_key = _D_MIN_CLI_NAMES.get(name)
        if d_min_key is not None:
            out.setdefault("d_min", {})[d_min_key] = int(round(num))
            out["_recognized_set_count"] += 1
            continue

        pid_map = _PID_CLI_NAMES.get(name) or _PID_CLI_BF_ALT_NAMES.get(name)
        if pid_map is not None:
            axis, comp = pid_map
            out["pid"][axis][comp] = int(round(num))
            out["_recognized_set_count"] += 1
            continue

    return out


def cli_dump_baseline_strictly_valid(cli_dump: str | None) -> bool:
    """
    True when a CLI upload looks like a meaningful Betaflight baseline, not a trivial snippet.

    We accept partial ``diff``/``dump`` text, but require at least three recognized ``set`` lines
    so a single stray key or garbled upload cannot silently become the authoritative baseline.
    """
    if cli_dump is None:
        return False
    text = str(cli_dump).strip()
    if len(text) < 20:
        return False
    parsed = parse_cli_dump(text)
    recognized = int(parsed.get("_recognized_set_count") or 0)
    if recognized < 3:
        return False
    filters = parsed.get("filters")
    has_filters = isinstance(filters, Mapping) and any(
        key not in _FILTER_CLI_CONTEXT_ONLY_KEYS for key in filters.keys()
    )
    pid = parsed.get("pid")
    has_pid = False
    if isinstance(pid, Mapping):
        has_pid = any(
            isinstance(pid.get(axis), Mapping) and bool(pid.get(axis))
            for axis in ("roll", "pitch", "yaw")
        )
    return has_filters or has_pid

