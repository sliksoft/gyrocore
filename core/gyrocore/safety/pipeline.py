"""Mandatory staged safety pipeline (WU10).

AbsoluteTuneProposal
    → MechanicalSafetyResult
    → SafeTuneCandidate
    → TuningOutputSafetyResult
    → FinalSafeTuneResult  (actionable = False)
"""

from __future__ import annotations

from typing import Any, Mapping

from gyrocore.autotune.absolute import AbsoluteTuneProposal
from gyrocore.safety.mechanical_eval import evaluate_mechanical_safety
from gyrocore.safety.output import evaluate_tuning_output_safety
from gyrocore.safety.results import (
    FinalSafeTuneResult,
    MechanicalSafetyResult,
    SafeTuneCandidate,
    TuningOutputSafetyResult,
    make_final_safe_tune,
)
from gyrocore.safety.safe_tune import clamp_safe_tune
from gyrocore.safety.types import SafetyVerdict, StageBypassError


def finalize_safe_tune(output_safety: TuningOutputSafetyResult) -> FinalSafeTuneResult:
    """Last WU10 stage. Always ``actionable=False`` even on PASS."""
    if not isinstance(output_safety, TuningOutputSafetyResult):
        raise StageBypassError("finalize_safe_tune requires TuningOutputSafetyResult")
    warnings = list(output_safety.warning_reasons)
    warnings.extend(output_safety.candidate.warnings)
    blocked = list(output_safety.blocking_reasons)
    return make_final_safe_tune(
        status=output_safety.status,
        output_safety=output_safety,
        warnings=tuple(dict.fromkeys(warnings)),
        blocked_reasons=tuple(dict.fromkeys(blocked)),
        provenance={
            "stages": [
                "mechanical_safety",
                "safe_tune_clamps",
                "tuning_output_safety",
                "final_safe_tune",
            ],
            "actionable": False,
            "next_wu": "WU11_cli_apply",
        },
    )


def run_safety_pipeline(
    proposal: AbsoluteTuneProposal,
    *,
    analysis: Mapping[str, Any] | None,
    hardware: Mapping[str, Any] | None = None,
    require_analysis: bool = True,
) -> FinalSafeTuneResult:
    """Run every stage in order. There is no skip path."""
    mechanical = evaluate_mechanical_safety(analysis, require_analysis=require_analysis)
    candidate = clamp_safe_tune(proposal, mechanical, analysis=analysis, hardware=hardware)
    tos = evaluate_tuning_output_safety(
        candidate, analysis=analysis, require_analysis=require_analysis
    )
    return finalize_safe_tune(tos)


__all__ = [
    "FinalSafeTuneResult",
    "MechanicalSafetyResult",
    "SafeTuneCandidate",
    "TuningOutputSafetyResult",
    "finalize_safe_tune",
    "run_safety_pipeline",
]
