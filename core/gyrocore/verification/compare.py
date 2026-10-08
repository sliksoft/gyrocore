"""Public entry: ``compare_tuning_flights``."""

from __future__ import annotations

from typing import Any, Mapping

from .constants import FILTER_CONVERGENCE_DB, FLASH_CONVERGENCE_BW_HZ, PROVENANCE
from .convergence import detect_convergence
from .matching import assess_comparability
from .models import FlightSnapshot, VerificationResult


def flight_snapshot_from_mapping(data: Mapping[str, Any]) -> FlightSnapshot:
    """Build a snapshot from a loose dict (tests / desktop / Core evidence)."""
    noise = data.get("noise_floor_db") or {}
    if not isinstance(noise, Mapping):
        noise = {}
    bw = data.get("bandwidth_hz") or {}
    if not isinstance(bw, Mapping):
        bw = {}
    coh = data.get("mean_coherence") or {}
    if not isinstance(coh, Mapping):
        coh = {}
    peaks = data.get("peaks_hz") or []
    if not isinstance(peaks, list):
        peaks = []
    return FlightSnapshot(
        craft_name=data.get("craft_name") or data.get("craft"),
        target=data.get("target"),
        betaflight_version=data.get("betaflight_version"),
        pid_profile=data.get("pid_profile"),
        sample_rate_hz=_f(data.get("sample_rate_hz")),
        quality_score=_f(data.get("quality_score")),
        noise_floor_db={str(k): float(v) for k, v in noise.items() if v is not None},
        resonance_severity=_f(data.get("resonance_severity")),
        saturation_fraction=_f(data.get("saturation_fraction")),
        system_id_quality=data.get("system_id_quality"),
        bandwidth_hz={str(k): float(v) for k, v in bw.items() if v is not None},
        mean_coherence={str(k): float(v) for k, v in coh.items() if v is not None},
        throttle_min=_f(data.get("throttle_min")),
        throttle_max=_f(data.get("throttle_max")),
        tune_values={str(k): float(v) for k, v in (data.get("tune_values") or {}).items()},
        peaks_hz=[float(p) for p in peaks],
    )


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def compare_tuning_flights(
    before: FlightSnapshot | Mapping[str, Any],
    after: FlightSnapshot | Mapping[str, Any],
) -> VerificationResult:
    """Compare two GyroCore measurement snapshots. Never executes rollback."""
    b = before if isinstance(before, FlightSnapshot) else flight_snapshot_from_mapping(before)
    a = after if isinstance(after, FlightSnapshot) else flight_snapshot_from_mapping(after)

    match = assess_comparability(b, a)
    conv = detect_convergence(b, a, comparable=bool(match["comparable"]))

    improved: list[str] = []
    degraded: list[str] = []
    unchanged: list[str] = []
    for detail in conv.get("details") or []:
        name = str(detail.get("metric"))
        direction = detail.get("direction")
        if direction == "improve":
            improved.append(name)
        elif direction == "regress":
            degraded.append(name)
        else:
            unchanged.append(name)

    # Unchanged within measurement noise (explicit)
    for axis in ("roll", "pitch", "yaw"):
        if axis in b.noise_floor_db and axis in a.noise_floor_db:
            d = abs(a.noise_floor_db[axis] - b.noise_floor_db[axis])
            metric = f"{axis}_noise_floor_db"
            if d < FILTER_CONVERGENCE_DB and metric not in unchanged and metric not in improved and metric not in degraded:
                unchanged.append(metric)

    status = conv["status"]
    confidence = "high" if match["tier"] == "good" and match["comparable"] else "medium" if match["comparable"] else "low"

    return VerificationResult(
        comparable=bool(match["comparable"]),
        reasons=list(match["reasons"]) + ([conv["message"]] if conv.get("message") else []),
        improved_metrics=improved,
        degraded_metrics=degraded,
        unchanged_metrics=unchanged,
        confidence=confidence,
        overall_status=status,
        evidence={
            "similarity": match,
            "convergence": conv,
            "thresholds": {
                "filter_convergence_db": FILTER_CONVERGENCE_DB,
                "flash_convergence_bw_hz": FLASH_CONVERGENCE_BW_HZ,
                "source": "FPVPIDlab+GyroCore",
            },
        },
        rollback_advisory=bool(conv.get("rollback_advisory")),
        similarity_score=match.get("score"),
        provenance=dict(PROVENANCE),
        actionable=False,
    )
