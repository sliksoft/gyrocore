"""Staged safety tokens and verdict types (WU10).

Construction of later-stage results requires the previous-stage token object.
There is no public constructor that jumps from AbsoluteTuneProposal to a final result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

STAGE_MECHANICAL = "mechanical_safety"
STAGE_SAFE_TUNE = "safe_tune_clamps"
STAGE_OUTPUT = "tuning_output_safety"
STAGE_FINAL = "final_safe_tune"

_MECHANICAL_TOKEN = object()
_SAFE_TUNE_TOKEN = object()
_OUTPUT_TOKEN = object()
_FINAL_TOKEN = object()


class SafetyVerdict(str, Enum):
    PASS = "pass"
    WARN = "warn"
    BLOCK = "block"


class StageBypassError(TypeError):
    """Raised when a later safety stage is constructed without the previous token."""


def _require_token(got: object, expected: object, stage: str) -> None:
    if got is not expected:
        raise StageBypassError(
            f"{stage} cannot be constructed directly; use the staged pipeline functions"
        )


@dataclass(frozen=True)
class SafetyCheck:
    """One machine-readable safety/clamp decision."""

    rule_id: str
    verdict: SafetyVerdict
    message: str
    before: Any = None
    after: Any = None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "verdict": self.verdict.value,
            "message": self.message,
            "before": self.before,
            "after": self.after,
            "evidence": dict(self.evidence),
        }


def verdict_from_mechanical_gate(gate: Mapping[str, Any]) -> SafetyVerdict:
    if gate.get("mechanical_block") is True:
        return SafetyVerdict.BLOCK
    if gate.get("mechanical_limited") is True or gate.get("mechanical_caution") is True:
        return SafetyVerdict.WARN
    return SafetyVerdict.PASS


__all__ = [
    "STAGE_FINAL",
    "STAGE_MECHANICAL",
    "STAGE_OUTPUT",
    "STAGE_SAFE_TUNE",
    "SafetyCheck",
    "SafetyVerdict",
    "StageBypassError",
    "verdict_from_mechanical_gate",
]
