"""Desync-risk evidence helper (extracted from tuning_safety_policy; analysis-only)."""
from __future__ import annotations

from typing import Any, Mapping

def desync_risk_active(analysis: Mapping[str, Any] | None) -> bool:
    """True when log/motor diagnostics flag desync risk (same guardrails as harsh motor stress)."""
    if not isinstance(analysis, Mapping):
        return False
    if analysis.get("has_desync_risk") is True:
        return True
    md = analysis.get("motor_diagnostics")
    if isinstance(md, Mapping) and md.get("has_desync_risk") is True:
        return True
    probs = analysis.get("problems")
    rows: list[Any] = []
    if isinstance(probs, list):
        rows = probs
    elif isinstance(probs, dict):
        inner = probs.get("problems")
        if isinstance(inner, list):
            rows = inner
    for row in rows:
        if not isinstance(row, dict):
            continue
        t = str(row.get("type", "")).strip().lower()
        if "desync" in t:
            return True
    return False
