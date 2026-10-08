"""Flight comparability matching — FPVPIDlab VerificationMatcher ideas + GyroCore gates."""

from __future__ import annotations

from .constants import (
    MIN_THROTTLE_OVERLAP,
    MOTOR_HARMONIC_TOLERANCE_RATIO,
    PEAK_MATCH_TOLERANCE_MIN_HZ,
    REQUIRE_SAME_BETAFLIGHT_MAJOR,
    SIMILARITY_ACCEPT_THRESHOLD,
    SIMILARITY_REJECT_THRESHOLD,
)
from .models import FlightSnapshot


def _bf_major(version: str | None) -> str | None:
    if not version:
        return None
    # e.g. "4.5.1" or "2026.6.2"
    parts = str(version).strip().split(".")
    return parts[0] if parts else None


def compute_throttle_overlap(a: FlightSnapshot, b: FlightSnapshot) -> float:
    if a.throttle_min is None or a.throttle_max is None or b.throttle_min is None or b.throttle_max is None:
        return 0.0
    ref_range = a.throttle_max - a.throttle_min
    if ref_range <= 0:
        return 0.0
    overlap = min(a.throttle_max, b.throttle_max) - max(a.throttle_min, b.throttle_min)
    if overlap <= 0:
        return 0.0
    return min(1.0, overlap / ref_range)


def match_peaks(ref_peaks: list[float], ver_peaks: list[float]) -> float:
    if not ref_peaks:
        return 1.0
    if not ver_peaks:
        return 1.0  # peaks filtered — not a mismatch (FPVPIDlab policy)
    matched = 0
    unmatched = 0
    for rp in ref_peaks:
        tol = max(PEAK_MATCH_TOLERANCE_MIN_HZ, abs(rp) * MOTOR_HARMONIC_TOLERANCE_RATIO)
        closest = min((abs(rp - vp) for vp in ver_peaks), default=float("inf"))
        if closest <= tol:
            matched += 1
        elif closest > tol * 3:
            pass  # filtered
        else:
            unmatched += 1
    denom = matched + unmatched
    return 1.0 if denom == 0 else matched / denom


def assess_comparability(before: FlightSnapshot, after: FlightSnapshot) -> dict:
    reasons: list[str] = []
    score_parts: list[tuple[str, float, float]] = []

    # Identity gates (GyroCore-specific)
    if before.craft_name and after.craft_name and before.craft_name != after.craft_name:
        reasons.append("craft_mismatch")
    if before.target and after.target and before.target != after.target:
        reasons.append("target_mismatch")
    if before.pid_profile is not None and after.pid_profile is not None and before.pid_profile != after.pid_profile:
        reasons.append("pid_profile_mismatch")
    if REQUIRE_SAME_BETAFLIGHT_MAJOR:
        ma, mb = _bf_major(before.betaflight_version), _bf_major(after.betaflight_version)
        if ma and mb and ma != mb:
            reasons.append("betaflight_major_mismatch")

    if before.sample_rate_hz and after.sample_rate_hz:
        ratio = min(before.sample_rate_hz, after.sample_rate_hz) / max(
            before.sample_rate_hz, after.sample_rate_hz
        )
        rate_score = ratio * 100
        score_parts.append(("sample_rate", rate_score, 0.15))
        if ratio < 0.8:
            reasons.append("sample_rate_incompatible")
    else:
        score_parts.append(("sample_rate", 50.0, 0.15))

    thr_overlap = compute_throttle_overlap(before, after)
    score_parts.append(("throttle_overlap", thr_overlap * 100, 0.35))
    if thr_overlap < MIN_THROTTLE_OVERLAP and before.throttle_min is not None:
        reasons.append("throttle_coverage_insufficient")

    peak_ratio = match_peaks(before.peaks_hz, after.peaks_hz)
    score_parts.append(("peak_match", peak_ratio * 100, 0.35))

    # Quality presence
    if before.quality_score is not None and after.quality_score is not None:
        q = min(before.quality_score, after.quality_score)
        score_parts.append(("quality", max(0.0, min(100.0, q * 100)), 0.15))
    else:
        score_parts.append(("quality", 50.0, 0.15))

    overall = sum(s * w for _, s, w in score_parts)
    hard_fail = any(
        r in reasons
        for r in ("craft_mismatch", "target_mismatch", "betaflight_major_mismatch", "sample_rate_incompatible")
    )
    if hard_fail:
        comparable = False
        tier = "poor"
    elif overall >= SIMILARITY_ACCEPT_THRESHOLD:
        comparable = True
        tier = "good"
    elif overall >= SIMILARITY_REJECT_THRESHOLD:
        comparable = True
        tier = "marginal"
        reasons.append("marginal_similarity")
    else:
        comparable = False
        tier = "poor"
        reasons.append("verification_rejected")

    return {
        "comparable": comparable,
        "score": round(overall, 1),
        "tier": tier,
        "reasons": reasons,
        "sub_scores": [{"name": n, "score": round(s, 1), "weight": w} for n, s, w in score_parts],
    }
