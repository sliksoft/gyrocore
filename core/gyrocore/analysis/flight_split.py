# GyroCore WU4: adapted from AeroTuner backend/analysis/flight_split.py
"""
Detect multiple flights in one blackbox export (concatenated sessions).

Blackbox ``t`` is time in microseconds. Flights are separated by:

- Time moving backward (logger reset / appended session) beyond a small glitch threshold.
- Large forward gaps (concatenated logs with monotonic or near-monotonic time).
- Long stretches of near-zero throttle and gyro (disarmed / on bench).
- Long stretches of near-zero motor commands (disarm), when motor columns exist.

Rows without a valid integer ``t`` stay in the current chunk (legacy behavior).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Backward jump larger than this (µs) is treated as a new flight, not a glitch.
TIME_RESET_THRESHOLD_US = 100_000  # 0.1 seconds

# Concatenated sessions may continue increasing ``t``; treat large forward steps as breaks.
FORWARD_GAP_THRESHOLD_US = 500_000  # 500 ms

# Inactivity: low gyro + low throttle for at least this wall duration → new flight.
INACTIVITY_DURATION_US = 1_500_000  # 1.5 s (within requested 1–2 s)

# Motors near zero for at least this duration → new flight (disarm gap).
MOTOR_ZERO_DURATION_US = 1_000_000  # 1.0 s

# "Inactive" sample: gyro magnitude and throttle both low (when throttle is present).
GYRO_INACTIVE_DEG_S = 20.0
# If throttle is missing, require quieter gyro so we do not split on hover without RC columns.
GYRO_INACTIVE_NO_THROTTLE_DEG_S = 8.0
THROTTLE_INACTIVE_MAX = 0.12  # normalized 0..1; RC 1000–2000 mapped below

# Motor outputs treated as "off" (µs-style PWM near 0, or small floats).
MOTOR_ZERO_ABS_MAX = 150.0


def _throttle_normalized(s: dict) -> float | None:
    raw = s.get("throttle")
    if raw is None:
        return None
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v > 1.5:
        return max(0.0, min(1.0, (v - 1000.0) / 1000.0))
    return max(0.0, min(1.0, v))


def _gyro_max_abs(s: dict) -> float | None:
    try:
        gx = float(s.get("gx", 0.0))
        gy = float(s.get("gy", 0.0))
        gz = float(s.get("gz", 0.0))
    except (TypeError, ValueError):
        return None
    return max(abs(gx), abs(gy), abs(gz))


def _sample_inactive(s: dict) -> bool:
    """Near-zero stick + gyro — typical disarmed / static log gap."""
    gmax = _gyro_max_abs(s)
    if gmax is None:
        return False
    th = _throttle_normalized(s)
    if th is None:
        return gmax < GYRO_INACTIVE_NO_THROTTLE_DEG_S
    return gmax < GYRO_INACTIVE_DEG_S and th < THROTTLE_INACTIVE_MAX


def _motors_effectively_zero(s: dict) -> bool:
    m = s.get("motors")
    if not isinstance(m, (list, tuple)) or len(m) < 4:
        return False
    try:
        vals = [float(x) for x in m[:4]]
    except (TypeError, ValueError):
        return False
    return all(abs(v) <= MOTOR_ZERO_ABS_MAX for v in vals)


def _trim_trailing_inactive(chunk: list[dict]) -> None:
    while chunk:
        last = chunk[-1]
        if not isinstance(last, dict):
            break
        if not _sample_inactive(last):
            break
        chunk.pop()


def _trim_trailing_motor_zero(chunk: list[dict]) -> None:
    while chunk:
        last = chunk[-1]
        if not isinstance(last, dict):
            break
        if not _motors_effectively_zero(last):
            break
        chunk.pop()


def split_samples_into_flights(samples: list[dict]) -> list[list[dict]]:
    """
    Partition normalized samples into flights.

    A new flight starts when:

    - Time moves backward by more than ``TIME_RESET_THRESHOLD_US``, or
    - Time jumps forward by more than ``FORWARD_GAP_THRESHOLD_US``, or
    - Low throttle + low gyro persist for ``INACTIVITY_DURATION_US``, or
    - Motor commands stay near zero for ``MOTOR_ZERO_DURATION_US`` (if motors exist).

    Returns a non-empty list of chunks; each chunk is a shallow list of references to
    the original row dicts.
    """
    if not samples:
        return []

    flights: list[list[dict]] = []
    chunk: list[dict] = []
    prev_t: int | None = None
    idle_run_start_t: int | None = None
    motor_zero_run_start_t: int | None = None
    skip_idle = False
    skip_motor_zero = False

    def _emit_and_reset(reason: str, index: int, new_chunk_first: dict, new_t: int) -> None:
        nonlocal chunk, prev_t, idle_run_start_t, motor_zero_run_start_t, skip_idle, skip_motor_zero
        logger.info(
            "[flight_split] new flight reason=%s at index=%d",
            reason,
            index,
        )
        if chunk:
            flights.append(chunk)
        chunk = [new_chunk_first]
        prev_t = new_t
        idle_run_start_t = None
        motor_zero_run_start_t = None
        skip_idle = False
        skip_motor_zero = False

    for i, s in enumerate(samples):
        if not isinstance(s, dict):
            chunk.append(s)
            continue

        try:
            t = int(s["t"])
        except (KeyError, TypeError, ValueError):
            chunk.append(s)
            continue

        if skip_idle:
            if _sample_inactive(s):
                continue
            skip_idle = False
            idle_run_start_t = None

        if skip_motor_zero:
            if _motors_effectively_zero(s):
                continue
            skip_motor_zero = False
            motor_zero_run_start_t = None

        if prev_t is not None:
            backward = prev_t - t
            if backward > TIME_RESET_THRESHOLD_US:
                _emit_and_reset("time_backward", i, s, t)
                continue
            forward = t - prev_t
            if forward > FORWARD_GAP_THRESHOLD_US:
                _emit_and_reset("forward_time_gap", i, s, t)
                continue

        # Long inactivity → end previous flight; skip idle samples until active again.
        if _sample_inactive(s):
            if idle_run_start_t is None:
                idle_run_start_t = t
            elif (t - idle_run_start_t) >= INACTIVITY_DURATION_US:
                _trim_trailing_inactive(chunk)
                if chunk:
                    logger.info(
                        "[flight_split] closed flight reason=%s at index=%d samples=%d",
                        "inactivity_gap",
                        i,
                        len(chunk),
                    )
                    flights.append(chunk)
                else:
                    logger.debug(
                        "[flight_split] inactivity_gap at index=%d with no prior segment",
                        i,
                    )
                chunk = []
                prev_t = None
                idle_run_start_t = None
                motor_zero_run_start_t = None
                skip_idle = True
                continue
        else:
            idle_run_start_t = None

        # Long motor-off → disarm gap between flights (only when motor columns exist).
        if _motors_effectively_zero(s):
            if motor_zero_run_start_t is None:
                motor_zero_run_start_t = t
            elif (t - motor_zero_run_start_t) >= MOTOR_ZERO_DURATION_US:
                _trim_trailing_motor_zero(chunk)
                if chunk:
                    logger.info(
                        "[flight_split] closed flight reason=%s at index=%d samples=%d",
                        "motor_zero_gap",
                        i,
                        len(chunk),
                    )
                    flights.append(chunk)
                else:
                    logger.debug(
                        "[flight_split] motor_zero_gap at index=%d with no prior segment",
                        i,
                    )
                chunk = []
                prev_t = None
                idle_run_start_t = None
                motor_zero_run_start_t = None
                skip_motor_zero = True
                continue
        else:
            motor_zero_run_start_t = None

        chunk.append(s)
        prev_t = t

    if chunk:
        flights.append(chunk)

    return flights if flights else [list(samples)]
