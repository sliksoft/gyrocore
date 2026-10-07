"""Blackbox CSV → sample dicts (WU3 extract from AeroTuner parser.py).

Environment-variable feature flags are removed; pass ``ParserFeatureFlags``
or rely on defaults. Pre-cap spectral analysis is deferred (not WU3).
"""


from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParserFeatureFlags:
    """Opt-in optional Blackbox columns. Defaults match legacy (parse when present)."""

    enable_erpm: bool = True
    enable_debug: bool = True
    enable_extended_telemetry: bool = True


def default_parser_flags() -> ParserFeatureFlags:
    return ParserFeatureFlags()


def parser_feature_flags_metadata(flags: ParserFeatureFlags | None = None) -> dict[str, bool]:
    """Active optional-column flags for analyze metadata."""
    active = flags or default_parser_flags()
    return {
        "enable_erpm": bool(active.enable_erpm),
        "enable_debug": bool(active.enable_debug),
        "enable_extended_telemetry": bool(active.enable_extended_telemetry),
    }


DEFAULT_PARSER_FLAGS: ParserFeatureFlags = ParserFeatureFlags()

MAX_PARSED_SAMPLES = 20000
DEFAULT_MAX_DECODED_CSV_TEXT_BYTES = 96 * 1024 * 1024
DEFAULT_MAX_DECODED_CSV_LINES = 750_000


def max_decoded_csv_text_bytes() -> int:
    """Legacy helper; prefer CoreConfig.max_decoded_csv_bytes when calling parse APIs."""
    return DEFAULT_MAX_DECODED_CSV_TEXT_BYTES


def max_decoded_csv_lines() -> int:
    return DEFAULT_MAX_DECODED_CSV_LINES


def _duration_seconds_wall_clock(samples: list[dict]) -> float:
    """Duration from first to last sample in list order (``t`` in microseconds)."""
    if len(samples) < 2:
        return 0.0
    try:
        t0 = int(samples[0]["t"])
        t1 = int(samples[-1]["t"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    return max(0.0, float(t1 - t0) / 1e6)


def evenly_subsample_parsed_samples(samples: list[dict], max_n: int) -> list[dict]:
    """
    Evenly spaced indices from first through last row (inclusive), up to ``max_n`` rows.

    Preserves wall-clock span in ``t`` (first and last timestamps of the full log remain
    in the subset). Use after parsing the full row set so large logs are not mistaken
    for ~10 s clips when only the first *max_n* rows were kept.
    """
    n = len(samples)
    if max_n < 1:
        return []
    if n <= max_n:
        return samples
    if max_n == 1:
        return [samples[0]]
    denom = max_n - 1
    indices = [(k * (n - 1)) // denom for k in range(max_n)]
    return [samples[i] for i in indices]


# Prefer blackbox_decode-style deg/s columns (gyro[i]) over raw gyroADC[i] when both exist.
GYRO_ALIASES = [
    "gyro[0]",
    "gyro_unfilt[0]",
    "gyrounfilt[0]",
    "gyro_roll",
    "gx",
    "gyroadc[0]",
]
GYRO_Y_ALIASES = [
    "gyro[1]",
    "gyro_unfilt[1]",
    "gyrounfilt[1]",
    "gyro_pitch",
    "gy",
    "gyroadc[1]",
]
GYRO_Z_ALIASES = [
    "gyro[2]",
    "gyro_unfilt[2]",
    "gyrounfilt[2]",
    "gyro_yaw",
    "gz",
    "gyroadc[2]",
]

# Cumulative log time (µs). Keep ``looptime`` separate: it is per-iteration duration,
# not session time, and must not win over a real time column on the same row.
TIME_ALIASES = ["time", "timeus", "time (us)", "looptime"]
TIME_PRIMARY_ALIASES = ["time", "timeus", "time (us)"]
TIME_LOOPTIME_ALIASES = ["looptime"]

THROTTLE_ALIASES = [
    "rccommand[3]",
    "rc_command[3]",
    "rccommands[3]",
    "throttle",
    "rc3",
]

MOTOR_ALIASES = [
    ["motor[0]", "motor0", "motor_0", "m[0]", "m0"],
    ["motor[1]", "motor1", "motor_1", "m[1]", "m1"],
    ["motor[2]", "motor2", "motor_2", "m[2]", "m2"],
    ["motor[3]", "motor3", "motor_3", "m[3]", "m3"],
]

SETPOINT_ROLL = ["setpoint[0]", "setpoint_roll"]
SETPOINT_PITCH = ["setpoint[1]", "setpoint_pitch"]
SETPOINT_YAW = ["setpoint[2]", "setpoint_yaw"]

PID_P_ALIASES = [
    ["axisP[0]", "axisp[0]", "p_roll", "axisP_roll", "axis_p_roll"],
    ["axisP[1]", "axisp[1]", "p_pitch", "axisP_pitch", "axis_p_pitch"],
    ["axisP[2]", "axisp[2]", "p_yaw", "axisP_yaw", "axis_p_yaw"],
]
PID_I_ALIASES = [
    ["axisI[0]", "axisi[0]", "i_roll", "axisI_roll", "axis_i_roll"],
    ["axisI[1]", "axisi[1]", "i_pitch", "axisI_pitch", "axis_i_pitch"],
    ["axisI[2]", "axisi[2]", "i_yaw", "axisI_yaw", "axis_i_yaw"],
]
PID_D_ALIASES = [
    ["axisD[0]", "axisd[0]", "axisD_roll", "axis_d_roll", "dterm_roll", "roll_d"],
    ["axisD[1]", "axisd[1]", "axisD_pitch", "axis_d_pitch", "dterm_pitch", "pitch_d"],
    ["axisD[2]", "axisd[2]", "axisD_yaw", "axis_d_yaw", "dterm_yaw", "yaw_d"],
]
PID_F_ALIASES = [
    ["axisF[0]", "axisf[0]", "f_roll", "axisF_roll", "axis_f_roll", "feedforward_roll"],
    ["axisF[1]", "axisf[1]", "f_pitch", "axisF_pitch", "axis_f_pitch", "feedforward_pitch"],
    ["axisF[2]", "axisf[2]", "f_yaw", "axisF_yaw", "axis_f_yaw", "feedforward_yaw"],
]

# Optional columns (gated by ParserFeatureFlags)
ERPM_SINGLE_ALIASES = ["erpm", "erpm_avg", "eRPM"]
ERPM_MOTOR_ALIASES = [
    ["erpm[0]", "eRPM[0]", "motor_erpm[0]", "motor_erpm0"],
    ["erpm[1]", "eRPM[1]", "motor_erpm[1]", "motor_erpm1"],
    ["erpm[2]", "eRPM[2]", "motor_erpm[2]", "motor_erpm2"],
    ["erpm[3]", "eRPM[3]", "motor_erpm[3]", "motor_erpm3"],
]

LOOP_ITERATION_ALIASES = ["loopiteration", "loop_iter", "loop iteration"]
FLIGHT_MODE_FLAGS_ALIASES = [
    "flightmodeflags",
    "flight_mode_flags",
    "flightmodestate",
    "flight_mode",
]


def _debug_channel_aliases(channel: int) -> list[str]:
    return [f"debug[{channel}]", f"debug{channel}", f"debug ({channel})"]


def _norm_header(h: str) -> str:
    return h.strip().lower()


def _header_lower_list(headers: list[str]) -> list[str]:
    return [_norm_header(h) for h in headers]


def find_index(headers: list[str], aliases: Iterable[str]) -> Optional[int]:
    """Match Betaflight-style column names (case-insensitive)."""
    lower = _header_lower_list(headers)
    for a in aliases:
        key = _norm_header(str(a))
        try:
            return lower.index(key)
        except ValueError:
            continue
    for a in aliases:
        key = _norm_header(str(a))
        # Avoid "gy" matching "gyro[1]", "gx" matching "gyro[0]", etc.
        if len(key) <= 2:
            continue
        for i, hl in enumerate(lower):
            if key == hl or key in hl or hl in key:
                return i
    return None


def find_time_column_index(headers: list[str]) -> Optional[int]:
    """
    Resolve the blackbox **cumulative** time column (microseconds).

    Tries primary names first (exact, then fuzzy). Fuzzy alias ``time`` must not
    match ``looptime`` (substring false positive). ``looptime`` alone is only
    used as a last resort when no primary or fuzzy cumulative column exists.
    """
    lower = _header_lower_list(headers)
    for a in TIME_PRIMARY_ALIASES:
        key = _norm_header(str(a))
        try:
            return lower.index(key)
        except ValueError:
            continue
    for a in TIME_PRIMARY_ALIASES:
        key = _norm_header(str(a))
        if len(key) <= 2:
            continue
        for i, hl in enumerate(lower):
            if key == "time" and hl == "looptime":
                continue
            if key == hl or key in hl or hl in key:
                return i
    for a in TIME_LOOPTIME_ALIASES:
        key = _norm_header(str(a))
        try:
            return lower.index(key)
        except ValueError:
            continue
    return None


def _fallback_throttle_index(headers: list[str]) -> Optional[int]:
    """Discover rcCommand[3] / throttle when exact alias match fails."""
    lower = _header_lower_list(headers)
    for i, hl in enumerate(lower):
        if hl == "rccommand[3]" or hl == "rc_command[3]":
            return i
        if "rccommand" in hl.replace(" ", "") and "[3]" in hl:
            return i
        if hl == "throttle" or hl.endswith("_throttle"):
            return i
    return None


def _fallback_motor_indices(headers: list[str]) -> list[Optional[int]]:
    """Discover motor[0..3] columns by regex on header names."""
    lower = _header_lower_list(headers)
    out: list[Optional[int]] = [None, None, None, None]
    pat_bracket = re.compile(r"^motor\[(\d)\]$")
    pat_plain = re.compile(r"^motor(\d)$")
    pat_m = re.compile(r"^m\[(\d)\]$")
    pat_m_plain = re.compile(r"^m(\d)$")
    for i, hl in enumerate(lower):
        m = pat_bracket.match(hl) or pat_plain.match(hl) or pat_m.match(hl) or pat_m_plain.match(hl)
        if not m:
            continue
        idx = int(m.group(1))
        if 0 <= idx <= 3 and out[idx] is None:
            out[idx] = i
    return out


def _merge_motor_indices(
    primary: list[Optional[int]], fallback: list[Optional[int]]
) -> list[Optional[int]]:
    return [p if p is not None else fallback[i] for i, p in enumerate(primary)]


def _pid_triplet_indices(headers: list[str], aliases: list[list[str]]) -> list[Optional[int]]:
    return [find_index(headers, group) for group in aliases]


def _read_optional_float(row: list[str], idx: Optional[int]) -> Optional[float]:
    if idx is None or len(row) <= idx:
        return None
    try:
        raw = row[idx].strip()
        if not raw:
            return None
        return float(raw)
    except (TypeError, ValueError):
        return None


def _read_optional_int(row: list[str], idx: Optional[int]) -> Optional[int]:
    if idx is None or len(row) <= idx:
        return None
    try:
        raw = row[idx].strip()
        if not raw:
            return None
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def _normalize_erpm_to_four_motors(
    raw: Optional[float | list[Optional[float]]],
) -> list[Optional[float]]:
    """
    Canonical shape: [motor1, motor2, motor3, motor4] as floats or None.
    Single-column ERPM is broadcast to all four motors.
    """
    if raw is None:
        return [None, None, None, None]
    if isinstance(raw, (int, float)):
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return [None, None, None, None]
        return [v, v, v, v]
    if isinstance(raw, (list, tuple)):
        out: list[Optional[float]] = []
        for i in range(4):
            if i >= len(raw) or raw[i] is None:
                out.append(None)
            else:
                try:
                    out.append(float(raw[i]))
                except (TypeError, ValueError):
                    out.append(None)
        return out
    return [None, None, None, None]


def gyro_headers_are_raw_adc(headers: list[str], gx_i: int, gy_i: int, gz_i: int) -> bool:
    """
    True if the matched gyro columns are Betaflight raw gyroADC-style (LSB counts),
    not already scaled to deg/s. Uses the resolved header names at the gyro indices.
    """
    lower = _header_lower_list(headers)
    for idx in (gx_i, gy_i, gz_i):
        if idx is None or idx < 0 or idx >= len(lower):
            continue
        h = lower[idx]
        if "adc" in h:
            return True
    return False


def max_abs_gyro_triplet(
    samples: list[dict],
    *,
    max_rows: Optional[int] = None,
) -> Optional[float]:
    """
    Peak |ω| across roll/pitch/yaw for the first ``max_rows`` samples (or all if None).
    Expects gx/gy/gz in the same units (typically deg/s after analyze normalization).
    """
    if not samples:
        return None
    end = len(samples) if max_rows is None else min(len(samples), max_rows)
    peak = 0.0
    for i in range(end):
        s = samples[i]
        if not isinstance(s, dict):
            continue
        try:
            gx = abs(float(s.get("gx", 0.0)))
            gy = abs(float(s.get("gy", 0.0)))
            gz = abs(float(s.get("gz", 0.0)))
            peak = max(peak, gx, gy, gz)
        except (TypeError, ValueError):
            continue
    return peak if peak > 0.0 else None


def _find_gyro_header(lines: list[str]) -> tuple[Optional[int], list[str]]:
    header_index: Optional[int] = None
    headers: list[str] = []
    for index, line in enumerate(lines):
        if "," not in line:
            continue
        try:
            parsed = next(csv.reader([line]))
        except Exception:
            continue
        normalized = [col.strip() for col in parsed]
        joined = ",".join(col.lower() for col in normalized)
        if "gyro" in joined and len(normalized) >= 3:
            return index, normalized
    return None, []


def parse_csv_rows(
    lines: list[str],
    header_index: int,
    headers: list[str],
    flags: ParserFeatureFlags | None = None,
) -> tuple[list[dict], dict[str, float | int]]:
    flags = flags or DEFAULT_PARSER_FLAGS

    gx_i = find_index(headers, GYRO_ALIASES)
    gy_i = find_index(headers, GYRO_Y_ALIASES)
    gz_i = find_index(headers, GYRO_Z_ALIASES)
    if gx_i is None or gy_i is None or gz_i is None:
        return [], {}

    t_i = find_time_column_index(headers)
    throttle_i = find_index(headers, THROTTLE_ALIASES)
    if throttle_i is None:
        throttle_i = _fallback_throttle_index(headers)

    motor_idx = [find_index(headers, group) for group in MOTOR_ALIASES]
    motor_idx = _merge_motor_indices(motor_idx, _fallback_motor_indices(headers))

    set_roll_i = find_index(headers, SETPOINT_ROLL)
    set_pitch_i = find_index(headers, SETPOINT_PITCH)
    set_yaw_i = find_index(headers, SETPOINT_YAW)
    pid_indices = {
        "axisP": _pid_triplet_indices(headers, PID_P_ALIASES),
        "axisI": _pid_triplet_indices(headers, PID_I_ALIASES),
        "axisD": _pid_triplet_indices(headers, PID_D_ALIASES),
        "axisF": _pid_triplet_indices(headers, PID_F_ALIASES),
    }

    erpm_single_i: Optional[int] = None
    erpm_motor_idx: list[Optional[int]] = []
    debug_idx: list[Optional[int]] = []
    loop_iter_i: Optional[int] = None
    flight_mode_i: Optional[int] = None

    if flags.enable_erpm:
        erpm_single_i = find_index(headers, ERPM_SINGLE_ALIASES)
        if erpm_single_i is None:
            erpm_motor_idx = [find_index(headers, group) for group in ERPM_MOTOR_ALIASES]
    if flags.enable_debug:
        debug_idx = [find_index(headers, _debug_channel_aliases(i)) for i in range(8)]
    if flags.enable_extended_telemetry:
        loop_iter_i = find_index(headers, LOOP_ITERATION_ALIASES)
        flight_mode_i = find_index(headers, FLIGHT_MODE_FLAGS_ALIASES)

    max_idx = max(gx_i, gy_i, gz_i)
    if t_i is not None:
        max_idx = max(max_idx, t_i)
    if throttle_i is not None:
        max_idx = max(max_idx, throttle_i)
    for mi in motor_idx:
        if mi is not None:
            max_idx = max(max_idx, mi)
    for si in (set_roll_i, set_pitch_i, set_yaw_i):
        if si is not None:
            max_idx = max(max_idx, si)
    for indices in pid_indices.values():
        for pi in indices:
            if pi is not None:
                max_idx = max(max_idx, pi)

    data_lines = lines[header_index + 1 :]

    def _sample_from_line(row_number: int, line: str) -> dict | None:
        if "," not in line.strip():
            return None
        try:
            row = next(csv.reader([line]))
        except Exception:
            return None
        if len(row) <= max_idx:
            return None

        try:
            gx = float(row[gx_i])
            gy = float(row[gy_i])
            gz = float(row[gz_i])
        except (TypeError, ValueError, IndexError):
            return None

        if t_i is not None and len(row) > t_i:
            try:
                t_raw = row[t_i].strip()
                t_val = int(float(t_raw)) if t_raw else row_number
            except (TypeError, ValueError):
                t_val = row_number
        else:
            t_val = row_number

        throttle_val = None
        if throttle_i is not None and len(row) > throttle_i:
            try:
                raw_t = row[throttle_i].strip()
                if raw_t:
                    throttle_val = float(raw_t)
            except (TypeError, ValueError):
                throttle_val = None

        motors: list[float | None] = []
        for idx in motor_idx:
            if idx is None or len(row) <= idx:
                motors.append(None)
            else:
                try:
                    raw_m = row[idx].strip()
                    motors.append(float(raw_m) if raw_m else None)
                except (TypeError, ValueError):
                    motors.append(None)

        sample: dict = {
            "t": t_val,
            "gx": gx,
            "gy": gy,
            "gz": gz,
            "gyro_x": gx,
            "gyro_y": gy,
            "gyro_z": gz,
            "throttle": throttle_val,
            "motors": motors,
        }

        if set_roll_i is not None and len(row) > set_roll_i:
            try:
                sample["setpoint_roll"] = float(row[set_roll_i])
            except (TypeError, ValueError):
                pass
        if set_pitch_i is not None and len(row) > set_pitch_i:
            try:
                sample["setpoint_pitch"] = float(row[set_pitch_i])
            except (TypeError, ValueError):
                pass
        if set_yaw_i is not None and len(row) > set_yaw_i:
            try:
                sample["setpoint_yaw"] = float(row[set_yaw_i])
            except (TypeError, ValueError):
                pass

        for key, indices in pid_indices.items():
            if not any(i is not None for i in indices):
                continue
            values = [_read_optional_float(row, idx) for idx in indices]
            if any(value is not None for value in values):
                sample[key] = values

        if flags.enable_erpm:
            if erpm_single_i is not None:
                v = _read_optional_float(row, erpm_single_i)
                if v is not None:
                    sample["erpm"] = _normalize_erpm_to_four_motors(v)
            elif any(i is not None for i in erpm_motor_idx):
                erpm_vals = [_read_optional_float(row, mi) for mi in erpm_motor_idx]
                if any(v is not None for v in erpm_vals):
                    sample["erpm"] = _normalize_erpm_to_four_motors(erpm_vals)

        if flags.enable_debug and any(i is not None for i in debug_idx):
            dbg: list[Optional[float]] = []
            for di in debug_idx:
                dbg.append(_read_optional_float(row, di))
            sample["debug"] = dbg

        if flags.enable_extended_telemetry:
            li = _read_optional_int(row, loop_iter_i)
            if li is not None:
                sample["loop_iteration"] = li
            fm = _read_optional_int(row, flight_mode_i)
            if fm is not None:
                sample["flight_mode_flags"] = fm

        return sample

    samples: list[dict] = []
    meta: dict[str, float | int] = {}
    n_full = 0
    first_sample: dict | None = None
    last_sample: dict | None = None
    spilled = False

    for row_number, line in enumerate(data_lines, start=1):
        sample = _sample_from_line(row_number, line)
        if sample is None:
            continue
        n_full += 1
        if first_sample is None:
            first_sample = sample
        last_sample = sample
        if n_full <= MAX_PARSED_SAMPLES:
            samples.append(sample)
        else:
            spilled = True

    if spilled:
        target_positions = {
            1 + round(i * (n_full - 1) / (MAX_PARSED_SAMPLES - 1))
            for i in range(MAX_PARSED_SAMPLES)
        }
        samples = []
        valid_pos = 0
        for row_number, line in enumerate(data_lines, start=1):
            sample = _sample_from_line(row_number, line)
            if sample is None:
                continue
            valid_pos += 1
            if valid_pos in target_positions:
                samples.append(sample)
        if len(samples) > MAX_PARSED_SAMPLES:
            samples = samples[:MAX_PARSED_SAMPLES]
        dur_before = _duration_seconds_wall_clock(
            [s for s in (first_sample, last_sample) if isinstance(s, dict)]
        )
        dur_after = _duration_seconds_wall_clock(samples)
        meta["original_sample_count"] = n_full
        meta["duration_before_subsample_s"] = dur_before
        logger.info(
            "parse_csv_rows subsample: original_count=%s capped_count=%s "
            "duration_before_cap_s=%.4f duration_after_cap_s=%.4f",
            n_full,
            len(samples),
            dur_before,
            dur_after,
        )

    return samples, meta


def parse_csv(csv_text: str, flags: ParserFeatureFlags | None = None, *, max_text_bytes: int | None = None, max_lines: int | None = None) -> list[dict]:
    """
    Parse decoded Blackbox CSV text into sample dicts (gx, gy, gz, throttle, motors, setpoints).
    Returns [] if no valid gyro header or no rows parsed.
    Optional columns (erpm, debug, loop_iteration, flight_mode_flags) are included when
    `flags` allow and the CSV provides matching headers.
    """
    samples, _meta = parse_csv_with_meta(
        csv_text, flags, max_text_bytes=max_text_bytes, max_lines=max_lines
    )
    return samples


def parse_csv_with_meta(
    csv_text: str,
    flags: ParserFeatureFlags | None = None,
    *,
    max_text_bytes: int | None = None,
    max_lines: int | None = None,
) -> tuple[list[dict], dict[str, float | int]]:
    """Like :func:`parse_csv`, plus parse metadata (``original_sample_count`` when capped)."""
    text_limit = max_decoded_csv_text_bytes() if max_text_bytes is None else max_text_bytes
    line_limit = max_decoded_csv_lines() if max_lines is None else max_lines
    if text_limit > 0 and len(csv_text.encode("utf-8", errors="ignore")) > text_limit:
        logger.warning("parse_csv rejected oversized decoded CSV text")
        return [], {}
    if line_limit > 0 and csv_text.count("\n") + 1 > line_limit:
        logger.warning("parse_csv rejected decoded CSV with too many lines")
        return [], {}
    lines = [line for line in csv_text.splitlines() if line.strip()]
    header_index, headers = _find_gyro_header(lines)
    if header_index is None or not headers:
        return [], {}
    return parse_csv_rows(lines, header_index, headers, flags=flags)


def parse_blackbox_csv(
    text: str,
    flags: ParserFeatureFlags | None = None,
    log_index: int | None = None,
    *,
    max_text_bytes: int | None = None,
    max_lines: int | None = None,
) -> dict:
    """
    Parse Betaflight blackbox_decode CSV: locate gyro header row, extract gyro,
    time, throttle, motors, setpoints.
    Optional telemetry is controlled by `flags` (defaults to DEFAULT_PARSER_FLAGS).

    ``log_index`` is retained for API compatibility with donor callers (pre-cap
    spectral extraction is deferred past WU3).
    """
    _ = log_index  # reserved for future dense-window identity (analysis WU)
    text_limit = max_decoded_csv_text_bytes() if max_text_bytes is None else max_text_bytes
    line_limit = max_decoded_csv_lines() if max_lines is None else max_lines
    if text_limit > 0 and len(text.encode("utf-8", errors="ignore")) > text_limit:
        return {"parse_failed": True, "message": "decoded_csv_too_large"}
    if line_limit > 0 and text.count("\n") + 1 > line_limit:
        return {"parse_failed": True, "message": "decoded_csv_too_many_lines"}
    lines = [line for line in text.splitlines() if line.strip()]
    header_index, headers = _find_gyro_header(lines)
    if header_index is None or not headers:
        return {"parse_failed": True, "message": "no_valid_gyro_header"}

    gx_i = find_index(headers, GYRO_ALIASES)
    gy_i = find_index(headers, GYRO_Y_ALIASES)
    gz_i = find_index(headers, GYRO_Z_ALIASES)
    gyro_source_is_raw_adc = False
    if gx_i is not None and gy_i is not None and gz_i is not None:
        gyro_source_is_raw_adc = gyro_headers_are_raw_adc(headers, gx_i, gy_i, gz_i)

    samples, subsample_meta = parse_csv_rows(lines, header_index, headers, flags=flags)
    if not samples:
        return {
            "parse_failed": True,
            "message": "no_valid_samples",
            "available_headers": headers[:40],
        }

    out: dict = {
        "samples": samples,
        "count": len(samples),
        "gyro_source_is_raw_adc": gyro_source_is_raw_adc,
        "gyro_header_x": headers[gx_i] if gx_i is not None else None,
        "gyro_header_y": headers[gy_i] if gy_i is not None else None,
        "gyro_header_z": headers[gz_i] if gz_i is not None else None,
    }
    if subsample_meta:
        out.update(subsample_meta)

    return out


def log_parser_probe_after_normalize(
    samples: list[dict],
    *,
    pre_normalize_peak: float | None = None,
    applied_scale: float | None = None,
    second_pass_correction: bool = False,
    gyro_source_is_raw_adc: bool | None = None,
) -> None:
    """
    Debug / validation after gyro normalization.

    Interprets gx/gy/gz as **deg/s** (Betaflight blackbox convention for scaled gyro columns).
    Thresholds are wide enough for calm hover through aggressive acro; they flag dead sensors,
    wrong units, or failed ADC→deg/s scaling — not normal low-rate flight.
    """
    if not samples:
        logger.warning("parser probe: no samples after normalize")
        return

    first = samples[0]
    peak_axes = max_abs_gyro_triplet(samples, max_rows=None)

    th_ok = first.get("throttle") is not None
    motors = first.get("motors")
    m_ok = (
        isinstance(motors, list)
        and len(motors) >= 4
        and all(isinstance(x, (int, float)) for x in motors[:4])
    )

    # Realistic deg/s: bench noise ~0–2; hover/cruise often tens–low hundreds; flips/spikes can exceed 2000 briefly.
    _MIN_SANE_DEG_S = 8.0
    _MAX_SANE_DEG_S = 8000.0

    issues: list[str] = []
    if not th_ok:
        issues.append("throttle=None")
    if not m_ok:
        issues.append("motors not 4 numeric")
    if peak_axes is not None:
        if peak_axes > _MAX_SANE_DEG_S:
            issues.append(
                f"peak |gyro| {peak_axes:.1f} deg/s > {_MAX_SANE_DEG_S:.0f} (units/scaling glitch?)"
            )
        elif peak_axes < _MIN_SANE_DEG_S:
            issues.append(
                f"peak |gyro| {peak_axes:.3f} deg/s < {_MIN_SANE_DEG_S:.0f} (static log or over-scaled?)"
            )

    logger.info(
        "gyro probe: count=%d pre_peak_raw=%s post_peak_deg_s=%s scale=%s second_pass=%s "
        "adc_header_hint=%s throttle_ok=%s motors_ok=%s",
        len(samples),
        pre_normalize_peak,
        peak_axes,
        applied_scale,
        second_pass_correction,
        gyro_source_is_raw_adc,
        th_ok,
        m_ok,
    )
    if issues:
        logger.warning("parser validation issues: %s", "; ".join(issues))


__all__ = [
    "DEFAULT_PARSER_FLAGS",
    "MAX_PARSED_SAMPLES",
    "ParserFeatureFlags",
    "default_parser_flags",
    "parser_feature_flags_metadata",
    "evenly_subsample_parsed_samples",
    "find_index",
    "gyro_headers_are_raw_adc",
    "log_parser_probe_after_normalize",
    "max_abs_gyro_triplet",
    "parse_blackbox_csv",
    "parse_csv",
    "parse_csv_with_meta",
    "parse_csv_rows",
]
