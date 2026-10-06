"""
CHIRP / Autotune computation mirrors (WU5).

Upstream TypeScript remains the system-ID source of truth under
``third_party/betaflight/configurator/``. This package only hosts thin,
documented mirrors needed for provenance and regression (e.g. sample-rate
formula). Full Bode/coherence/Welch ports are deferred until parity.
"""

from .sample_rate import (
    compute_sample_rate_from_sysconfig,
    compute_sample_rate_hz,
    pid_loop_frequency_hz,
)

__all__ = [
    "compute_sample_rate_hz",
    "compute_sample_rate_from_sysconfig",
    "pid_loop_frequency_hz",
]
