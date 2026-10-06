"""GyroCore preprocess: sample normalization, flight split/selection, sample-rate helpers (WU4)."""

from __future__ import annotations

from .flight_selection import select_best_flight_for_analysis
from .normalize import (
    BETAFLIGHT_GYRO_ADC_TO_DEG_PER_SEC,
    build_gyro_scale_metadata,
    detect_gyro_scale,
    normalize_raw_samples,
    normalize_samples,
)
from .sample_rate import infer_sample_rate_hz

__all__ = [
    "BETAFLIGHT_GYRO_ADC_TO_DEG_PER_SEC",
    "build_gyro_scale_metadata",
    "detect_gyro_scale",
    "infer_sample_rate_hz",
    "normalize_raw_samples",
    "normalize_samples",
    "select_best_flight_for_analysis",
]
