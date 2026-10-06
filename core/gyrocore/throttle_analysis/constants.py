"""Throttle spectrogram / TPA advisory constants (FPVPIDlab + GyroCore)."""

from __future__ import annotations

DEFAULT_NUM_BANDS = 10
MIN_SAMPLES_PER_BAND = 512
MIN_CONTIGUOUS_RUN = 512
FFT_WINDOW_SIZE = 4096

DEFAULT_TF_BANDS = 5
MIN_TF_SAMPLES = 2048
MIN_TF_RUN_SAMPLES = 2048

# Variance thresholds for TPA review advisory (FPVPIDlab ThrottleTFAnalyzer)
TPA_VARIANCE_BANDWIDTH_HZ = 15.0
TPA_VARIANCE_OVERSHOOT_PCT = 10.0
TPA_VARIANCE_PHASE_MARGIN_DEG = 10.0
TPA_TF_MIN_BANDS = 3
TPA_HIGH_THROTTLE_OVERSHOOT_DELTA_PP = 10.0

PROVENANCE = {
    "upstream": "https://github.com/eddycek/fpvpidlab",
    "commit": "76354a022b331a9b466727f9a67ba369a12067ac",
    "license": "GPL-3.0-only",
    "capability": "throttle_analysis",
    "tpa_auto_apply": False,
}
