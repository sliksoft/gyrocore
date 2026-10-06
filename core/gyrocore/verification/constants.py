"""Verification / convergence thresholds."""

from __future__ import annotations

# FPVPIDlab VerificationMatcher
SIMILARITY_ACCEPT_THRESHOLD = 70
SIMILARITY_REJECT_THRESHOLD = 40
PEAK_MATCH_TOLERANCE_MIN_HZ = 10.0
MOTOR_HARMONIC_TOLERANCE_RATIO = 0.05

# FPVPIDlab ConvergenceDetector
FILTER_CONVERGENCE_DB = 1.5
FILTER_DIMINISHING_DB = 3.0
FLASH_CONVERGENCE_BW_HZ = 2.0
FLASH_DIMINISHING_BW_HZ = 5.0
FLASH_CONVERGENCE_PM_DEG = 3.0

# GyroCore-specific identity / quality gates
REQUIRE_SAME_BETAFLIGHT_MAJOR = True
MIN_THROTTLE_OVERLAP = 0.25
MIN_QUALITY_FOR_CONVERGED = 0.4  # unified confidence / quality score if present

PROVENANCE = {
    "upstream": "https://github.com/eddycek/fpvpidlab",
    "commit": "76354a022b331a9b466727f9a67ba369a12067ac",
    "license": "GPL-3.0-only",
    "capability": "verification",
    "auto_rollback": False,
}
