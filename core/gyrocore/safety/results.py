"""Staged safety result types. Public constructors require a private stage token."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from gyrocore.autotune.absolute import AbsoluteTune, AbsoluteTuneProposal
from gyrocore.safety.types import (
    STAGE_FINAL,
    STAGE_MECHANICAL,
    STAGE_OUTPUT,
    STAGE_SAFE_TUNE,
    SafetyCheck,
    SafetyVerdict,
    StageBypassError,
    _require_token,
)
from gyrocore.safety.types import (
    _FINAL_TOKEN,
    _MECHANICAL_TOKEN,
    _OUTPUT_TOKEN,
    _SAFE_TUNE_TOKEN,
)

NON_ACTIONABLE_FINAL_NOTICE = (
    "FinalSafeTuneResult is never actionable in WU10. WU11 is the first work unit "
    "allowed to convert a passed result into CLI/apply output."
)


@dataclass(frozen=True)
class MechanicalSafetyResult:
    """Structured mechanical gate. Must be produced by ``evaluate_mechanical_safety``."""

    status: SafetyVerdict
    mechanical_block: bool
    mechanical_limited: bool
    mechanical_caution: bool
    mechanical_outcome: str
    recommended_action: str
    reasons: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    limited_reasons: tuple[str, ...]
    caution_reasons: tuple[str, ...]
    max_delta_scale: float
    evidence: Mapping[str, Any]
    checks: tuple[SafetyCheck, ...]
    raw: Mapping[str, Any]
    provenance: Mapping[str, Any] = field(default_factory=dict)
    _token: object = field(default=None, repr=False, compare=False)

    stage: str = field(default=STAGE_MECHANICAL, init=False)

    def __post_init__(self) -> None:
        _require_token(self._token, _MECHANICAL_TOKEN, "MechanicalSafetyResult")
        object.__setattr__(self, "stage", STAGE_MECHANICAL)

    @classmethod
    def from_gate(
        cls,
        gate: Mapping[str, Any],
        *,
        extra_checks: tuple[SafetyCheck, ...] = (),
        provenance: Mapping[str, Any] | None = None,
    ) -> MechanicalSafetyResult:
        from gyrocore.safety.types import verdict_from_mechanical_gate

        data = dict(gate)
        verdict = verdict_from_mechanical_gate(data)
        blocking = tuple(str(x) for x in (data.get("blocking_reasons") or []) if str(x).strip())
        limited = tuple(str(x) for x in (data.get("limited_reasons") or []) if str(x).strip())
        caution = tuple(str(x) for x in (data.get("caution_reasons") or []) if str(x).strip())
        reasons = tuple(str(x) for x in (data.get("reasons") or []) if str(x).strip())
        evidence = data.get("evidence") if isinstance(data.get("evidence"), Mapping) else {}
        try:
            scale = float(data.get("max_delta_scale", evidence.get("max_delta_scale", 1.0)))
        except (TypeError, ValueError):
            scale = 0.0 if verdict is SafetyVerdict.BLOCK else 1.0
        if verdict is SafetyVerdict.BLOCK:
            scale = 0.0
        checks = list(extra_checks)
        for code in blocking:
            checks.append(
                SafetyCheck(
                    rule_id=f"mechanical.block.{code}",
                    verdict=SafetyVerdict.BLOCK,
                    message=code,
                    evidence={"max_delta_scale": scale},
                )
            )
        for code in limited:
            checks.append(
                SafetyCheck(
                    rule_id=f"mechanical.limited.{code}",
                    verdict=SafetyVerdict.WARN,
                    message=code,
                    evidence={"max_delta_scale": scale},
                )
            )
        for code in caution:
            checks.append(
                SafetyCheck(
                    rule_id=f"mechanical.caution.{code}",
                    verdict=SafetyVerdict.WARN,
                    message=code,
                )
            )
        if verdict is SafetyVerdict.PASS and not checks:
            checks.append(
                SafetyCheck(
                    rule_id="mechanical.pass",
                    verdict=SafetyVerdict.PASS,
                    message="mechanical_clear",
                    evidence=dict(evidence),
                )
            )
        return cls(
            status=verdict,
            mechanical_block=bool(data.get("mechanical_block")),
            mechanical_limited=bool(data.get("mechanical_limited")),
            mechanical_caution=bool(data.get("mechanical_caution")),
            mechanical_outcome=str(data.get("mechanical_outcome") or ""),
            recommended_action=str(data.get("recommended_action") or ""),
            reasons=reasons,
            blocking_reasons=blocking,
            limited_reasons=limited,
            caution_reasons=caution,
            max_delta_scale=scale,
            evidence=dict(evidence),
            checks=tuple(checks),
            raw=data,
            provenance=dict(provenance or {"donor": "build_mechanical_safety_gate"}),
            _token=_MECHANICAL_TOKEN,
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        return dict(self.raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status.value,
            "mechanical_block": self.mechanical_block,
            "mechanical_limited": self.mechanical_limited,
            "mechanical_caution": self.mechanical_caution,
            "mechanical_outcome": self.mechanical_outcome,
            "recommended_action": self.recommended_action,
            "reasons": list(self.reasons),
            "blocking_reasons": list(self.blocking_reasons),
            "limited_reasons": list(self.limited_reasons),
            "caution_reasons": list(self.caution_reasons),
            "max_delta_scale": self.max_delta_scale,
            "evidence": dict(self.evidence),
            "checks": [c.to_dict() for c in self.checks],
            "provenance": dict(self.provenance),
        }


@dataclass(frozen=True)
class SafeTuneCandidate:
    """Non-actionable clamped candidate. Requires a MechanicalSafetyResult token."""

    status: SafetyVerdict
    proposal: AbsoluteTuneProposal
    mechanical: MechanicalSafetyResult
    current_config: Mapping[str, Any]
    proposed_config: Mapping[str, Any] | None
    clamped_config: Mapping[str, Any] | None
    clamped_tune: AbsoluteTune | None
    max_delta_used: Mapping[str, Any]
    clamp_ids: tuple[str, ...]
    checks: tuple[SafetyCheck, ...]
    blocked_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    provenance: Mapping[str, Any] = field(default_factory=dict)
    _token: object = field(default=None, repr=False, compare=False)

    stage: str = field(default=STAGE_SAFE_TUNE, init=False)
    actionable: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_token(self._token, _SAFE_TUNE_TOKEN, "SafeTuneCandidate")
        if not isinstance(self.mechanical, MechanicalSafetyResult):
            raise StageBypassError("SafeTuneCandidate requires MechanicalSafetyResult")
        object.__setattr__(self, "stage", STAGE_SAFE_TUNE)
        object.__setattr__(self, "actionable", False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status.value,
            "actionable": False,
            "clamp_ids": list(self.clamp_ids),
            "blocked_reasons": list(self.blocked_reasons),
            "warnings": list(self.warnings),
            "max_delta_used": dict(self.max_delta_used),
            "current_config": dict(self.current_config),
            "proposed_config": dict(self.proposed_config) if self.proposed_config else None,
            "clamped_config": dict(self.clamped_config) if self.clamped_config else None,
            "clamped_tune": self.clamped_tune.to_dict() if self.clamped_tune else None,
            "checks": [c.to_dict() for c in self.checks],
            "mechanical": self.mechanical.to_dict(),
            "provenance": dict(self.provenance),
        }


def make_safe_tune_candidate(**kwargs: Any) -> SafeTuneCandidate:
    return SafeTuneCandidate(_token=_SAFE_TUNE_TOKEN, **kwargs)


@dataclass(frozen=True)
class TuningOutputSafetyResult:
    """Final output-safety gate. Requires a SafeTuneCandidate token."""

    status: SafetyVerdict
    candidate: SafeTuneCandidate
    blocking_reasons: tuple[str, ...]
    warning_reasons: tuple[str, ...]
    checks: tuple[SafetyCheck, ...]
    donor_status: str
    provenance: Mapping[str, Any] = field(default_factory=dict)
    _token: object = field(default=None, repr=False, compare=False)

    stage: str = field(default=STAGE_OUTPUT, init=False)
    cli_actionable: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        _require_token(self._token, _OUTPUT_TOKEN, "TuningOutputSafetyResult")
        if not isinstance(self.candidate, SafeTuneCandidate):
            raise StageBypassError("TuningOutputSafetyResult requires SafeTuneCandidate")
        object.__setattr__(self, "stage", STAGE_OUTPUT)
        object.__setattr__(self, "cli_actionable", False)

    def to_legacy_dict(self) -> dict[str, Any]:
        status = {
            SafetyVerdict.PASS: "actionable",
            SafetyVerdict.WARN: "limited",
            SafetyVerdict.BLOCK: "blocked",
        }[self.status]
        return {
            "present": True,
            "status": status,
            "cli_actionable": False,
            "cli_availability": "unavailable",
            "blocking_reasons": list(self.blocking_reasons),
            "hard_block_reasons": list(self.blocking_reasons) if self.status is SafetyVerdict.BLOCK else [],
            "diagnostic_reasons": list(self.blocking_reasons) if self.status is SafetyVerdict.BLOCK else [],
            "reasons": list(self.blocking_reasons) + list(self.warning_reasons),
            "warnings": list(self.warning_reasons),
            "mechanical": self.candidate.mechanical.to_legacy_dict(),
            "snapshot_partial": False,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status.value,
            "donor_status": self.donor_status,
            "cli_actionable": False,
            "blocking_reasons": list(self.blocking_reasons),
            "warning_reasons": list(self.warning_reasons),
            "checks": [c.to_dict() for c in self.checks],
            "candidate": self.candidate.to_dict(),
            "provenance": dict(self.provenance),
        }


def make_tuning_output_safety(**kwargs: Any) -> TuningOutputSafetyResult:
    return TuningOutputSafetyResult(_token=_OUTPUT_TOKEN, **kwargs)


@dataclass(frozen=True)
class FinalSafeTuneResult:
    """Terminal WU10 result. Always ``actionable=False``."""

    status: SafetyVerdict
    output_safety: TuningOutputSafetyResult
    warnings: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    provenance: Mapping[str, Any] = field(default_factory=dict)
    _token: object = field(default=None, repr=False, compare=False)

    stage: str = field(default=STAGE_FINAL, init=False)
    actionable: bool = field(default=False, init=False)
    kind: str = field(default="gyrocore_final_safe_tune", init=False)

    def __post_init__(self) -> None:
        _require_token(self._token, _FINAL_TOKEN, "FinalSafeTuneResult")
        if not isinstance(self.output_safety, TuningOutputSafetyResult):
            raise StageBypassError("FinalSafeTuneResult requires TuningOutputSafetyResult")
        object.__setattr__(self, "stage", STAGE_FINAL)
        object.__setattr__(self, "actionable", False)
        object.__setattr__(self, "kind", "gyrocore_final_safe_tune")

    @property
    def proposal(self) -> AbsoluteTuneProposal:
        return self.output_safety.candidate.proposal

    @property
    def mechanical(self) -> MechanicalSafetyResult:
        return self.output_safety.candidate.mechanical

    @property
    def candidate(self) -> SafeTuneCandidate:
        return self.output_safety.candidate

    @property
    def current_tune(self) -> AbsoluteTune:
        return self.proposal.current

    @property
    def original_proposal_tune(self) -> AbsoluteTune | None:
        return self.proposal.proposed

    @property
    def clamped_tune(self) -> AbsoluteTune | None:
        return self.candidate.clamped_tune

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "stage": self.stage,
            "status": self.status.value,
            "actionable": False,
            "non_actionable_notice": NON_ACTIONABLE_FINAL_NOTICE,
            "warnings": list(self.warnings),
            "blocked_reasons": list(self.blocked_reasons),
            "current_tune": self.current_tune.to_dict(),
            "original_proposal": self.proposal.to_dict(),
            "clamped_tune": self.clamped_tune.to_dict() if self.clamped_tune else None,
            "mechanical_safety": self.mechanical.to_dict(),
            "clamp_evidence": self.candidate.to_dict(),
            "tuning_output_safety": self.output_safety.to_dict(),
            "provenance": dict(self.provenance),
        }


def make_final_safe_tune(**kwargs: Any) -> FinalSafeTuneResult:
    return FinalSafeTuneResult(_token=_FINAL_TOKEN, **kwargs)


__all__ = [
    "FinalSafeTuneResult",
    "MechanicalSafetyResult",
    "NON_ACTIONABLE_FINAL_NOTICE",
    "SafeTuneCandidate",
    "TuningOutputSafetyResult",
    "make_final_safe_tune",
    "make_safe_tune_candidate",
    "make_tuning_output_safety",
]
