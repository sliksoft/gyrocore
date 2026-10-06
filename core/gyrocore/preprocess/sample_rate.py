"""Sample-rate helpers for analysis (WU4)."""

from __future__ import annotations

from typing import Any, Sequence

from gyrocore.analysis.signal import compute_sample_rate, time_us_to_seconds


def infer_sample_rate_hz(samples: Sequence[dict[str, Any]]) -> float:
    """Infer Hz from sample ``t`` timestamps (microseconds)."""
    times: list[float] = []
    for row in samples:
        if not isinstance(row, dict):
            continue
        try:
            times.append(float(row["t"]))
        except (KeyError, TypeError, ValueError):
            continue
    if len(times) < 2:
        return 0.0
    seconds = time_us_to_seconds(times)
    return float(compute_sample_rate(seconds))
