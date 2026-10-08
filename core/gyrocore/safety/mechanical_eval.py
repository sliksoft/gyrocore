"""Mechanical safety evaluation (WU10)."""

from __future__ import annotations

from typing import Any, Mapping

from gyrocore.safety.analysis_adapter import (
    analysis_is_usable,
    mechanical_inputs_from_analysis,
)
from gyrocore.safety.mechanical import build_mechanical_safety_gate
from gyrocore.safety.results import MechanicalSafetyResult
from gyrocore.safety.types import SafetyCheck, SafetyVerdict


def evaluate_mechanical_safety(
    analysis: Mapping[str, Any] | None = None,
    *,
    require_analysis: bool = False,
    **gate_kwargs: Any,
) -> MechanicalSafetyResult:
    """Run the donor mechanical gate against WU4 evidence and/or explicit kwargs.

    ``require_analysis=True`` fails closed when analysis is missing or unusable
    (GyroCore Autotune path). Direct donor-parity calls leave it False so empty
    kwargs still match AeroTuner (pass / mechanical_clear).
    """
    extra: list[SafetyCheck] = []
    kwargs = dict(gate_kwargs)
    provenance: dict[str, Any] = {
        "function": "build_mechanical_safety_gate",
        "donor": "backend.services.mechanical_safety_gate",
    }
    if analysis is not None:
        provenance["analysis_ok"] = bool(analysis.get("ok")) if isinstance(analysis, Mapping) else False
        if require_analysis and not analysis_is_usable(analysis):
            extra.append(
                SafetyCheck(
                    rule_id="mechanical.missing_required_analysis",
                    verdict=SafetyVerdict.BLOCK,
                    message=str((analysis or {}).get("message") or "missing_required_analysis"),
                )
            )
            return MechanicalSafetyResult.from_gate(
                {
                    "mechanical_block": True,
                    "mechanical_limited": False,
                    "mechanical_caution": False,
                    "mechanical_outcome": "mechanical_block",
                    "severity": "blocked",
                    "reasons": ["missing_required_analysis"],
                    "blocking_reasons": ["missing_required_analysis"],
                    "limited_reasons": [],
                    "caution_reasons": [],
                    "recommended_action": "guidance_only",
                    "user_message": ["Required analysis evidence is missing or unusable."],
                    "evidence": {"max_delta_scale": 0.0},
                    "limited_tier": "blocked",
                    "max_delta_scale": 0.0,
                },
                extra_checks=tuple(extra),
                provenance=provenance,
            )
        mapped = mechanical_inputs_from_analysis(analysis)
        for key, value in mapped.items():
            kwargs.setdefault(key, value)
    elif require_analysis:
        return MechanicalSafetyResult.from_gate(
            {
                "mechanical_block": True,
                "mechanical_limited": False,
                "mechanical_caution": False,
                "mechanical_outcome": "mechanical_block",
                "severity": "blocked",
                "reasons": ["missing_required_analysis"],
                "blocking_reasons": ["missing_required_analysis"],
                "limited_reasons": [],
                "caution_reasons": [],
                "recommended_action": "guidance_only",
                "user_message": ["Required analysis evidence is missing or unusable."],
                "evidence": {"max_delta_scale": 0.0},
                "limited_tier": "blocked",
                "max_delta_scale": 0.0,
            },
            extra_checks=(
                SafetyCheck(
                    rule_id="mechanical.missing_required_analysis",
                    verdict=SafetyVerdict.BLOCK,
                    message="missing_required_analysis",
                ),
            ),
            provenance=provenance,
        )

    gate = build_mechanical_safety_gate(**kwargs)
    return MechanicalSafetyResult.from_gate(gate, extra_checks=tuple(extra), provenance=provenance)


__all__ = ["evaluate_mechanical_safety"]
