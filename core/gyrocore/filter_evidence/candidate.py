"""Non-actionable filter candidate heuristics (FPVPIDlab FilterRecommender subset)."""

from __future__ import annotations

from typing import Any, Mapping

from .constants import (
    DTERM_LPF1_MAX_HZ,
    DTERM_LPF1_MIN_HZ,
    DYNAMIC_LOWPASS_MIN_BANDS,
    DYNAMIC_LOWPASS_MIN_CORRELATION,
    DYNAMIC_LOWPASS_NOISE_INCREASE_DB,
    GYRO_LPF1_MAX_HZ,
    GYRO_LPF1_MIN_HZ,
    NOISE_FLOOR_VERY_CLEAN_DB,
    NOISE_FLOOR_VERY_NOISY_DB,
    NOISE_TARGET_DEADZONE_HZ,
    PROPWASH_FLOOR_BYPASS_DB,
    PROPWASH_GYRO_LPF1_FLOOR_HZ,
)
from .models import FilterCandidate


def compute_noise_based_target(worst_noise_floor_db: float, min_hz: float, max_hz: float) -> int:
    """EXACT_PARITY with FPVPIDlab ``computeNoiseBasedTarget``."""
    t = (worst_noise_floor_db - NOISE_FLOOR_VERY_NOISY_DB) / (
        NOISE_FLOOR_VERY_CLEAN_DB - NOISE_FLOOR_VERY_NOISY_DB
    )
    target = min_hz + t * (max_hz - min_hz)
    return int(round(max(min_hz, min(max_hz, target))))


def analyze_dynamic_lowpass_evidence(
    band_noise: list[dict[str, float]],
) -> dict[str, Any] | None:
    """Port of ``analyzeDynamicLowpass`` — evidence only, no apply path."""
    if len(band_noise) < DYNAMIC_LOWPASS_MIN_BANDS:
        return None
    sorted_bands = sorted(band_noise, key=lambda b: b["throttle_mid"])
    low = sorted_bands[0]["noise_floor_db"]
    high = sorted_bands[-1]["noise_floor_db"]
    delta = high - low
    xs = [b["throttle_mid"] for b in band_noise]
    ys = [b["noise_floor_db"] for b in band_noise]
    corr = _pearson(xs, ys)
    recommended = delta >= DYNAMIC_LOWPASS_NOISE_INCREASE_DB and corr >= DYNAMIC_LOWPASS_MIN_CORRELATION
    return {
        "recommended": recommended,
        "noise_increase_delta_db": round(delta, 1),
        "throttle_noise_correlation": round(corr, 2),
        "bands_analyzed": len(band_noise),
        "summary": (
            f"Noise increases {delta:.0f} dB with throttle (r={corr:.2f}). Dynamic LPF evidence."
            if recommended
            else f"Noise relatively consistent across throttle ({delta:.0f} dB). Static LPF evidence."
        ),
    }


def build_filter_candidate(
    *,
    worst_noise_floor_db: float | None,
    current_settings: Mapping[str, Any],
    dynamic_evidence: dict[str, Any] | None,
) -> FilterCandidate:
    if worst_noise_floor_db is None:
        return FilterCandidate(
            actionable=False,
            rationale="insufficient noise-floor evidence for candidate",
        )
    target_gyro = compute_noise_based_target(worst_noise_floor_db, GYRO_LPF1_MIN_HZ, GYRO_LPF1_MAX_HZ)
    target_dterm = compute_noise_based_target(worst_noise_floor_db, DTERM_LPF1_MIN_HZ, DTERM_LPF1_MAX_HZ)
    note = ""
    if target_gyro < PROPWASH_GYRO_LPF1_FLOOR_HZ and worst_noise_floor_db <= PROPWASH_FLOOR_BYPASS_DB:
        target_gyro = PROPWASH_GYRO_LPF1_FLOOR_HZ
        note = " raised to propwash floor"
    cur_gyro = float(current_settings.get("gyro_lpf1_static_hz") or 0)
    cur_dterm = float(current_settings.get("dterm_lpf1_static_hz") or 0)
    settings: dict[str, float] = {}
    if cur_gyro > 0 and abs(target_gyro - cur_gyro) > NOISE_TARGET_DEADZONE_HZ:
        settings["gyro_lpf1_static_hz"] = float(target_gyro)
    if cur_dterm > 0 and abs(target_dterm - cur_dterm) > NOISE_TARGET_DEADZONE_HZ:
        settings["dterm_lpf1_static_hz"] = float(target_dterm)
    dyn = None
    if dynamic_evidence is not None:
        dyn = bool(dynamic_evidence.get("recommended"))
    return FilterCandidate(
        actionable=False,
        gyro_lpf1_hz=float(target_gyro),
        dterm_lpf1_hz=float(target_dterm),
        dynamic_lowpass_recommended=dyn,
        rationale=f"noise-based non-actionable candidate{note}",
        settings=settings,
    )


def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    denx = sum((x - mx) ** 2 for x in xs) ** 0.5
    deny = sum((y - my) ** 2 for y in ys) ** 0.5
    if denx == 0 or deny == 0:
        return 0.0
    return num / (denx * deny)
