"""Convergence / regression detection with measurement-quality gating."""

from __future__ import annotations

from typing import Any

from .constants import (
    FILTER_CONVERGENCE_DB,
    FILTER_DIMINISHING_DB,
    FLASH_CONVERGENCE_BW_HZ,
    FLASH_DIMINISHING_BW_HZ,
    MIN_QUALITY_FOR_CONVERGED,
)
from .models import ConvergenceStatus, FlightSnapshot


def _axis_noise_delta(before: FlightSnapshot, after: FlightSnapshot) -> list[tuple[str, float]]:
    deltas: list[tuple[str, float]] = []
    for axis in ("roll", "pitch", "yaw"):
        if axis in before.noise_floor_db and axis in after.noise_floor_db:
            deltas.append((axis, after.noise_floor_db[axis] - before.noise_floor_db[axis]))
    return deltas


def detect_convergence(
    before: FlightSnapshot,
    after: FlightSnapshot,
    *,
    comparable: bool,
) -> dict[str, Any]:
    """Map FPVPIDlab filter/flash convergence into GyroCore status vocabulary."""
    if not comparable:
        return {
            "status": "INCOMPARABLE",
            "details": [],
            "rollback_advisory": False,
            "message": "Flights are not comparable",
        }

    quality_ok = True
    for snap in (before, after):
        if snap.quality_score is not None and snap.quality_score < MIN_QUALITY_FOR_CONVERGED:
            quality_ok = False

    noise_deltas = _axis_noise_delta(before, after)
    details: list[dict[str, Any]] = []
    worst_noise = 0.0
    for axis, delta in noise_deltas:
        details.append(
            {
                "metric": f"{axis}_noise_floor_db",
                "delta": round(delta, 3),
                "unit": "dB",
                "direction": "improve" if delta < 0 else "regress" if delta > 0 else "unchanged",
            }
        )
        if delta > worst_noise or len(details) == 1:
            worst_noise = delta

    # Bandwidth deltas
    bw_deltas = []
    for axis in ("roll", "pitch", "yaw"):
        if axis in before.bandwidth_hz and axis in after.bandwidth_hz:
            d = after.bandwidth_hz[axis] - before.bandwidth_hz[axis]
            bw_deltas.append(abs(d))
            details.append(
                {
                    "metric": f"{axis}_bandwidth_hz",
                    "delta": round(d, 3),
                    "unit": "Hz",
                    "direction": "improve" if d > 0 else "regress" if d < 0 else "unchanged",
                }
            )
    max_bw = max(bw_deltas) if bw_deltas else 0.0

    if not noise_deltas and not bw_deltas:
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "details": details,
            "rollback_advisory": False,
            "message": "No overlapping metrics to compare",
        }

    # Regression on noise (positive delta = noisier)
    if worst_noise > FILTER_CONVERGENCE_DB:
        return {
            "status": "REGRESSED",
            "details": details,
            "rollback_advisory": True,
            "message": f"Noise floor regressed by {worst_noise:.1f} dB on worst axis",
        }

    # Resonance / saturation hard regress
    if (
        before.resonance_severity is not None
        and after.resonance_severity is not None
        and after.resonance_severity > before.resonance_severity + 0.15
    ):
        return {
            "status": "REGRESSED",
            "details": details,
            "rollback_advisory": True,
            "message": "Resonance severity increased",
        }

    abs_noise = abs(worst_noise)
    if quality_ok and abs_noise < FILTER_CONVERGENCE_DB and max_bw < FLASH_CONVERGENCE_BW_HZ:
        return {
            "status": "CONVERGED",
            "details": details,
            "rollback_advisory": False,
            "message": "Changes within measurement noise and quality gates satisfied",
        }

    if abs_noise < FILTER_DIMINISHING_DB and max_bw < FLASH_DIMINISHING_BW_HZ:
        # GyroCore maps diminishing_returns → CONVERGED only when quality ok; else IMPROVING
        status: ConvergenceStatus = "CONVERGED" if quality_ok else "IMPROVING"
        return {
            "status": status,
            "details": details,
            "rollback_advisory": False,
            "message": "Small deltas; diminishing returns region",
        }

    if worst_noise < 0 or (bw_deltas and after.bandwidth_hz and before.bandwidth_hz):
        # Improvement if noise down or bandwidth up on average
        improved = worst_noise < -FILTER_CONVERGENCE_DB
        if improved:
            return {
                "status": "IMPROVING",
                "details": details,
                "rollback_advisory": False,
                "message": "Meaningful improvement detected",
            }

    return {
        "status": "IMPROVING",
        "details": details,
        "rollback_advisory": False,
        "message": "Metrics changed beyond convergence thresholds",
    }
