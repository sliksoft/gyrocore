"""Centralized normalization rules for parity comparisons."""

from __future__ import annotations

import math
import re
from typing import Any

# Field comparison policies used by compare.py
POLICY_EXACT = "EXACT"
POLICY_NORMALIZED_EXACT = "NORMALIZED_EXACT"
POLICY_TOLERANCE = "TOLERANCE"
POLICY_IGNORED = "IGNORED_NONDETERMINISTIC"

# Default absolute/relative tolerances for TOLERANCE fields.
DEFAULT_ABS_TOL = 1e-6
DEFAULT_REL_TOL = 1e-4
SCORE_ABS_TOL = 0.51  # allow half-point rounding noise on integer-ish scores
METRIC_ABS_TOL = 1e-3
METRIC_REL_TOL = 1e-3
FREQ_ABS_TOL = 0.5  # Hz


_FIELD_POLICY: dict[str, str] = {
    # EXACT
    "analysis_status": POLICY_EXACT,
    "valid_log": POLICY_EXACT,
    "selected_flight_index": POLICY_EXACT,
    "selected_embedded_log_index": POLICY_EXACT,
    "flight_count": POLICY_EXACT,
    "flight_selection_mode": POLICY_EXACT,
    "quality_status": POLICY_EXACT,
    "quality_grade": POLICY_EXACT,
    "mechanical_safety.status": POLICY_EXACT,
    "mechanical_safety.mechanical_block": POLICY_EXACT,
    "mechanical_safety.mechanical_limited": POLICY_EXACT,
    "mechanical_safety.mechanical_caution": POLICY_EXACT,
    "mechanical_safety.mechanical_outcome": POLICY_EXACT,
    "tuning_output_safety.status": POLICY_EXACT,
    "tuning_output_safety.cli_actionable": POLICY_EXACT,
    "tuning_output_safety.cli_availability": POLICY_EXACT,
    "tuning_decision.mode": POLICY_EXACT,
    "tuning_decision.status": POLICY_EXACT,
    "ai_disabled": POLICY_EXACT,
    "oracle_entrypoint": POLICY_EXACT,
    # NORMALIZED_EXACT
    "problem_types": POLICY_NORMALIZED_EXACT,
    "problem_severities": POLICY_NORMALIZED_EXACT,
    "mechanical_safety.reasons": POLICY_NORMALIZED_EXACT,
    "mechanical_safety.blocking_reasons": POLICY_NORMALIZED_EXACT,
    "mechanical_safety.limited_reasons": POLICY_NORMALIZED_EXACT,
    "tuning_output_safety.blocking_reasons": POLICY_NORMALIZED_EXACT,
    "tuning_output_safety.hard_block_reasons": POLICY_NORMALIZED_EXACT,
    "tuning_output_safety.diagnostic_reasons": POLICY_NORMALIZED_EXACT,
    "tuning_output_safety.reasons": POLICY_NORMALIZED_EXACT,
    "authoritative_cli": POLICY_NORMALIZED_EXACT,
    "result_view.hero.tone": POLICY_NORMALIZED_EXACT,
    "result_view.hero.title": POLICY_NORMALIZED_EXACT,
    "pid_summary": POLICY_NORMALIZED_EXACT,
    "filter_summary": POLICY_NORMALIZED_EXACT,
    "tuning_mode": POLICY_NORMALIZED_EXACT,
    # TOLERANCE
    "quality_score": POLICY_TOLERANCE,
    "metrics": POLICY_TOLERANCE,
    "resonance": POLICY_TOLERANCE,
    "erpm": POLICY_TOLERANCE,
}


def field_policy(path: str) -> str:
    if path in _FIELD_POLICY:
        return _FIELD_POLICY[path]
    # Prefix matches for nested metric blobs.
    for key, policy in _FIELD_POLICY.items():
        if path == key or path.startswith(key + "."):
            return policy
    return POLICY_EXACT


def normalize_cli_text(value: Any) -> str:
    """Normalize authoritative CLI for stable string equality."""
    if value is None:
        return ""
    if isinstance(value, list):
        lines = [str(x) for x in value]
        text = "\n".join(lines)
    else:
        text = str(value)
    # Normalize newlines, trim trailing whitespace per line, drop empty lines.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines_out: list[str] = []
    for line in text.split("\n"):
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            lines_out.append(cleaned)
    return "\n".join(lines_out)


def normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out = sorted({str(x).strip() for x in value if str(x).strip()})
    return out


def normalize_for_compare(path: str, value: Any) -> Any:
    policy = field_policy(path)
    if policy == POLICY_IGNORED:
        return None
    if path == "authoritative_cli" or path.endswith(".cli"):
        return normalize_cli_text(value)
    if policy == POLICY_NORMALIZED_EXACT and (
        path.endswith("reasons")
        or path.endswith("problem_types")
        or "reasons" in path
        or path in {"problem_types", "problem_severities"}
    ):
        if isinstance(value, dict):
            return {str(k): normalize_string_list(v) if isinstance(v, list) else v for k, v in value.items()}
        return normalize_string_list(value)
    return value


def floats_close(
    a: float,
    b: float,
    *,
    abs_tol: float = DEFAULT_ABS_TOL,
    rel_tol: float = DEFAULT_REL_TOL,
) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    if not math.isfinite(a) or not math.isfinite(b):
        return a == b
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def tolerance_for_path(path: str) -> tuple[float, float]:
    if "quality_score" in path or path.endswith(".score"):
        return SCORE_ABS_TOL, DEFAULT_REL_TOL
    if "hz" in path.lower() or "freq" in path.lower() or "resonance" in path:
        return FREQ_ABS_TOL, METRIC_REL_TOL
    return METRIC_ABS_TOL, METRIC_REL_TOL
