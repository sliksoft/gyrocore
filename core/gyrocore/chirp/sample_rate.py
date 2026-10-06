"""
CHIRP / Blackbox sample-rate resolution (WU6).

Betaflight interpretation (evidence from vendored sources, not Autotune's
num-blind formula):

  gyro_rate_hz = 1e6 / looptime_us
  pid_loop_rate_hz = gyro_rate_hz / pid_process_denom
  header_logged_rate_hz =
      pid_loop_rate_hz * (frameIntervalPNum / frameIntervalPDenom)

Equivalent closed form (matches ``FlightLog.getBlackboxRate`` and
``GraphSpectrumCalc.initialize``)::

  1e6 * frameIntervalPNum
  / (looptime_us * pid_process_denom * frameIntervalPDenom)

Frame selection predicate (blackbox-tools ``shouldHaveFrame`` /
viewer ``flightlog_parser``)::

  (frameIndex % I + PNum - 1) % PDenom < PNum

so the long-run logged fraction of PID iterations is ``PNum / PDenom``.
Firmware often prints a bare divider (``H P interval:2`` → num=1, denom=2).

Autotune ``useAutotune.computeSampleRate`` ignores ``frameIntervalPNum``;
that upstream weakness is mirrored only by
``upstream_autotune_compute_sample_rate_hz`` for WU5 parity. GyroCore
resolution uses the Viewer / tools formula above.

Mismatch tolerance matches Blackbox Viewer ``WARNING_RATE_DIFFERENCE`` (5%).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

import numpy as np

# Blackbox Viewer flightlog.js / graph_spectrum_calc.js
MISMATCH_TOLERANCE_FRACTION = 0.05

# Minimum positive samples needed for a timestamp median estimate
_MIN_TIMESTAMP_DELTAS = 8


class SampleRateSource(str, Enum):
    """Where ``effective_rate_hz`` came from."""

    HEADER = "header"
    TIMESTAMP = "timestamp"
    HEADER_CONFIRMED = "header_confirmed"  # header used; timestamps agree
    UNKNOWN = "unknown"


class SampleRateStatus(str, Enum):
    OK = "ok"
    MISMATCH = "mismatch"
    HEADER_ONLY = "header_only"
    TIMESTAMP_ONLY = "timestamp_only"
    UNUSABLE = "unusable"


@dataclass(frozen=True)
class SampleRateEvidence:
    """Structured sample-rate resolution result for CHIRP / system-ID."""

    pid_loop_rate_hz: float | None
    blackbox_configured_rate_hz: float | None
    header_rate_hz: float | None
    timestamp_rate_hz: float | None
    effective_rate_hz: float | None
    source: SampleRateSource
    status: SampleRateStatus
    difference_percent: float | None
    confidence: float
    warnings: tuple[str, ...] = field(default_factory=tuple)
    frame_interval_p_num: int | None = None
    frame_interval_p_denom: int | None = None
    looptime_us: float | None = None
    pid_process_denom: float | None = None
    usable: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["source"] = self.source.value
        d["status"] = self.status.value
        d["warnings"] = list(self.warnings)
        return d


# ---------------------------------------------------------------------------
# WU5 upstream Autotune mirror (denom-only; intentional historical parity)
# ---------------------------------------------------------------------------


def upstream_autotune_compute_sample_rate_hz(
    looptime_us: float | int | None = None,
    pid_process_denom: float | int | None = None,
    frame_interval_p_denom: float | int | None = None,
) -> float:
    """
    Exact mirror of Configurator ``useAutotune.computeSampleRate``.

    Ignores ``frameIntervalPNum``. Kept for upstream-parity vectors only.
    """
    looptime_us_v = float(looptime_us or 125)
    pid_denom_v = float(pid_process_denom or 1)
    bb_rate_v = float(frame_interval_p_denom or 1)
    return 1_000_000.0 / (looptime_us_v * pid_denom_v * bb_rate_v)


# Back-compat aliases used by WU5 tests / desktop re-export
def compute_sample_rate_hz(
    looptime_us: float | int | None = None,
    pid_process_denom: float | int | None = None,
    frame_interval_p_denom: float | int | None = None,
) -> float:
    return upstream_autotune_compute_sample_rate_hz(
        looptime_us, pid_process_denom, frame_interval_p_denom
    )


def compute_sample_rate_from_sysconfig(sys_config: Mapping[str, object]) -> float:
    return upstream_autotune_compute_sample_rate_hz(
        looptime_us=_as_number(sys_config.get("looptime")),
        pid_process_denom=_as_number(sys_config.get("pid_process_denom")),
        frame_interval_p_denom=_as_number(sys_config.get("frameIntervalPDenom")),
    )


def pid_loop_frequency_hz(
    looptime_us: float | int | None = None,
    pid_process_denom: float | int | None = None,
) -> float:
    """PID loop frequency from header fields (no blackbox P interval)."""
    looptime_us_v = float(looptime_us or 125)
    pid_denom_v = float(pid_process_denom or 1)
    return 1_000_000.0 / (looptime_us_v * pid_denom_v)


# ---------------------------------------------------------------------------
# GyroCore-correct header rate (Viewer / blackbox-tools semantics)
# ---------------------------------------------------------------------------


def header_logged_rate_hz(
    looptime_us: float | int,
    pid_process_denom: float | int,
    frame_interval_p_num: float | int,
    frame_interval_p_denom: float | int,
) -> float:
    """
    Logged Blackbox rate using num/denom.

    ``1e6 * PNum / (looptime * pid_process_denom * PDenom)``
    """
    lt = float(looptime_us)
    pd = float(pid_process_denom)
    num = float(frame_interval_p_num)
    den = float(frame_interval_p_denom)
    if lt <= 0 or pd <= 0 or num <= 0 or den <= 0:
        raise ValueError("looptime, pid_process_denom, PNum, and PDenom must be > 0")
    return 1_000_000.0 * num / (lt * pd * den)


def try_header_logged_rate_hz(
    looptime_us: float | int | None,
    pid_process_denom: float | int | None,
    frame_interval_p_num: float | int | None,
    frame_interval_p_denom: float | int | None,
) -> float | None:
    """Return header logged rate or None if metadata is incomplete/invalid."""
    if (
        looptime_us is None
        or pid_process_denom is None
        or frame_interval_p_num is None
        or frame_interval_p_denom is None
    ):
        return None
    try:
        lt = float(looptime_us)
        pd = float(pid_process_denom)
        num = float(frame_interval_p_num)
        den = float(frame_interval_p_denom)
    except (TypeError, ValueError):
        return None
    if not all(np.isfinite(v) and v > 0 for v in (lt, pd, num, den)):
        return None
    # Integer-ish sanity: denom must be >= num for a meaningful fraction ≤ 1
    # (firmware can still emit odd values; we still compute but callers warn).
    return 1_000_000.0 * num / (lt * pd * den)


def try_pid_loop_rate_hz(
    looptime_us: float | int | None,
    pid_process_denom: float | int | None,
) -> float | None:
    if looptime_us is None or pid_process_denom is None:
        return None
    try:
        lt = float(looptime_us)
        pd = float(pid_process_denom)
    except (TypeError, ValueError):
        return None
    if not (np.isfinite(lt) and np.isfinite(pd) and lt > 0 and pd > 0):
        return None
    return 1_000_000.0 / (lt * pd)


# ---------------------------------------------------------------------------
# Timestamp-observed rate
# ---------------------------------------------------------------------------


def estimate_timestamp_rate_hz(
    timestamps_us: Sequence[float] | np.ndarray,
    *,
    min_deltas: int = _MIN_TIMESTAMP_DELTAS,
) -> float | None:
    """
    Robust estimate of sample rate from Blackbox ``time`` field (microseconds).

    Uses the median of positive finite dt values. Zero/negative deltas are
    rejected. Large gaps remain in the pool so a few dropouts do not dominate
    (median), but extreme sparsity still yields a lower rate — callers compare
    against the header.
    """
    arr = np.asarray(timestamps_us, dtype=float)
    if arr.size < 2:
        return None
    dts = np.diff(arr)
    valid = dts[np.isfinite(dts) & (dts > 0.0)]
    if valid.size < min_deltas:
        # Allow slightly smaller windows for short chirp segments in tests
        if valid.size < 3:
            return None
    median_dt = float(np.median(valid))
    if not np.isfinite(median_dt) or median_dt <= 0.0:
        return None
    rate = 1_000_000.0 / median_dt
    if not np.isfinite(rate) or rate <= 0.0:
        return None
    return rate


def _difference_percent(a: float, b: float) -> float:
    """Relative difference as percent of ``b`` (timestamp / reference)."""
    if b == 0.0:
        return float("inf")
    return abs(a - b) / abs(b) * 100.0


# ---------------------------------------------------------------------------
# Resolution policy
# ---------------------------------------------------------------------------


def resolve_chirp_sample_rate(
    *,
    looptime_us: float | int | None = None,
    pid_process_denom: float | int | None = None,
    frame_interval_p_num: float | int | None = None,
    frame_interval_p_denom: float | int | None = None,
    timestamps_us: Sequence[float] | np.ndarray | None = None,
    mismatch_tolerance_fraction: float = MISMATCH_TOLERANCE_FRACTION,
) -> SampleRateEvidence:
    """
    Resolve the effective CHIRP analysis sample rate.

    Policy (deterministic):

    A. Header valid + timestamp agrees (within tolerance of header):
       use header rate; source=header_confirmed; status=ok

    B. Header valid + timestamps disagree:
       flag mismatch; use **timestamp** rate (spectral axis must match the
       actual spacing of the samples being transformed); status=mismatch

    C. Incomplete/invalid header + valid timestamps:
       use timestamp rate; status=timestamp_only

    D. Neither trustworthy:
       effective_rate_hz=None; status=unusable; usable=False
       (does **not** silently assume full PID / full-rate logging)

    Tolerance default 5% relative to the timestamp rate, matching Viewer
    ``WARNING_RATE_DIFFERENCE``.
    """
    warnings: list[str] = []

    pid_rate = try_pid_loop_rate_hz(looptime_us, pid_process_denom)
    header_rate = try_header_logged_rate_hz(
        looptime_us,
        pid_process_denom,
        frame_interval_p_num,
        frame_interval_p_denom,
    )
    # blackbox_configured_rate is the same quantity as header_rate when P
    # interval metadata is present; exposed separately for clarity in reports.
    blackbox_configured = header_rate

    if header_rate is not None and frame_interval_p_num is not None and frame_interval_p_denom is not None:
        try:
            num_f = float(frame_interval_p_num)
            den_f = float(frame_interval_p_denom)
            if num_f > den_f:
                warnings.append("frame_interval_p_num_exceeds_denom")
        except (TypeError, ValueError):
            pass

    ts_rate: float | None = None
    if timestamps_us is not None:
        ts_rate = estimate_timestamp_rate_hz(timestamps_us)
        if ts_rate is None and len(list(timestamps_us)) >= 2:
            warnings.append("timestamp_rate_unreliable")

    # Explicit: missing P interval must not inherit Autotune's silent full-rate
    if frame_interval_p_num is None or frame_interval_p_denom is None:
        if looptime_us is not None and pid_process_denom is not None:
            warnings.append("p_interval_metadata_missing")
    if looptime_us is None:
        warnings.append("looptime_missing")
    if pid_process_denom is None:
        warnings.append("pid_process_denom_missing")

    # --- D: nothing usable ---
    if header_rate is None and ts_rate is None:
        return SampleRateEvidence(
            pid_loop_rate_hz=pid_rate,
            blackbox_configured_rate_hz=blackbox_configured,
            header_rate_hz=header_rate,
            timestamp_rate_hz=ts_rate,
            effective_rate_hz=None,
            source=SampleRateSource.UNKNOWN,
            status=SampleRateStatus.UNUSABLE,
            difference_percent=None,
            confidence=0.0,
            warnings=tuple(warnings + ["no_trustworthy_sample_rate"]),
            frame_interval_p_num=_as_int(frame_interval_p_num),
            frame_interval_p_denom=_as_int(frame_interval_p_denom),
            looptime_us=_as_number(looptime_us),
            pid_process_denom=_as_number(pid_process_denom),
            usable=False,
        )

    # --- C: timestamps only ---
    if header_rate is None and ts_rate is not None:
        return SampleRateEvidence(
            pid_loop_rate_hz=pid_rate,
            blackbox_configured_rate_hz=None,
            header_rate_hz=None,
            timestamp_rate_hz=ts_rate,
            effective_rate_hz=ts_rate,
            source=SampleRateSource.TIMESTAMP,
            status=SampleRateStatus.TIMESTAMP_ONLY,
            difference_percent=None,
            confidence=0.7,
            warnings=tuple(warnings + ["derived_from_timestamps_only"]),
            frame_interval_p_num=_as_int(frame_interval_p_num),
            frame_interval_p_denom=_as_int(frame_interval_p_denom),
            looptime_us=_as_number(looptime_us),
            pid_process_denom=_as_number(pid_process_denom),
            usable=True,
        )

    assert header_rate is not None

    # --- Header only (no / bad timestamps) ---
    if ts_rate is None:
        return SampleRateEvidence(
            pid_loop_rate_hz=pid_rate,
            blackbox_configured_rate_hz=blackbox_configured,
            header_rate_hz=header_rate,
            timestamp_rate_hz=None,
            effective_rate_hz=header_rate,
            source=SampleRateSource.HEADER,
            status=SampleRateStatus.HEADER_ONLY,
            difference_percent=None,
            confidence=0.75,
            warnings=tuple(warnings + ["no_timestamp_crosscheck"]),
            frame_interval_p_num=_as_int(frame_interval_p_num),
            frame_interval_p_denom=_as_int(frame_interval_p_denom),
            looptime_us=_as_number(looptime_us),
            pid_process_denom=_as_number(pid_process_denom),
            usable=True,
        )

    # --- A / B: both present ---
    rel = abs(header_rate - ts_rate) / ts_rate
    diff_pct = _difference_percent(header_rate, ts_rate)

    if rel <= mismatch_tolerance_fraction:
        return SampleRateEvidence(
            pid_loop_rate_hz=pid_rate,
            blackbox_configured_rate_hz=blackbox_configured,
            header_rate_hz=header_rate,
            timestamp_rate_hz=ts_rate,
            effective_rate_hz=header_rate,
            source=SampleRateSource.HEADER_CONFIRMED,
            status=SampleRateStatus.OK,
            difference_percent=diff_pct,
            confidence=0.95,
            warnings=tuple(warnings),
            frame_interval_p_num=_as_int(frame_interval_p_num),
            frame_interval_p_denom=_as_int(frame_interval_p_denom),
            looptime_us=_as_number(looptime_us),
            pid_process_denom=_as_number(pid_process_denom),
            usable=True,
        )

    # B: mismatch — prefer timestamp for spectral analysis of logged samples
    warnings.append("header_timestamp_rate_mismatch")
    warnings.append("effective_rate_from_timestamps_due_to_mismatch")
    return SampleRateEvidence(
        pid_loop_rate_hz=pid_rate,
        blackbox_configured_rate_hz=blackbox_configured,
        header_rate_hz=header_rate,
        timestamp_rate_hz=ts_rate,
        effective_rate_hz=ts_rate,
        source=SampleRateSource.TIMESTAMP,
        status=SampleRateStatus.MISMATCH,
        difference_percent=diff_pct,
        confidence=0.6,
        warnings=tuple(warnings),
        frame_interval_p_num=_as_int(frame_interval_p_num),
        frame_interval_p_denom=_as_int(frame_interval_p_denom),
        looptime_us=_as_number(looptime_us),
        pid_process_denom=_as_number(pid_process_denom),
        usable=True,
    )


def resolve_from_sysconfig(
    sys_config: Mapping[str, object],
    timestamps_us: Sequence[float] | np.ndarray | None = None,
    *,
    mismatch_tolerance_fraction: float = MISMATCH_TOLERANCE_FRACTION,
) -> SampleRateEvidence:
    """Resolve using chirp-parser / viewer sysConfig key names."""
    return resolve_chirp_sample_rate(
        looptime_us=_as_number(sys_config.get("looptime")),
        pid_process_denom=_as_number(sys_config.get("pid_process_denom")),
        frame_interval_p_num=_as_number(sys_config.get("frameIntervalPNum")),
        frame_interval_p_denom=_as_number(sys_config.get("frameIntervalPDenom")),
        timestamps_us=timestamps_us,
        mismatch_tolerance_fraction=mismatch_tolerance_fraction,
    )


def _as_number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_int(value: object) -> int | None:
    n = _as_number(value)
    if n is None:
        return None
    return int(n)


__all__ = [
    "MISMATCH_TOLERANCE_FRACTION",
    "SampleRateSource",
    "SampleRateStatus",
    "SampleRateEvidence",
    "upstream_autotune_compute_sample_rate_hz",
    "compute_sample_rate_hz",
    "compute_sample_rate_from_sysconfig",
    "pid_loop_frequency_hz",
    "header_logged_rate_hz",
    "try_header_logged_rate_hz",
    "try_pid_loop_rate_hz",
    "estimate_timestamp_rate_hz",
    "resolve_chirp_sample_rate",
    "resolve_from_sysconfig",
]
