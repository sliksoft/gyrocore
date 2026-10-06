# Re-export documented sample-rate mirror for desktop adapters.
# Implementation lives in gyrocore.chirp (Python Core) for testability;
# full CHIRP/system-ID math remains in third_party TypeScript until parity.

from gyrocore.chirp.sample_rate import (  # noqa: F401
    compute_sample_rate_from_sysconfig,
    compute_sample_rate_hz,
    pid_loop_frequency_hz,
)
