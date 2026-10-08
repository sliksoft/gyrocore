"""
CHIRP / system identification (WU5–WU7). Analysis only — no tuning output.

``pipeline``     — single entry point ``identify_chirp_system`` (WU7)
``sysconfig``    — BBL ``H`` header parsing (upstream ``parseHeader``)
``frames``       — CHIRP field table from GyroCore's decoded CSV
``extraction``   — chirp-active segment extraction (upstream ``parseChirpLog``)
``sample_rate``  — header + timestamp resolution, spacing analysis (WU6/WU7)
``system_id``    — Welch TF, sensitivity, step response, spectrogram, open loop
``quality``      — analysis-validity gates (not PID safety)

Upstream TypeScript under ``third_party/betaflight/configurator/`` remains the
traceable source; vendored snapshots are not modified. ``recommendGains`` and
any apply / MSP / CLI path are intentionally not ported.
"""

from .debug_modes import API_VERSION_MAX_SUPPORTED, chirp_debug_mode_index
from .extraction import ChirpExtraction, ChirpSegment, extract_chirp
from .frames import ChirpFrames, ChirpFramesError, chirp_frames_from_parsed_samples, read_chirp_frames_from_csv
from .pipeline import ChirpAxisResult, ChirpSystemIdResult, identify_chirp_system, identify_chirp_system_from_bbl
from .quality import QualityGate, QualityReport
from .sample_rate import (
    MISMATCH_TOLERANCE_FRACTION,
    SampleRateEvidence,
    SampleRateSource,
    SampleRateStatus,
    TimestampSpacing,
    analyze_timestamp_spacing,
    compute_sample_rate_from_sysconfig,
    compute_sample_rate_hz,
    estimate_timestamp_rate_hz,
    header_logged_rate_hz,
    pid_loop_frequency_hz,
    resolve_chirp_sample_rate,
    resolve_from_sysconfig,
    upstream_autotune_compute_sample_rate_hz,
)
from .sysconfig import ChirpSysConfig, parse_chirp_sysconfig, read_bbl_header_text
from .system_id import (
    OpenLoopResponse,
    Sensitivity,
    Spectrogram,
    StepResponse,
    TransferFunction,
    WelchSpectra,
    choose_segment_size,
    complex_fft,
    compute_sensitivity,
    compute_spectrogram,
    compute_step_response,
    hanning_window,
    open_loop_response,
    welch_spectra,
    welch_transfer_function,
)

__all__ = [
    "API_VERSION_MAX_SUPPORTED",
    "ChirpAxisResult",
    "ChirpExtraction",
    "ChirpFrames",
    "ChirpFramesError",
    "ChirpSegment",
    "ChirpSysConfig",
    "ChirpSystemIdResult",
    "MISMATCH_TOLERANCE_FRACTION",
    "OpenLoopResponse",
    "QualityGate",
    "QualityReport",
    "SampleRateEvidence",
    "SampleRateSource",
    "SampleRateStatus",
    "Sensitivity",
    "Spectrogram",
    "StepResponse",
    "TimestampSpacing",
    "TransferFunction",
    "WelchSpectra",
    "analyze_timestamp_spacing",
    "chirp_debug_mode_index",
    "chirp_frames_from_parsed_samples",
    "choose_segment_size",
    "complex_fft",
    "compute_sample_rate_from_sysconfig",
    "compute_sample_rate_hz",
    "compute_sensitivity",
    "compute_spectrogram",
    "compute_step_response",
    "estimate_timestamp_rate_hz",
    "extract_chirp",
    "hanning_window",
    "header_logged_rate_hz",
    "identify_chirp_system",
    "identify_chirp_system_from_bbl",
    "open_loop_response",
    "parse_chirp_sysconfig",
    "pid_loop_frequency_hz",
    "read_bbl_header_text",
    "read_chirp_frames_from_csv",
    "resolve_chirp_sample_rate",
    "resolve_from_sysconfig",
    "upstream_autotune_compute_sample_rate_hz",
    "welch_spectra",
    "welch_transfer_function",
]
