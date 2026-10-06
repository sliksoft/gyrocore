# GyroCore WU4: adapted from AeroTuner backend/analysis/grade_hardware_limits.py
"""
Hardware / motor dominance for public grades and scores (analyze API only).

Does not affect tuning math — only post-processes ``run_score`` / letter grade so UI
and logs are not misleading when ``motor_issue`` or desync risk is present.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from gyrocore.analysis.run_score_v1 import score_to_grade
from gyrocore.analysis._support.severity_coercion import coerce_problem_severity
from gyrocore.analysis._support.desync import desync_risk_active

_LETTER_RANK = {"A": 5, "B": 4, "C": 3, "D": 2, "E": 1}
_INV_RANK = {5: "A", 4: "B", 3: "C", 2: "D", 1: "E"}


def _letter_rank(letter: str) -> int:
    s = str(letter or "D").strip().upper()[:1]
    return int(_LETTER_RANK.get(s, 2))


def _rank_to_letter(r: int) -> str:
    r = max(1, min(5, int(r)))
    return _INV_RANK.get(r, "C")


def _severity_to_float(value: Any) -> float:
    """Convert a severity value to float.

    Accepts numeric values (legacy fixture shape) and production string labels.
    Unknown or missing values map to low / 0.0.
    """
    return coerce_problem_severity(value, 0.0)


def motor_issue_max_severity_from_response(response: Mapping[str, Any] | None) -> float:
    """Max ``severity`` among ``motor_issue`` rows in ``response['problems']``.

    Handles both numeric severity values (legacy test fixtures) and the string
    labels ``"high"`` / ``"medium"`` / ``"low"`` produced by
    ``problem_detection_engine._severity_from_score``.
    """
    if not isinstance(response, Mapping):
        return 0.0
    prob = response.get("problems")
    if not isinstance(prob, dict):
        return 0.0
    rows = prob.get("problems")
    if not isinstance(rows, list):
        return 0.0
    best = 0.0
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("type", "")).strip().lower() != "motor_issue":
            continue
        s = _severity_to_float(row.get("severity"))
        if s is not None and s > best:
            best = s
    return float(best)


def _analysis_for_desync(response: Mapping[str, Any]) -> dict[str, Any]:
    ana = response.get("analysis") if isinstance(response.get("analysis"), dict) else {}
    out: dict[str, Any] = dict(ana)
    pb = response.get("problems")
    if isinstance(pb, dict):
        out["problems"] = pb
    return out


def apply_hardware_limits_to_response(response: dict[str, Any]) -> None:
    """
    Cap ``run_score`` / grades when motor issues or desync dominate.

    Rules:
    - ``motor_issue`` max severity >= 0.4: score capped to 70; letter not better than C.
    - Desync risk: score capped to 62 (stays in C band vs run_score_v1); letter not
      better than C; ``meta.grade_display`` may be ``C-`` for UI.
    """
    if not isinstance(response, dict):
        return

    sev = motor_issue_max_severity_from_response(response)
    motor_cap = sev >= 0.4
    desync = desync_risk_active(_analysis_for_desync(response))

    if not motor_cap and not desync:
        return

    try:
        rs = int(round(float(response.get("run_score") or 0)))
    except (TypeError, ValueError):
        rs = 0
    score_before_cap = max(10, min(100, rs))
    rs = score_before_cap

    score_cap = 100
    if motor_cap:
        score_cap = min(score_cap, 70)
    if desync:
        score_cap = min(score_cap, 62)
    new_score = min(rs, score_cap)

    g_run = score_to_grade(new_score)
    g_top = str(response.get("grade") or g_run).strip().upper()[:1]
    ceiling = 3  # C
    merged = min(_letter_rank(g_run), _letter_rank(g_top), ceiling)
    new_grade = _rank_to_letter(merged)

    response["run_score"] = int(new_score)
    meta = response.get("meta")
    if isinstance(meta, dict):
        meta["run_score"] = int(new_score)
        if motor_cap:
            meta["hardware_tune_limited"] = True
            meta["motor_issue_max_severity"] = float(sev)
        if desync:
            meta["hardware_tune_warning"] = True
            meta["grade_display"] = "C-"
        elif motor_cap:
            meta.pop("grade_display", None)

    summ = response.get("summary")
    if isinstance(summ, dict):
        summ["score"] = int(new_score)
        summ["grade"] = new_grade

    response["grade"] = new_grade

    for key in ("quality",):
        q = response.get(key)
        if isinstance(q, dict):
            q["score"] = float(new_score)
            q["grade"] = new_grade

    if isinstance(meta, dict):
        for mk in ("quality", "quality_v2"):
            mq = meta.get(mk)
            if isinstance(mq, dict):
                mq["score"] = float(new_score)
                mq["grade"] = new_grade

    ana = response.get("analysis")
    if isinstance(ana, dict):
        aq = ana.get("quality")
        if isinstance(aq, dict):
            aq["score"] = float(new_score)
            aq["grade"] = new_grade

    response["_hardware_grade_limits_applied"] = copy.deepcopy(
        {
            "motor_issue_severity": float(sev),
            "motor_cap": bool(motor_cap),
            "desync_risk": bool(desync),
            "score_before": int(score_before_cap),
            "score_after": int(new_score),
            "grade_after": new_grade,
        }
    )
