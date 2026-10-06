# GyroCore WU4: adapted from AeroTuner backend/analysis/run_score_v1.py
"""Canonical run quality score (v1) for analyze API responses."""

from __future__ import annotations

import math
from typing import Any


def _clamp01(x: float) -> float:
    if not math.isfinite(x):
        return 0.5
    return max(0.0, min(1.0, float(x)))


def _pid_leaf_penalty(key: str, val: float) -> float:
    """Penalty 0..1 for a single PID-related numeric leaf (adjustment-style keys)."""
    k = str(key).lower()
    abs_v = abs(val)
    # Avoid matching the "d" in "adjust" inside p_adjust / d_adjust.
    if "ff_adjust" in k or k.endswith("ff") or k.startswith("ff_"):
        hi = 14.0
    elif "d_adjust" in k or k.startswith("d_"):
        hi = 12.0
    elif "p_adjust" in k or k.startswith("p_"):
        hi = 10.0
    elif "ff" in k:
        hi = 16.0
    elif k.startswith("d") or k.endswith("_d"):
        hi = 14.0
    elif "p" in k:
        hi = 12.0
    else:
        hi = 18.0
    if abs_v <= hi:
        return 0.0
    return min(1.0, (abs_v - hi) / 12.0)


def _pid_extremeness_penalty(pid_branch: Any, depth: int = 0) -> float:
    if depth > 8 or not isinstance(pid_branch, dict):
        return 0.0
    worst = 0.0
    for k, v in pid_branch.items():
        if isinstance(v, (int, float)) and isinstance(k, str):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fv):
                worst = max(worst, _pid_leaf_penalty(k, fv))
        elif isinstance(v, dict):
            worst = max(worst, _pid_extremeness_penalty(v, depth + 1))
    return worst


def _safe_float(x: Any) -> float | None:
    try:
        f = float(x)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _single_filter_block_penalty(filters: dict[str, Any]) -> float:
    """Penalty 0..1 for one filters dict (LPF/notch consistency)."""
    p = 0.0
    l1 = _safe_float(filters.get("gyro_lpf1_static_hz"))
    l2 = _safe_float(filters.get("gyro_lpf2_static_hz"))
    nh = _safe_float(filters.get("gyro_notch_hz"))
    nc = _safe_float(filters.get("gyro_notch_cutoff"))

    if l1 is not None:
        if l1 < 90.0:
            p = max(p, min(1.0, (90.0 - l1) / 120.0))
        if l1 > 480.0:
            p = max(p, min(1.0, (l1 - 480.0) / 200.0))
    if l1 is not None and l2 is not None and l2 > l1 + 1.0:
        p = max(p, 0.45)
    if nh is not None and nh > 1.0:
        if nh < 35.0 or nh > 680.0:
            p = max(p, 0.5)
        if nc is not None and nc >= nh:
            p = max(p, 0.3)
    return min(1.0, p)


def _filter_instability_penalty(tuning: dict[str, Any]) -> float:
    blocks: list[dict[str, Any]] = []
    f = tuning.get("filters")
    if isinstance(f, dict):
        blocks.append(f)
    for ax in ("roll", "pitch", "yaw"):
        blk = tuning.get(ax)
        if isinstance(blk, dict) and isinstance(blk.get("filters"), dict):
            blocks.append(blk["filters"])
    if not blocks:
        return 0.0
    return max(_single_filter_block_penalty(b) for b in blocks)


def _tuning_quality_component(tuning: Any) -> float:
    """
    0..1 quality from tuning package; 1.0 when absent or benign.
    Penalizes extreme PID suggestions and unstable filter configs.
    """
    if not isinstance(tuning, dict) or not tuning:
        return 1.0
    pid_branch = tuning.get("pid")
    p_pid = _pid_extremeness_penalty(pid_branch) if isinstance(pid_branch, dict) else 0.0
    p_filt = _filter_instability_penalty(tuning)
    penalty = _clamp01(0.5 * (p_pid + p_filt))
    return _clamp01(1.0 - penalty)


def score_to_grade(score: int) -> str:
    """Map 0–100 run score to a letter band (aligned with UI expectations)."""
    s = int(score)
    if s >= 80:
        return "A"
    if s >= 65:
        return "B"
    if s >= 50:
        return "C"
    if s >= 30:
        return "D"
    return "E"


def calculate_run_score_v1(analysis: dict) -> int:
    """
    Unified 0–100 integer score from noise, oscillation, tracking, propwash, and optional tuning.

    Expected inputs (any subset); missing pieces use neutral 0.5:
    - ``noise_score``, ``oscillation_score``, ``tracking_score``, ``propwash_score``: 0–1
    - Or ``metrics`` (``metrics_engine`` shape) plus optional ``oscillation_strength_0_100``
      (0–100, same as ``advanced.oscillations``).
    - Optional ``tuning``: v2 tuning package (``pid``, ``filters``, per-axis ``filters``);
      extreme PID leaves and inconsistent filters reduce the score.
    """

    a: dict[str, Any] = analysis if isinstance(analysis, dict) else {}

    noise_score = a.get("noise_score")
    if noise_score is None:
        m = a.get("metrics")
        if isinstance(m, dict):
            nz = m.get("noise")
            if isinstance(nz, dict):
                try:
                    clean = max(0.0, min(100.0, float(nz.get("value", 0.0) or 0.0)))
                    noise_score = (100.0 - clean) / 100.0
                except (TypeError, ValueError):
                    noise_score = None
    if noise_score is None:
        noise_score = 0.5

    oscillation_score = a.get("oscillation_score")
    if oscillation_score is None:
        o100 = a.get("oscillation_strength_0_100")
        if o100 is None and isinstance(a.get("advanced"), dict):
            adv = a["advanced"]
            o100 = adv.get("oscillations") if isinstance(adv, dict) else None
        if o100 is not None:
            try:
                oscillation_score = max(0.0, min(1.0, float(o100) / 100.0))
            except (TypeError, ValueError):
                oscillation_score = None
    if oscillation_score is None:
        oscillation_score = 0.5

    tracking_score = a.get("tracking_score")
    if tracking_score is None:
        m = a.get("metrics")
        if isinstance(m, dict):
            tr = m.get("tracking")
            if isinstance(tr, dict) and tr.get("score") is not None:
                try:
                    tracking_score = max(0.0, min(1.0, float(tr["score"]) / 100.0))
                except (TypeError, ValueError):
                    tracking_score = None
    if tracking_score is None:
        tracking_score = 0.5

    # Propwash penalty input (audit P1-D — preserved for regression stability):
    # When ``propwash_score`` is absent, ``metrics.propwash["confidence"]`` is used.
    # That value is detection certainty that propwash exists (0–1), not severity/level.
    # Higher confidence increases the propwash penalty term ``(1 - propwash_score) * 0.1``.
    # ``propwash["level"]`` is ignored here; do not treat confidence as severity.
    propwash_score = a.get("propwash_score")
    if propwash_score is None:
        m = a.get("metrics")
        if isinstance(m, dict):
            pw = m.get("propwash")
            if isinstance(pw, dict) and pw.get("confidence") is not None:
                try:
                    propwash_score = max(0.0, min(1.0, float(pw["confidence"])))
                except (TypeError, ValueError):
                    propwash_score = None
    if propwash_score is None:
        propwash_score = 0.5

    noise_score = _clamp01(float(noise_score))
    oscillation_score = _clamp01(float(oscillation_score))
    tracking_score = _clamp01(float(tracking_score))
    propwash_score = _clamp01(float(propwash_score))

    analysis_score = (
        (1.0 - noise_score) * 0.3
        + (1.0 - oscillation_score) * 0.3
        + tracking_score * 0.3
        + (1.0 - propwash_score) * 0.1
    )
    analysis_score = max(0.0, min(1.0, analysis_score))
    if not math.isfinite(analysis_score):
        analysis_score = 0.5

    tuning_q = _tuning_quality_component(a.get("tuning"))
    # Blend: analysis primary; tuning modulates up to 30%.
    blended = 0.7 * analysis_score + 0.3 * tuning_q
    score = max(0.0, min(1.0, blended))
    if not math.isfinite(score):
        score = 0.5
    score_i = int(round(score * 100))
    # Score floor (audit P3-K — preserved for regression stability):
    # Run score never drops below 10 even when blended quality is extremely poor.
    score_i = max(10, score_i)
    score_i = min(100, score_i)
    return score_i
