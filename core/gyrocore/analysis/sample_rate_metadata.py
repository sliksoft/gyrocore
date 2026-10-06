# GyroCore WU4: adapted from AeroTuner backend/analysis/sample_rate_metadata.py
"""Sample-rate metadata and spectral assessability helpers."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


SPECTRAL_SOURCE_RAW_FULL_RATE = "raw_full_rate"
SPECTRAL_SOURCE_HIGH_RATE_SLICE = "high_rate_slice"
SPECTRAL_SOURCE_CAPPED_20K = "capped_20k"
SPECTRAL_SOURCE_DOWNSAMPLED = "downsampled"
SPECTRAL_SOURCE_UNKNOWN = "unknown"

_VALID_SOURCE_KINDS = {
    SPECTRAL_SOURCE_RAW_FULL_RATE,
    SPECTRAL_SOURCE_HIGH_RATE_SLICE,
    SPECTRAL_SOURCE_CAPPED_20K,
    SPECTRAL_SOURCE_DOWNSAMPLED,
    SPECTRAL_SOURCE_UNKNOWN,
}


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        out = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return out if out > 0 else None


def duration_seconds_from_samples(samples: Sequence[Mapping[str, Any]] | None) -> float | None:
    rows = [row for row in (samples or []) if isinstance(row, Mapping)]
    if len(rows) < 2:
        return None
    t0 = _finite_float(rows[0].get("t"))
    t1 = _finite_float(rows[-1].get("t"))
    if t0 is None or t1 is None or t1 <= t0:
        return None
    return float(t1 - t0) / 1_000_000.0


def effective_sample_rate_hz(
    samples: Sequence[Mapping[str, Any]] | None,
    *,
    duration_s: Any = None,
    sample_count: Any = None,
) -> float | None:
    count = _positive_int(sample_count) or len(samples or [])
    if count < 2:
        return None
    duration = _finite_float(duration_s)
    if duration is None or duration <= 0:
        duration = duration_seconds_from_samples(samples)
    if duration is None or duration <= 0:
        return None
    return float(count - 1) / float(duration)


def infer_source_kind(
    *,
    raw_sample_count: Any = None,
    display_sample_count: Any = None,
    spectral_sample_count: Any = None,
    source_kind: Any = None,
) -> str:
    raw = _positive_int(raw_sample_count)
    display = _positive_int(display_sample_count)
    spectral = _positive_int(spectral_sample_count)
    if isinstance(source_kind, str) and source_kind in _VALID_SOURCE_KINDS:
        return source_kind
    if raw is not None and spectral is not None:
        if spectral >= raw:
            return SPECTRAL_SOURCE_RAW_FULL_RATE
        if display is not None and spectral == display and spectral <= 20_000 and raw > spectral:
            return SPECTRAL_SOURCE_CAPPED_20K
        if raw > spectral:
            return SPECTRAL_SOURCE_HIGH_RATE_SLICE
    return SPECTRAL_SOURCE_UNKNOWN


def build_sample_rate_metadata(
    samples: Sequence[Mapping[str, Any]] | None,
    *,
    raw_sample_count: Any = None,
    analyzed_sample_count: Any = None,
    display_sample_count: Any = None,
    spectral_sample_count: Any = None,
    duration_s: Any = None,
    source_kind: Any = None,
    decimation_factor: Any = None,
    spectral_assessable: bool | None = None,
    spectral_limit_reasons: Sequence[str] | None = None,
) -> dict[str, Any]:
    rows = [row for row in (samples or []) if isinstance(row, Mapping)]
    spectral_count = _positive_int(spectral_sample_count) or len(rows)
    duration = _finite_float(duration_s)
    if duration is None or duration <= 0:
        duration = duration_seconds_from_samples(rows)
    fs = effective_sample_rate_hz(rows, duration_s=duration, sample_count=spectral_count)
    nyquist = (fs / 2.0) if fs is not None and fs > 0 else None

    raw_count = _positive_int(raw_sample_count)
    display_count = _positive_int(display_sample_count)
    analyzed_count = _positive_int(analyzed_sample_count)
    decimation = _finite_float(decimation_factor)
    if decimation is None and raw_count is not None and spectral_count > 0 and raw_count > spectral_count:
        decimation = float(raw_count) / float(spectral_count)

    kind = infer_source_kind(
        raw_sample_count=raw_count,
        display_sample_count=display_count,
        spectral_sample_count=spectral_count,
        source_kind=source_kind,
    )

    reasons = [str(r) for r in (spectral_limit_reasons or []) if str(r).strip()]
    if fs is None or fs <= 0:
        reasons.append("effective_sample_rate_unavailable")
    if kind in {SPECTRAL_SOURCE_CAPPED_20K, SPECTRAL_SOURCE_DOWNSAMPLED}:
        reasons.append("spectral_source_downsampled")
    assessable = bool(spectral_assessable) if spectral_assessable is not None else not reasons

    return {
        "raw_sample_count": raw_count,
        "analyzed_sample_count": analyzed_count,
        "display_sample_count": display_count,
        "spectral_sample_count": spectral_count,
        "duration_s": round(duration, 6) if duration is not None else None,
        "effective_sample_rate_hz": round(fs, 3) if fs is not None else None,
        "nyquist_hz": round(nyquist, 3) if nyquist is not None else None,
        "decimation_factor": round(decimation, 4) if decimation is not None else None,
        "source_kind": kind,
        "spectral_assessable": bool(assessable),
        "spectral_limit_reasons": list(dict.fromkeys(reasons)),
    }


def frequency_assessability(
    metadata: Mapping[str, Any] | None,
    target_hz: Any,
    *,
    reason: str = "not_assessable_due_to_low_sample_rate",
    nyquist_margin: float = 1.05,
) -> dict[str, Any]:
    meta = metadata if isinstance(metadata, Mapping) else {}
    target = _finite_float(target_hz)
    nyquist = _finite_float(meta.get("nyquist_hz"))
    if target is None or target <= 0:
        return {"assessable": False, "reason": "target_frequency_unavailable"}
    if nyquist is None or nyquist <= 0:
        return {"assessable": False, "reason": "nyquist_unavailable"}
    if nyquist < target * float(nyquist_margin):
        return {
            "assessable": False,
            "reason": reason,
            "target_hz": round(target, 3),
            "nyquist_hz": round(nyquist, 3),
        }
    return {
        "assessable": True,
        "reason": "assessable",
        "target_hz": round(target, 3),
        "nyquist_hz": round(nyquist, 3),
    }


def hf_noise_assessability(metadata: Mapping[str, Any] | None, *, min_hf_hz: float = 150.0) -> dict[str, Any]:
    return frequency_assessability(
        metadata,
        min_hf_hz,
        reason="hf_band_not_assessable_due_to_low_sample_rate",
        nyquist_margin=1.0,
    )

