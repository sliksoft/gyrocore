"""GyroCore staged tuning safety pipeline (WU10).

No CLI, MSP, or FC writes. ``FinalSafeTuneResult.actionable`` is always False.
"""

from __future__ import annotations

from gyrocore.safety.clamps import (
    DEFAULT_MAX_DELTA,
    apply_safety,
    apply_safety_autotune,
    apply_to_baseline,
)
from gyrocore.safety.mechanical import build_mechanical_safety_gate
from gyrocore.safety.mechanical_eval import evaluate_mechanical_safety
from gyrocore.safety.output import evaluate_tuning_output_safety
from gyrocore.safety.pipeline import finalize_safe_tune, run_safety_pipeline
from gyrocore.safety.results import (
    FinalSafeTuneResult,
    MechanicalSafetyResult,
    NON_ACTIONABLE_FINAL_NOTICE,
    SafeTuneCandidate,
    TuningOutputSafetyResult,
)
from gyrocore.safety.safe_tune import clamp_safe_tune
from gyrocore.safety.types import SafetyCheck, SafetyVerdict, StageBypassError

__all__ = [
    "DEFAULT_MAX_DELTA",
    "FinalSafeTuneResult",
    "MechanicalSafetyResult",
    "NON_ACTIONABLE_FINAL_NOTICE",
    "SafeTuneCandidate",
    "SafetyCheck",
    "SafetyVerdict",
    "StageBypassError",
    "TuningOutputSafetyResult",
    "apply_safety",
    "apply_safety_autotune",
    "apply_to_baseline",
    "build_mechanical_safety_gate",
    "clamp_safe_tune",
    "evaluate_mechanical_safety",
    "evaluate_tuning_output_safety",
    "finalize_safe_tune",
    "run_safety_pipeline",
]
