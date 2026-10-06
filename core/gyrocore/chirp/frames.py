"""Columnar CHIRP frame table built from GyroCore's decoded Blackbox CSV.

Decoding stays with ``blackbox_decode`` (``gyrocore.decode``); CSV header
discovery and column matching reuse ``gyrocore.parse.blackbox_csv``
(``_find_gyro_header``, ``find_index``, ``find_time_column_index``, decoded-CSV
size limits). This module only selects the exact fields upstream
``parseChirpLog`` reads, because the general analysis parser:

- prefers ``gyro[i]`` / ``gyroUnfilt[i]`` over ``gyroADC[i]`` (upstream CHIRP
  uses ``gyroADC[i]`` only),
- evenly subsamples logs above ``MAX_PARSED_SAMPLES`` (fatal for Welch), and
- keeps ``flightModeFlags`` only when printed as an integer, while
  ``blackbox_decode`` prints flag names by default.

``chirp_frames_from_parsed_samples`` adapts already-parsed
``parse_blackbox_csv`` output when the CSV text is no longer available.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np

from gyrocore.parse.blackbox_csv import (
    FLIGHT_MODE_FLAGS_ALIASES,
    LOOP_ITERATION_ALIASES,
    _find_gyro_header,
    find_index,
    find_time_column_index,
    max_decoded_csv_lines,
    max_decoded_csv_text_bytes,
)

# blackbox-tools src/blackbox_fielddefs.c FLIGHT_LOG_FLIGHT_MODE_NAME (bit order).
# Bit 6 prints as "HEADFREE"; Betaflight CHIRP firmware logs BOXCHIRP in that bit.
FLIGHT_MODE_FLAG_NAMES: tuple[str, ...] = (
    "ANGLE_MODE",
    "HORIZON_MODE",
    "MAG",
    "BARO",
    "GPS_HOME",
    "GPS_HOLD",
    "HEADFREE",
    "UNUSED",
    "PASSTHRU",
    "RANGEFINDER_MODE",
    "FAILSAFE_MODE",
)
BOXCHIRP_BIT = 6
_FLAG_NAME_BITS = {name: bit for bit, name in enumerate(FLIGHT_MODE_FLAG_NAMES)}
_FLAG_NAME_BITS["CHIRP"] = BOXCHIRP_BIT

SETPOINT_FIELDS = ("setpoint[0]", "setpoint[1]", "setpoint[2]")
GYRO_ADC_FIELDS = ("gyroADC[0]", "gyroADC[1]", "gyroADC[2]")
DEBUG_FIELDS = ("debug[0]", "debug[1]", "debug[2]", "debug[3]")
REQUIRED_FIELDS = SETPOINT_FIELDS + GYRO_ADC_FIELDS + DEBUG_FIELDS


class ChirpFramesError(ValueError):
    """Frame table cannot be built (code in ``args[0]``)."""

    @property
    def code(self) -> str:
        return str(self.args[0]).split(":", 1)[0]


@dataclass(frozen=True)
class ChirpFrames:
    """Main-frame rows in log order; values are raw logged integers (float64)."""

    loop_iteration: np.ndarray
    time_us: np.ndarray
    setpoint: np.ndarray  # shape (3, n)
    gyro_adc: np.ndarray  # shape (3, n)
    debug: np.ndarray  # shape (4, n)
    flight_mode_flags: np.ndarray | None  # int64; None when the column is absent
    source: str
    gyro_columns: tuple[str, ...]
    malformed_rows: int = 0
    unknown_flag_tokens: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    subsampled: bool = False
    extra: Mapping[str, Any] = field(default_factory=dict)

    @property
    def frame_count(self) -> int:
        return int(self.time_us.shape[0])


def decode_flight_mode_flags(cell: str, unknown: set[str] | None = None) -> int | None:
    """Integer ``flightModeFlags`` from a ``blackbox_decode`` cell (raw int or ``A|B`` names)."""
    text = cell.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    bits = 0
    for token in text.split("|"):
        name = token.strip()
        if not name:
            continue
        bit = _FLAG_NAME_BITS.get(name.upper())
        if bit is None:
            if unknown is not None:
                unknown.add(name)
            continue
        bits |= 1 << bit
    return bits


def _exact_or_alias(headers: list[str], name: str) -> int | None:
    return find_index(headers, [name, name.replace("[", "").replace("]", "")])


def read_chirp_frames_from_csv(
    csv_text: str,
    *,
    max_text_bytes: int | None = None,
    max_lines: int | None = None,
) -> ChirpFrames:
    """Build a :class:`ChirpFrames` table from ``blackbox_decode`` CSV text (no subsampling)."""
    text_limit = max_decoded_csv_text_bytes() if max_text_bytes is None else max_text_bytes
    line_limit = max_decoded_csv_lines() if max_lines is None else max_lines
    if text_limit > 0 and len(csv_text.encode("utf-8", errors="ignore")) > text_limit:
        raise ChirpFramesError("decoded_csv_too_large")
    if line_limit > 0 and csv_text.count("\n") + 1 > line_limit:
        raise ChirpFramesError("decoded_csv_too_many_lines")

    lines = [line for line in csv_text.splitlines() if line.strip()]
    header_index, headers = _find_gyro_header(lines)
    if header_index is None or not headers:
        raise ChirpFramesError("no_valid_gyro_header")

    idx: dict[str, int] = {}
    missing = []
    for name in REQUIRED_FIELDS:
        i = _exact_or_alias(headers, name)
        if i is None:
            missing.append(name)
        else:
            idx[name] = i
    if missing:
        raise ChirpFramesError("missing_required_field:" + ",".join(missing))
    t_i = find_time_column_index(headers)
    if t_i is None:
        raise ChirpFramesError("missing_required_field:time")
    li_i = find_index(headers, LOOP_ITERATION_ALIASES)
    fm_i = find_index(headers, FLIGHT_MODE_FLAGS_ALIASES)

    cols = [idx[n] for n in REQUIRED_FIELDS]
    max_idx = max(cols + [t_i] + ([li_i] if li_i is not None else []) + ([fm_i] if fm_i is not None else []))
    rows_num: list[list[float]] = []
    times: list[float] = []
    iters: list[float] = []
    flags: list[int] = []
    unknown: set[str] = set()
    malformed = 0
    for line in lines[header_index + 1 :]:
        try:
            row = next(csv.reader([line]))
        except Exception:
            malformed += 1
            continue
        if len(row) <= max_idx:
            malformed += 1
            continue
        try:
            values = [float(row[c]) for c in cols]
            t_val = float(row[t_i])
            it_val = float(row[li_i]) if li_i is not None else float("nan")
        except ValueError:
            malformed += 1
            continue
        flag_val = -1
        if fm_i is not None:
            decoded = decode_flight_mode_flags(row[fm_i], unknown)
            flag_val = -1 if decoded is None else decoded
        rows_num.append(values)
        times.append(t_val)
        iters.append(it_val)
        flags.append(flag_val)

    arr = np.asarray(rows_num, dtype=np.float64).reshape(-1, len(REQUIRED_FIELDS)).T
    warnings: list[str] = []
    if malformed:
        warnings.append("malformed_csv_rows_skipped")
    if unknown:
        warnings.append("unknown_flight_mode_flag_tokens")
    if fm_i is None:
        warnings.append("flight_mode_flags_column_missing")
    return ChirpFrames(
        loop_iteration=np.asarray(iters, dtype=np.float64),
        time_us=np.asarray(times, dtype=np.float64),
        setpoint=arr[0:3].copy(),
        gyro_adc=arr[3:6].copy(),
        debug=arr[6:10].copy(),
        flight_mode_flags=np.asarray(flags, dtype=np.int64) if fm_i is not None else None,
        source="decoded_csv",
        gyro_columns=tuple(headers[idx[n]] for n in GYRO_ADC_FIELDS),
        malformed_rows=malformed,
        unknown_flag_tokens=tuple(sorted(unknown)),
        warnings=tuple(warnings),
    )


def chirp_frames_from_parsed_samples(parsed: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> ChirpFrames:
    """Adapt ``parse_blackbox_csv`` output (or its ``samples`` list) into :class:`ChirpFrames`.

    Raises when the parser subsampled the log or lacks setpoint/debug channels.
    ``flight_mode_flags`` survives only when the CSV printed integer flags.
    """
    meta: Mapping[str, Any] = parsed if isinstance(parsed, Mapping) else {}
    samples = list(meta.get("samples", []) if isinstance(parsed, Mapping) else parsed)
    if meta.get("parse_failed"):
        raise ChirpFramesError(f"parse_failed:{meta.get('message')}")
    if "original_sample_count" in meta:
        raise ChirpFramesError("subsampled_input: parser capped the log; use read_chirp_frames_from_csv")
    if not samples:
        raise ChirpFramesError("no_samples")

    warnings: list[str] = []
    gyro_cols = tuple(str(meta.get(f"gyro_header_{a}") or "") for a in "xyz")
    if meta and not all(c.strip().lower() == f"gyroadc[{i}]" for i, c in enumerate(gyro_cols)):
        warnings.append("gyro_column_not_gyroadc")
    if not meta:
        warnings.append("gyro_column_unknown")

    n = len(samples)
    sp = np.full((3, n), np.nan)
    gy = np.full((3, n), np.nan)
    dbg = np.full((4, n), np.nan)
    t = np.full(n, np.nan)
    it = np.full(n, np.nan)
    fm = np.full(n, -1, dtype=np.int64)
    have_flags = False
    for j, s in enumerate(samples):
        t[j] = float(s.get("t", np.nan))
        it[j] = float(s.get("loop_iteration", np.nan))
        for a, key in enumerate(("setpoint_roll", "setpoint_pitch", "setpoint_yaw")):
            v = s.get(key)
            if v is not None:
                sp[a, j] = float(v)
        for a, key in enumerate(("gx", "gy", "gz")):
            gy[a, j] = float(s[key])
        d = s.get("debug") or []
        for k in range(4):
            if k < len(d) and d[k] is not None:
                dbg[k, j] = float(d[k])
        if s.get("flight_mode_flags") is not None:
            fm[j] = int(s["flight_mode_flags"])
            have_flags = True
    if np.isnan(sp).all(axis=1).any():
        raise ChirpFramesError("missing_required_field:setpoint")
    if np.isnan(dbg).all(axis=1).any():
        raise ChirpFramesError("missing_required_field:debug")
    if not have_flags:
        warnings.append("flight_mode_flags_column_missing")
    return ChirpFrames(
        loop_iteration=it,
        time_us=t,
        setpoint=sp,
        gyro_adc=gy,
        debug=dbg,
        flight_mode_flags=fm if have_flags else None,
        source="parsed_samples",
        gyro_columns=gyro_cols,
        warnings=tuple(warnings),
    )


__all__ = [
    "BOXCHIRP_BIT",
    "ChirpFrames",
    "ChirpFramesError",
    "DEBUG_FIELDS",
    "FLIGHT_MODE_FLAG_NAMES",
    "GYRO_ADC_FIELDS",
    "REQUIRED_FIELDS",
    "SETPOINT_FIELDS",
    "chirp_frames_from_parsed_samples",
    "decode_flight_mode_flags",
    "read_chirp_frames_from_csv",
]
