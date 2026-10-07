"""Map WU4 ``build_analysis_evidence`` output onto donor mechanical-gate kwargs.

Does not re-run resonance / motor / problem / quality analysis.
"""

from __future__ import annotations

from typing import Any, Mapping


def mechanical_inputs_from_analysis(
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Translate GyroCore analysis evidence into ``build_mechanical_safety_gate`` kwargs."""
    if not isinstance(evidence, Mapping):
        return {}
    motors = evidence.get("motors") if isinstance(evidence.get("motors"), Mapping) else {}
    diagnostics = motors.get("diagnostics") if isinstance(motors, Mapping) else {}
    quality = evidence.get("quality") if isinstance(evidence.get("quality"), Mapping) else {}
    confidence = evidence.get("confidence")
    metrics = evidence.get("metrics") if isinstance(evidence.get("metrics"), Mapping) else {}
    noise = metrics.get("noise") if isinstance(metrics, Mapping) else None
    noise_level: str | None = None
    if isinstance(noise, Mapping):
        raw = noise.get("level")
        if raw is not None:
            noise_level = str(raw)
        else:
            # metrics.noise.value is cleanliness (0–100, higher = cleaner); same
            # bands as the donor route before build_mechanical_safety_gate.
            try:
                clean = float(noise.get("value"))
            except (TypeError, ValueError):
                clean = 0.0
            clean = max(0.0, min(100.0, clean)) if clean == clean else 0.0
            if clean >= 75.0:
                noise_level = "LOW"
            elif clean >= 50.0:
                noise_level = "MEDIUM"
            else:
                noise_level = "HIGH"
    quality_status = quality.get("status") if isinstance(quality, Mapping) else None
    # Donor gate kwargs only. Extra WU4 surfaces (FFT, step, D-term, eRPM,
    # saturation) already feed problems/metrics/motors — they are not re-run here.
    return {
        "pipeline_problems": evidence.get("problems"),
        "motor_diagnostics": diagnostics if isinstance(diagnostics, Mapping) else {},
        "engine_metrics": metrics if isinstance(metrics, Mapping) else {},
        "resonance_module": evidence.get("resonance"),
        "confidence_eval": confidence if isinstance(confidence, Mapping) else {},
        "quality_status": str(quality_status) if quality_status is not None else None,
        "noise_level": noise_level,
    }


def analysis_is_usable(evidence: Mapping[str, Any] | None) -> bool:
    if not isinstance(evidence, Mapping):
        return False
    if evidence.get("ok") is False:
        return False
    return True


__all__ = ["analysis_is_usable", "mechanical_inputs_from_analysis"]
