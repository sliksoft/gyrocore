"""Betaflight 2026.6.2 CLI names and canonical emit order (WU11).

Names come from firmware ``parameter_names.h``, WU2 ``cli.py`` output keys,
and the BBL alias ``d_max`` → CLI ``d_min_*``.
"""

from __future__ import annotations

from gyrocore.betaflight.simplified_tuning import (
    DYN_LPF_MAX_HZ,
    F_GAIN_MAX,
    FIRMWARE_PROVENANCE,
    LPF_MAX_HZ,
    PID_GAIN_MAX,
)

FIRMWARE_CLI_PROVENANCE = {
    **dict(FIRMWARE_PROVENANCE),
    "cli_names": [
        "fc/parameter_names.h",
        "WU2 core/gyrocore/betaflight/cli.py:_PID_CLI_OUTPUT",
        "blackbox-log-viewer flightlog_parser.js alias d_max→d_min",
    ],
}

# Internal component → 2026.6.2 CLI name.
PID_CLI_KEYS: tuple[tuple[str, str, str], ...] = (
    ("roll", "p", "p_roll"),
    ("roll", "i", "i_roll"),
    ("roll", "d", "d_roll"),
    ("roll", "ff", "f_roll"),
    ("roll", "d_max", "d_min_roll"),
    ("pitch", "p", "p_pitch"),
    ("pitch", "i", "i_pitch"),
    ("pitch", "d", "d_pitch"),
    ("pitch", "ff", "f_pitch"),
    ("pitch", "d_max", "d_min_pitch"),
    ("yaw", "p", "p_yaw"),
    ("yaw", "i", "i_yaw"),
    ("yaw", "d", "d_yaw"),
    ("yaw", "ff", "f_yaw"),
    ("yaw", "d_max", "d_min_yaw"),
)

GYRO_FILTER_CLI_KEYS: tuple[tuple[str, str], ...] = (
    ("lpf1_dyn_min_hz", "gyro_lpf1_dyn_min_hz"),
    ("lpf1_dyn_max_hz", "gyro_lpf1_dyn_max_hz"),
    ("lpf1_static_hz", "gyro_lpf1_static_hz"),
    ("lpf2_static_hz", "gyro_lpf2_static_hz"),
)

DTERM_FILTER_CLI_KEYS: tuple[tuple[str, str], ...] = (
    ("lpf1_dyn_min_hz", "dterm_lpf1_dyn_min_hz"),
    ("lpf1_dyn_max_hz", "dterm_lpf1_dyn_max_hz"),
    ("lpf1_static_hz", "dterm_lpf1_static_hz"),
    ("lpf2_static_hz", "dterm_lpf2_static_hz"),
)

CANONICAL_SET_ORDER: tuple[str, ...] = (
    *(key for _axis, _comp, key in PID_CLI_KEYS),
    *(key for _field, key in GYRO_FILTER_CLI_KEYS),
    *(key for _field, key in DTERM_FILTER_CLI_KEYS),
)

CLI_RANGES: dict[str, tuple[int, int]] = {
    **{key: (0, PID_GAIN_MAX) for _a, comp, key in PID_CLI_KEYS if comp != "ff"},
    **{key: (0, F_GAIN_MAX) for _a, comp, key in PID_CLI_KEYS if comp == "ff"},
    "gyro_lpf1_dyn_min_hz": (0, DYN_LPF_MAX_HZ),
    "gyro_lpf1_dyn_max_hz": (0, DYN_LPF_MAX_HZ),
    "gyro_lpf1_static_hz": (0, LPF_MAX_HZ),
    "gyro_lpf2_static_hz": (0, LPF_MAX_HZ),
    "dterm_lpf1_dyn_min_hz": (0, DYN_LPF_MAX_HZ),
    "dterm_lpf1_dyn_max_hz": (0, DYN_LPF_MAX_HZ),
    "dterm_lpf1_static_hz": (0, LPF_MAX_HZ),
    "dterm_lpf2_static_hz": (0, LPF_MAX_HZ),
}

ALLOWED_CLI_KEYS = frozenset(CANONICAL_SET_ORDER)
PID_PROFILE_MAX = 3
SAVE_COMMAND = "save"

__all__ = [
    "ALLOWED_CLI_KEYS",
    "CANONICAL_SET_ORDER",
    "CLI_RANGES",
    "DTERM_FILTER_CLI_KEYS",
    "FIRMWARE_CLI_PROVENANCE",
    "GYRO_FILTER_CLI_KEYS",
    "PID_CLI_KEYS",
    "PID_PROFILE_MAX",
    "SAVE_COMMAND",
]
