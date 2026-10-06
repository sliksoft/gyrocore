"""
CHIRP / Autotune computation (WU5–WU6).

``sample_rate`` — header + timestamp resolution (WU6 hardening).
``system_id`` — minimal Welch TF / Bode / coherence port (WU6 foundation).

Upstream TypeScript under ``third_party/betaflight/configurator/`` remains the
traceable Autotune source; vendored snapshots are not modified.
"""

from .sample_rate import (
    MISMATCH_TOLERANCE_FRACTION,
    SampleRateEvidence,
    SampleRateSource,
    SampleRateStatus,
    compute_sample_rate_from_sysconfig,
    compute_sample_rate_hz,
    estimate_timestamp_rate_hz,
    header_logged_rate_hz,
    pid_loop_frequency_hz,
    resolve_chirp_sample_rate,
    resolve_from_sysconfig,
    upstream_autotune_compute_sample_rate_hz,
)
from .system_id import TransferFunction, hanning_window, welch_transfer_function

__all__ = [
    "MISMATCH_TOLERANCE_FRACTION",
    "SampleRateEvidence",
    "SampleRateSource",
    "SampleRateStatus",
    "compute_sample_rate_hz",
    "compute_sample_rate_from_sysconfig",
    "pid_loop_frequency_hz",
    "upstream_autotune_compute_sample_rate_hz",
    "header_logged_rate_hz",
    "estimate_timestamp_rate_hz",
    "resolve_chirp_sample_rate",
    "resolve_from_sysconfig",
    "TransferFunction",
    "hanning_window",
    "welch_transfer_function",
]
