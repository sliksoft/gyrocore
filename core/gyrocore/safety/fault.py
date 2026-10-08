"""Mechanical fault evidence helpers (WU10).

Donor: AeroTuner ``backend/services/craft_tuning_policy.py``
(``MechanicalFaultEvidence``, ``collect_mechanical_fault_evidence``,
``noise_only_low_confidence_should_caution_not_limit``).

Policy A/B/D (D-min, intent, FF boost) and HTTP serialization are not migrated.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

HEALTHY_MOTOR_HEALTH_MIN = 75.0

_FLAT_MECHANICAL_FAULT_FIELD_KEYS = frozenset(
    {
        "bad_motor_count",
        "relative_bad_motor_count",
        "desync_risk",
        "resonance_severity",
        "broad_resonance",
        "persistent_resonance",
        "motor_health",
        "independent_mechanical_evidence",
        "high_severity_motor_issue",
    }
)

_CAUTION_ONLY_NON_FAULT_REASONS = frozenset(
    {
        "noise_low_confidence_capped",
        "motor_warning_caution",
        "motor_correction_demand_caution",
    }
)

_LIMITED_ONLY_NON_FAULT_REASONS = frozenset(
    {
        "mechanical_noise_low_confidence",
        "warning_motor_diagnostic",
        "per_motor_noise_anomaly",
        "medium_broad_resonance",
        "broad_frame_resonance_noise",
        "persistent_resonance_with_noise_risk",
        "motor_issue_medium_severity",
        "motor_correction_demand_uncertain",
    }
)


def _coerce_float(val: Any, default: float = 0.0) -> float:
    if val is None or isinstance(val, bool):
        return default
    try:
        v = float(val)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(v):
        return default
    return v


@dataclass
class MechanicalFaultEvidence:
    """Independent mechanical danger signals (Policy C)."""

    bad_motor_count: int = 0
    relative_bad_motor_count: int = 0
    desync_risk: bool = False
    resonance_severity: str = "low"
    broad_resonance: bool = False
    persistent_resonance: bool = False
    motor_health: float = 100.0
    blocking_reasons: tuple[str, ...] = ()
    independent_mechanical_evidence: bool = False
    high_severity_motor_issue: bool = False

    @property
    def has_fault(self) -> bool:
        if self.blocking_reasons or self.independent_mechanical_evidence:
            return True
        if self.bad_motor_count > 0 or self.relative_bad_motor_count > 0:
            return True
        if self.desync_risk:
            return True
        if self.high_severity_motor_issue:
            return True
        if self.resonance_severity == "high":
            return True
        if self.persistent_resonance and (
            self.bad_motor_count > 0 or self.broad_resonance
        ):
            return True
        if self.motor_health < 52.0:
            return True
        return False

    @property
    def motors_healthy(self) -> bool:
        return (
            self.bad_motor_count == 0
            and self.relative_bad_motor_count == 0
            and not self.desync_risk
            and self.motor_health >= HEALTHY_MOTOR_HEALTH_MIN
            and self.resonance_severity in {"low", "none", ""}
            and not self.persistent_resonance
        )


def _is_flat_serialized_mechanical_fault(value: Mapping[str, Any]) -> bool:
    if isinstance(value.get("evidence"), Mapping):
        return False
    return bool(_FLAT_MECHANICAL_FAULT_FIELD_KEYS.intersection(value.keys()))


def _gate_blocking_reason_list(gate: Mapping[str, Any]) -> list[str]:
    raw = gate.get("blocking_reasons")
    if raw is None:
        legacy = gate.get("reasons")
        if isinstance(legacy, list):
            return [str(x).strip() for x in legacy if str(x).strip()]
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def _mechanical_outcome_from_gate(
    gate: Mapping[str, Any], evidence: Mapping[str, Any]
) -> str:
    outcome = gate.get("mechanical_outcome")
    if isinstance(outcome, str) and outcome.strip():
        return outcome.strip().lower()
    ev_out = evidence.get("mechanical_outcome")
    if isinstance(ev_out, str) and ev_out.strip():
        return ev_out.strip().lower()
    return ""


def _apply_mechanical_clear_semantic_guard(
    *,
    gate: Mapping[str, Any],
    evidence: Mapping[str, Any],
    blocking: tuple[str, ...],
    limited: list[str],
    high_sev: bool,
) -> tuple[tuple[str, ...], bool]:
    outcome = _mechanical_outcome_from_gate(gate, evidence)
    independent = bool(evidence.get("independent_mechanical_evidence"))
    if independent or outcome != "mechanical_clear":
        return blocking, high_sev

    blocking = tuple(x for x in blocking if x not in _CAUTION_ONLY_NON_FAULT_REASONS)
    if not blocking and set(limited) <= _LIMITED_ONLY_NON_FAULT_REASONS:
        high_sev = False
    return blocking, high_sev


def collect_mechanical_fault_evidence(
    *,
    mechanical_gate: Mapping[str, Any] | None = None,
    motor_diagnostics: Mapping[str, Any] | None = None,
    analysis: Mapping[str, Any] | None = None,
) -> MechanicalFaultEvidence:
    gate = mechanical_gate if isinstance(mechanical_gate, Mapping) else {}
    md = motor_diagnostics if isinstance(motor_diagnostics, Mapping) else {}
    evidence = gate.get("evidence") if isinstance(gate.get("evidence"), Mapping) else {}

    health_raw = _coerce_float(md.get("health"), _coerce_float(md.get("aggregate_motor_health"), 100.0))
    if health_raw <= 1.0:
        health_pct = health_raw * 100.0
    else:
        health_pct = health_raw

    limited = [str(x) for x in (gate.get("limited_reasons") or []) if str(x).strip()]
    blocking = tuple(_gate_blocking_reason_list(gate))
    independent = bool(evidence.get("independent_mechanical_evidence"))
    mechanical_block = bool(gate.get("mechanical_block"))
    high_sev = any(
        str(x)
        in {
            "motor_issue_high_severity_danger",
            "bad_motor_diagnostic",
            "dangerous_flight_event",
        }
        for x in blocking
    )
    if independent or mechanical_block:
        high_sev = high_sev or "motor_issue_high_severity" in limited
    blocking, high_sev = _apply_mechanical_clear_semantic_guard(
        gate=gate,
        evidence=evidence,
        blocking=blocking,
        limited=limited,
        high_sev=high_sev,
    )

    desync = False
    if isinstance(analysis, Mapping):
        md_a = analysis.get("motor_diagnostics")
        if isinstance(md_a, Mapping):
            desync = bool(md_a.get("has_desync_risk") or md_a.get("desync_risk"))
    desync = desync or bool(md.get("has_desync_risk") or md.get("desync_risk"))

    return MechanicalFaultEvidence(
        bad_motor_count=int(_coerce_float(evidence.get("bad_motor_count"), 0)),
        relative_bad_motor_count=int(_coerce_float(evidence.get("relative_bad_motor_count"), 0)),
        desync_risk=desync,
        resonance_severity=str(evidence.get("resonance_severity") or "low").strip().lower(),
        broad_resonance=bool(evidence.get("broad_resonance")),
        persistent_resonance=bool(evidence.get("persistent_resonance")),
        motor_health=health_pct,
        blocking_reasons=blocking,
        independent_mechanical_evidence=bool(evidence.get("independent_mechanical_evidence")),
        high_severity_motor_issue=high_sev,
    )


def normalize_mechanical_fault_evidence(
    value: MechanicalFaultEvidence | Mapping[str, Any] | None,
) -> MechanicalFaultEvidence:
    if value is None:
        return MechanicalFaultEvidence()
    if isinstance(value, MechanicalFaultEvidence):
        return value
    if not isinstance(value, Mapping):
        return MechanicalFaultEvidence()
    if _is_flat_serialized_mechanical_fault(value):
        blocking_raw = value.get("blocking_reasons") or ()
        if isinstance(blocking_raw, list):
            blocking = tuple(str(x).strip() for x in blocking_raw if str(x).strip())
        elif isinstance(blocking_raw, tuple):
            blocking = tuple(str(x).strip() for x in blocking_raw if str(x).strip())
        else:
            blocking = ()
        return MechanicalFaultEvidence(
            bad_motor_count=int(_coerce_float(value.get("bad_motor_count"), 0)),
            relative_bad_motor_count=int(
                _coerce_float(value.get("relative_bad_motor_count"), 0)
            ),
            desync_risk=bool(value.get("desync_risk")),
            resonance_severity=str(value.get("resonance_severity") or "low")
            .strip()
            .lower(),
            broad_resonance=bool(value.get("broad_resonance")),
            persistent_resonance=bool(value.get("persistent_resonance")),
            motor_health=_coerce_float(value.get("motor_health"), 100.0),
            blocking_reasons=blocking,
            independent_mechanical_evidence=bool(
                value.get("independent_mechanical_evidence")
            ),
            high_severity_motor_issue=bool(value.get("high_severity_motor_issue")),
        )
    return collect_mechanical_fault_evidence(mechanical_gate=value)


def serialize_mechanical_fault_evidence(
    evidence: MechanicalFaultEvidence | Mapping[str, Any] | None,
) -> dict[str, Any]:
    normalized = normalize_mechanical_fault_evidence(evidence)
    payload = asdict(normalized)
    blocking = payload.get("blocking_reasons")
    if isinstance(blocking, tuple):
        payload["blocking_reasons"] = list(blocking)
    return payload


def noise_only_low_confidence_should_caution_not_limit(
    *,
    limited_reasons: list[str],
    mechanical_fault: MechanicalFaultEvidence,
    high_noise: bool,
    low_confidence: bool,
) -> bool:
    if not low_confidence or not high_noise:
        return False
    if mechanical_fault.has_fault:
        return False
    noise_only = set(limited_reasons) <= {
        "mechanical_noise_low_confidence",
        "warning_motor_diagnostic",
        "per_motor_noise_anomaly",
        "medium_broad_resonance",
        "broad_frame_resonance_noise",
        "persistent_resonance_with_noise_risk",
    }
    return noise_only and mechanical_fault.motors_healthy


__all__ = [
    "HEALTHY_MOTOR_HEALTH_MIN",
    "MechanicalFaultEvidence",
    "collect_mechanical_fault_evidence",
    "noise_only_low_confidence_should_caution_not_limit",
    "normalize_mechanical_fault_evidence",
    "serialize_mechanical_fault_evidence",
]
