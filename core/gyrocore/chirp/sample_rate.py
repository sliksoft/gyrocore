"""
Upstream CHIRP sample-rate formula mirror (WU5).

Faithful re-expression of Betaflight Configurator
``useAutotune.computeSampleRate`` for documentation and regression tests.

Source of truth (TypeScript)::

    third_party/betaflight/configurator/src/composables/useAutotune.ts
    function computeSampleRate(sysConfig)

This module does **not** improve or correct upstream behavior. See
``docs/upstream/CHIRP_SAMPLE_RATE.md``.
"""

from __future__ import annotations

from typing import Mapping


def compute_sample_rate_hz(
    looptime_us: float | int | None = None,
    pid_process_denom: float | int | None = None,
    frame_interval_p_denom: float | int | None = None,
) -> float:
    """
    Mirror of upstream ``computeSampleRate``.

    sampleRate = 1e6 / (looptimeUs * pidDenom * bbRate)

    where missing/zero-ish inputs follow upstream ``||`` defaults:
    looptimeUs=125, pidDenom=1, bbRate=1.
    """
    looptime_us_v = float(looptime_us or 125)
    pid_denom_v = float(pid_process_denom or 1)
    bb_rate_v = float(frame_interval_p_denom or 1)
    return 1_000_000.0 / (looptime_us_v * pid_denom_v * bb_rate_v)


def compute_sample_rate_from_sysconfig(sys_config: Mapping[str, object]) -> float:
    """Same formula, reading header-like keys used by the chirp parser."""
    return compute_sample_rate_hz(
        looptime_us=_as_number(sys_config.get("looptime")),
        pid_process_denom=_as_number(sys_config.get("pid_process_denom")),
        frame_interval_p_denom=_as_number(sys_config.get("frameIntervalPDenom")),
    )


def pid_loop_frequency_hz(
    looptime_us: float | int | None = None,
    pid_process_denom: float | int | None = None,
) -> float:
    """PID loop frequency implied by the same header fields (no blackbox denom)."""
    looptime_us_v = float(looptime_us or 125)
    pid_denom_v = float(pid_process_denom or 1)
    return 1_000_000.0 / (looptime_us_v * pid_denom_v)


def _as_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    return float(value)  # type: ignore[arg-type]


__all__ = [
    "compute_sample_rate_hz",
    "compute_sample_rate_from_sysconfig",
    "pid_loop_frequency_hz",
]
