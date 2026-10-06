"""GyroCore flight analysis / spectral evidence (WU4).

No tuning recommendations, no mechanical safety, no actionable CLI.
"""

from __future__ import annotations

from .confidence_unified import compute_unified_confidence
from .d_effectiveness_analysis import analyze_d_effectiveness
from .erpm_analysis import analyze_erpm
from .evidence import build_analysis_evidence
from .flight_split import split_samples_into_flights
from .metrics_engine import build_metrics, samples_dict_from_normalized_rows
from .motor_diagnostics import compute_per_motor_diagnostics
from .motor_saturation import compute_motor_saturation
from .multi_axis_fft import merge_axes_fft
from .problem_detection_engine import detect_problems
from .quality_engine_v2 import evaluate_quality_light, evaluate_quality_v2
from .resonance import analyze_resonance
from .resonance_v2 import detect_resonance_peaks
from .sample_rate_metadata import build_sample_rate_metadata
from .segment_engine import detect_segments
from .signal import compute_sample_rate, time_us_to_seconds
from .spectral_windows import build_spectral_evidence_from_samples
from .step_response_analysis import analyze_step_response

__all__ = [
    "analyze_d_effectiveness",
    "analyze_erpm",
    "analyze_resonance",
    "analyze_step_response",
    "build_analysis_evidence",
    "build_metrics",
    "build_sample_rate_metadata",
    "build_spectral_evidence_from_samples",
    "compute_motor_saturation",
    "compute_per_motor_diagnostics",
    "compute_sample_rate",
    "compute_unified_confidence",
    "detect_problems",
    "detect_resonance_peaks",
    "detect_segments",
    "evaluate_quality_light",
    "evaluate_quality_v2",
    "merge_axes_fft",
    "samples_dict_from_normalized_rows",
    "split_samples_into_flights",
    "time_us_to_seconds",
]
