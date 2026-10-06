# GyroCore WU4
"""
Central hardware compatibility matrix used for backend-side validation.

This module is intentionally non-blocking for safety gates: compatibility issues
decrease confidence and constrain aggressiveness, but never hard-block by themselves.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping

HardwareConfidenceImpact = str
HardwareCompatibilityStatus = str
SetupFamily = str

_CLASS_TO_FAMILY: dict[str, SetupFamily] = {
    "whoop_1s": "tiny_whoop",
    "whoop_2s": "small_whoop",
    "micro_2_5_3_5": "micro_toothpick",
    "freestyle_5": "five_inch",
    "racing_5": "five_inch",
    "long_range_7": "long_range",
    "long_range_10_large": "large_long_range",
    "cine_heavy": "cine_heavy",
}

_FAMILY_PROFILES: dict[SetupFamily, dict[str, tuple[float, float]]] = {
    "tiny_whoop": {
        "prop": (1.1, 1.8),
        "cells": (1, 1),
        "stator": (6, 10),
        "weight": (18, 85),
    },
    "small_whoop": {
        "prop": (1.2, 2.2),
        "cells": (2, 2),
        "stator": (7, 12),
        "weight": (30, 150),
    },
    "micro_toothpick": {
        "prop": (2.4, 3.7),
        "cells": (2, 6),
        "stator": (11, 18),
        "weight": (80, 420),
    },
    "small_freestyle": {
        "prop": (3.8, 4.6),
        "cells": (3, 6),
        "stator": (15, 22),
        "weight": (180, 650),
    },
    "five_inch": {
        "prop": (4.8, 5.3),
        "cells": (4, 6),
        "stator": (21, 25),
        "weight": (280, 950),
    },
    "long_range": {
        "prop": (6.7, 7.4),
        "cells": (4, 6),
        "stator": (24, 30),
        "weight": (500, 1900),
    },
    "large_long_range": {
        "prop": (9.0, 11.5),
        "cells": (4, 12),
        "stator": (28, 34),
        "weight": (850, 3800),
    },
    "cine_heavy": {
        "prop": (2.5, 10.5),
        "cells": (3, 12),
        "stator": (14, 34),
        "weight": (150, 5000),
    },
    "unknown_other": {
        "prop": (1, 12),
        "cells": (1, 12),
        "stator": (6, 36),
        "weight": (10, 6000),
    },
}


def _impact_rank(value: HardwareConfidenceImpact) -> int:
    return {"none": 0, "low": 1, "medium": 2, "high": 3}.get(str(value), 0)


def _max_impact(a: HardwareConfidenceImpact, b: HardwareConfidenceImpact) -> HardwareConfidenceImpact:
    return b if _impact_rank(b) > _impact_rank(a) else a


def _safe_int(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        n = int(float(raw))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _safe_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    return n if math.isfinite(n) else None


def _parse_frame_inches(raw: Any) -> float | None:
    if not isinstance(raw, str):
        return None
    txt = raw.strip().lower()
    if not txt:
        return None
    if "2-3" in txt or "micro" in txt:
        return 2.7
    if "65mm" in txt:
        return 65.0 / 25.4
    if "75mm" in txt:
        return 75.0 / 25.4
    if "85mm" in txt:
        return 85.0 / 25.4
    if "95mm" in txt:
        return 95.0 / 25.4
    if "10+" in txt or "12+" in txt:
        return 10.0
    m = re.match(r"^(\d{2,3})\s*mm$", txt)
    if m:
        mm = _safe_float(m.group(1))
        return (mm / 25.4) if mm and mm > 0 else None
    m = re.match(r'^(\d+(?:\.\d+)?)\s*"', txt)
    if m:
        inch = _safe_float(m.group(1))
        return inch if inch and inch > 0 else None
    return None


def _parse_motor_stator_diameter(raw: Any) -> int | None:
    if not isinstance(raw, str):
        return None
    m = re.match(r"^(\d{2})\d{2}$", raw.strip())
    if not m:
        return None
    n = _safe_int(m.group(1))
    if n is None or n < 6 or n > 40:
        return None
    return n


def _issue(
    code: str,
    message: str,
    *,
    severity: str,
    affected_fields: list[str],
    confidence_impact: HardwareConfidenceImpact,
    confirmation_required: bool,
    suggestion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = {
        "code": code,
        "message": message,
        "severity": severity,
        "affected_fields": list(affected_fields),
        "confidence_impact": confidence_impact,
        "confirmation_required": bool(confirmation_required),
    }
    if isinstance(suggestion, dict):
        out["suggestion"] = dict(suggestion)
    return out


_SELECTED_CLASS_BUMP = 0.5
_FRAME_CONTRADICTION_BOOST = 8.0
_SELECTED_TIE_MARGIN = 2.0
_SMALL_FRAME_FAMILIES = frozenset({"tiny_whoop", "small_whoop", "micro_toothpick"})
_LARGE_FRAME_FAMILIES = frozenset({"five_inch", "long_range", "large_long_range"})


def _frame_setup_family(frame_inches: float) -> SetupFamily:
    if frame_inches <= 2.2:
        return "tiny_whoop"
    if frame_inches <= 3.2:
        return "small_whoop"
    if frame_inches <= 3.8:
        return "micro_toothpick"
    if frame_inches <= 4.6:
        return "small_freestyle"
    if frame_inches <= 5.5:
        return "five_inch"
    if frame_inches <= 8.0:
        return "long_range"
    return "large_long_range"


def _frame_contradicts_selected(frame_inches: float | None, selected_family: SetupFamily | None) -> bool:
    if frame_inches is None or not selected_family:
        return False
    frame_family = _frame_setup_family(frame_inches)
    if frame_inches >= 4.6 and selected_family in _SMALL_FRAME_FAMILIES:
        return frame_family != selected_family
    if frame_inches <= 3.8 and selected_family in _LARGE_FRAME_FAMILIES:
        return frame_family != selected_family
    if frame_inches >= 6.7 and selected_family in {
        "tiny_whoop",
        "small_whoop",
        "micro_toothpick",
        "five_inch",
        "small_freestyle",
    }:
        return frame_family != selected_family
    return False


def _fits_family_profile(
    family: SetupFamily,
    *,
    prop_size: float | None,
    cells: int | None,
    stator_mm: int | None,
    weight_g: float | None,
) -> bool:
    profile = _FAMILY_PROFILES.get(family)
    if not profile:
        return False
    if prop_size is not None:
        lo, hi = profile["prop"]
        if prop_size < lo or prop_size > hi:
            return False
    if cells is not None:
        lo, hi = profile["cells"]
        if cells < lo or cells > hi:
            return False
    if stator_mm is not None:
        lo, hi = profile["stator"]
        if stator_mm < lo or stator_mm > hi:
            return False
    if weight_g is not None:
        lo, hi = profile["weight"]
        if weight_g < lo or weight_g > hi:
            return False
    return True


def _resolve_inferred_family(
    scores: dict[str, float],
    *,
    selected_family: SetupFamily | None,
    frame_inches: float | None,
    prop_size: float | None,
    cells: int | None,
    stator_mm: int | None,
    weight_g: float | None,
) -> SetupFamily:
    if not scores:
        return "unknown_other"

    working = dict(scores)
    if (
        selected_family == "cine_heavy"
        and _fits_family_profile(
            "cine_heavy",
            prop_size=prop_size,
            cells=cells,
            stator_mm=stator_mm,
            weight_g=weight_g,
        )
    ):
        return "cine_heavy"

    if frame_inches is not None and selected_family and _frame_contradicts_selected(
        frame_inches, selected_family
    ):
        frame_family = _frame_setup_family(frame_inches)
        working[frame_family] = float(
            working.get(frame_family, 0.0) + _FRAME_CONTRADICTION_BOOST
        )

    winner_score = max(working.values())
    if (
        selected_family
        and selected_family in working
        and _fits_family_profile(
            selected_family,
            prop_size=prop_size,
            cells=cells,
            stator_mm=stator_mm,
            weight_g=weight_g,
        )
        and working[selected_family] >= winner_score - _SELECTED_TIE_MARGIN
    ):
        return selected_family

    return str(max(working.items(), key=lambda item: item[1])[0])


def _best_matching_class(inferred_family: SetupFamily, style: str | None) -> str | None:
    if inferred_family == "tiny_whoop":
        return "whoop_1s"
    if inferred_family == "small_whoop":
        return "whoop_2s"
    if inferred_family in {"micro_toothpick", "small_freestyle"}:
        return "micro_2_5_3_5"
    if inferred_family == "five_inch":
        st = str(style or "").strip().lower()
        return "racing_5" if "race" in st else "freestyle_5"
    if inferred_family == "long_range":
        return "long_range_7"
    if inferred_family == "large_long_range":
        return "long_range_10_large"
    if inferred_family == "cine_heavy":
        return "cine_heavy"
    return None


def _inferred_family(
    *,
    hardware_class: str | None,
    frame_inches: float | None,
    cells: int | None,
    prop_size: float | None,
    stator_mm: int | None,
    kv: int | None,
    weight_g: float | None,
) -> tuple[SetupFamily, dict[str, float], list[str]]:
    scores: dict[str, float] = {}
    evidence: list[str] = []

    def _bump(family: str, points: float, why: str | None = None) -> None:
        scores[family] = float(scores.get(family, 0.0) + points)
        if why:
            evidence.append(f"{family}:{why}")

    selected_family = _CLASS_TO_FAMILY.get(str(hardware_class or "").strip().lower())
    if selected_family and not _frame_contradicts_selected(frame_inches, selected_family):
        _bump(selected_family, _SELECTED_CLASS_BUMP, "selected_class")

    for fam, profile in _FAMILY_PROFILES.items():
        if fam == "unknown_other":
            continue
        if prop_size is not None:
            lo, hi = profile["prop"]
            if lo <= prop_size <= hi:
                _bump(fam, 4.0, "prop")
        if cells is not None:
            lo, hi = profile["cells"]
            if lo <= cells <= hi:
                _bump(fam, 3.0, "cells")
        if stator_mm is not None:
            lo, hi = profile["stator"]
            if lo <= stator_mm <= hi:
                _bump(fam, 4.0, "stator")
        if weight_g is not None:
            lo, hi = profile["weight"]
            if lo <= weight_g <= hi:
                _bump(fam, 1.0, "weight")

    if frame_inches is not None:
        _bump(_frame_setup_family(frame_inches), 2.0, "frame")

    if kv is not None:
        if kv >= 15000:
            _bump("tiny_whoop", 1.0, "kv")
        elif kv >= 10000:
            _bump("small_whoop", 1.0, "kv")
        elif kv >= 5000:
            _bump("micro_toothpick", 1.0, "kv")
        elif kv >= 2500:
            _bump("small_freestyle", 1.0, "kv")
        elif kv >= 1500:
            _bump("five_inch", 1.0, "kv")
        elif kv >= 900:
            _bump("long_range", 1.0, "kv")
        else:
            _bump("large_long_range", 1.0, "kv")

    if not scores:
        return "unknown_other", scores, evidence
    winner = _resolve_inferred_family(
        scores,
        selected_family=selected_family,
        frame_inches=frame_inches,
        prop_size=prop_size,
        cells=cells,
        stator_mm=stator_mm,
        weight_g=weight_g,
    )
    return winner, scores, evidence


def evaluate_hardware_compatibility(hardware: Mapping[str, Any] | None) -> dict[str, Any]:
    hw = hardware if isinstance(hardware, Mapping) else {}
    hardware_class = str(hw.get("hardware_class") or "").strip().lower() or None
    cells = _safe_int(hw.get("cells"))
    kv = _safe_int(hw.get("motor_kv_value"))
    prop_size = _safe_float(hw.get("prop_size"))
    stator_mm = _parse_motor_stator_diameter(hw.get("motor_stator"))
    frame_inches = _parse_frame_inches(hw.get("frame"))
    detected_frame_inches = _parse_frame_inches(hw.get("detected_frame"))
    weight_g = _safe_float(hw.get("weight"))
    selected_family = _CLASS_TO_FAMILY.get(str(hardware_class or ""), "unknown_other")

    required_ok = (
        bool(hardware_class)
        and isinstance(cells, int)
        and isinstance(kv, int)
        and isinstance(prop_size, float)
        and prop_size > 0.0
    )
    if not required_ok:
        return {
            "status": "missing_required",
            "compatibility_score": 100,
            "confidence_impact": "none",
            "confidence_multiplier": 1.0,
            "inferred_setup_family": "unknown_other",
            "best_matching_setup_profile": None,
            "selected_vs_inferred_mismatch": False,
            "confirmation_required": False,
            "issues": [],
            "reason_codes": ["missing_required_hardware_fields_for_compatibility"],
            "pending_issue_codes": [],
            "confirmed_issue_codes": [],
            "diagnostics": {
                "signals": {
                    "cells": cells,
                    "kv": kv,
                    "prop_inches": prop_size,
                    "stator_diameter": stator_mm,
                    "frame_inches": frame_inches,
                    "detected_frame_inches": detected_frame_inches,
                    "weight_g": weight_g,
                },
                "selected_class": hardware_class,
                "selected_family": selected_family,
                "inferred_family_scores": {},
                "inferred_evidence": [],
            },
        }

    inferred_family, inferred_scores, inferred_evidence = _inferred_family(
        hardware_class=hardware_class,
        frame_inches=frame_inches,
        cells=cells,
        prop_size=prop_size,
        stator_mm=stator_mm,
        kv=kv,
        weight_g=weight_g,
    )
    best_match = _best_matching_class(inferred_family, _safe_str(hw.get("style")))
    issues: list[dict[str, Any]] = []

    if hardware_class and inferred_family != "unknown_other" and selected_family != inferred_family:
        issues.append(
            _issue(
                "SETUP_CLASS_FRAME_MISMATCH",
                f"Selected class {hardware_class} does not match inferred setup family {inferred_family}.",
                severity="strong_warning",
                affected_fields=["hardware_class", "frame", "battery", "motor_stator", "prop_size"],
                confidence_impact="high",
                confirmation_required=True,
                suggestion=(
                    {
                        "field": "hardware_class",
                        "value": best_match,
                        "label": f"Use {best_match}",
                    }
                    if best_match
                    else None
                ),
            )
        )

    profile = _FAMILY_PROFILES.get(selected_family, _FAMILY_PROFILES["unknown_other"])
    if prop_size is not None:
        lo, hi = profile["prop"]
        if prop_size < lo or prop_size > hi:
            issues.append(
                _issue(
                    "PROP_CLASS_MISMATCH",
                    "Prop size looks unusual for selected class.",
                    severity="warning",
                    affected_fields=["prop_size", "hardware_class"],
                    confidence_impact="medium",
                    confirmation_required=True,
                )
            )
    if cells is not None:
        lo, hi = profile["cells"]
        if cells < lo or cells > hi:
            issues.append(
                _issue(
                    "CLASS_BATTERY_MISMATCH",
                    "Battery cell count looks unusual for selected class.",
                    severity="warning",
                    affected_fields=["battery", "hardware_class"],
                    confidence_impact="medium",
                    confirmation_required=True,
                )
            )
    if stator_mm is not None:
        lo, hi = profile["stator"]
        if stator_mm < lo or stator_mm > hi:
            issues.append(
                _issue(
                    "CLASS_MOTOR_SIZE_MISMATCH",
                    "Motor stator looks unusual for selected class.",
                    severity="warning",
                    affected_fields=["motor_stator", "hardware_class"],
                    confidence_impact="medium",
                    confirmation_required=True,
                )
            )

    if (
        cells == 1
        and kv is not None
        and kv < 10000
        and inferred_family in {"tiny_whoop", "small_whoop"}
    ):
        suggested = str(kv * 10) if kv <= 5000 else "25000"
        issues.append(
            _issue(
                "WHOOP_1S_LOW_KV_LIKELY_TYPO",
                f"{kv}KV looks unusually low for 1S tiny setup; this may be a missing zero.",
                severity="strong_warning",
                affected_fields=["motor_kv", "battery"],
                confidence_impact="high",
                confirmation_required=True,
                suggestion={
                    "field": "motor_kv",
                    "value": suggested,
                    "label": f"Use {suggested}KV",
                },
            )
        )

    if prop_size is not None and stator_mm is not None:
        if prop_size >= 5.0 and stator_mm <= 11:
            issues.append(
                _issue(
                    "MOTOR_TOO_SMALL_FOR_PROP_CLASS",
                    "Motor stator looks too small for selected prop class.",
                    severity="warning",
                    affected_fields=["motor_stator", "prop_size"],
                    confidence_impact="medium",
                    confirmation_required=True,
                )
            )
        if prop_size <= 3.0 and stator_mm >= 24:
            issues.append(
                _issue(
                    "MOTOR_TOO_LARGE_FOR_PROP_CLASS",
                    "Motor stator looks too large for selected prop class.",
                    severity="hint",
                    affected_fields=["motor_stator", "prop_size"],
                    confidence_impact="low",
                    confirmation_required=False,
                )
            )

    if cells is not None and kv is not None and prop_size is not None:
        if cells >= 6 and prop_size >= 4.5 and kv > 3200:
            issues.append(
                _issue(
                    "HIGH_CELL_KV_PROP_MISMATCH",
                    "High-cell, large-prop, high-KV combination looks unusually aggressive.",
                    severity="warning",
                    affected_fields=["battery", "motor_kv", "prop_size"],
                    confidence_impact="medium",
                    confirmation_required=True,
                )
            )
        if cells <= 2 and prop_size >= 5.0 and kv > 4200:
            issues.append(
                _issue(
                    "LOW_CELL_HIGH_PROP_HIGH_KV_MISMATCH",
                    "Low-cell setup with large props and high KV looks inconsistent.",
                    severity="warning",
                    affected_fields=["battery", "motor_kv", "prop_size"],
                    confidence_impact="medium",
                    confirmation_required=True,
                )
            )

    if weight_g is not None:
        lo, hi = profile["weight"]
        if weight_g < lo or weight_g > hi:
            issues.append(
                _issue(
                    "WEIGHT_OUT_OF_CLASS_RANGE",
                    f"Weight {int(round(weight_g))}g is unusual for selected class.",
                    severity="hint",
                    affected_fields=["weight", "hardware_class"],
                    confidence_impact="low",
                    confirmation_required=False,
                )
            )

    if hardware_class and detected_frame_inches is not None:
        detected_family, _scores, _evidence = _inferred_family(
            hardware_class=None,
            frame_inches=detected_frame_inches,
            cells=None,
            prop_size=None,
            stator_mm=None,
            kv=None,
            weight_g=None,
        )
        if detected_family != "unknown_other" and detected_family != selected_family:
            issues.append(
                _issue(
                    "DETECTED_FRAME_CLASS_MISMATCH",
                    "Detected frame characteristics differ from selected class.",
                    severity="warning",
                    affected_fields=["hardware_class", "frame"],
                    confidence_impact="medium",
                    confirmation_required=True,
                )
            )

    reason_codes: list[str] = []
    for issue in issues:
        code = str(issue.get("code") or "").strip()
        if code and code not in reason_codes:
            reason_codes.append(code)

    raw_confirmed = hw.get("hardware_plausibility", {}).get("confirmed_issue_codes")
    confirmed_set = (
        {str(code).strip() for code in raw_confirmed if str(code).strip()}
        if isinstance(raw_confirmed, list)
        else set()
    )
    pending_codes = [code for code in reason_codes if code not in confirmed_set]
    confirmed_codes = [code for code in reason_codes if code in confirmed_set]

    status: HardwareCompatibilityStatus = "valid"
    if issues:
        status = "suspicious" if pending_codes else "confirmed_suspicious"

    impact: HardwareConfidenceImpact = "none"
    for issue in issues:
        impact = _max_impact(impact, str(issue.get("confidence_impact") or "none"))

    multiplier = 1.0
    if status == "suspicious":
        multiplier = {"low": 0.92, "medium": 0.84, "high": 0.76}.get(impact, 0.88)
    elif status == "confirmed_suspicious":
        multiplier = {"low": 0.95, "medium": 0.90, "high": 0.85}.get(impact, 0.92)

    severity_penalty = 0
    for issue in issues:
        severity_penalty += {
            "info": 2,
            "hint": 5,
            "warning": 12,
            "strong_warning": 20,
        }.get(str(issue.get("severity") or ""), 8)

    return {
        "status": status,
        "compatibility_score": max(0, 100 - severity_penalty),
        "confidence_impact": impact,
        "confidence_multiplier": round(float(multiplier), 3),
        "inferred_setup_family": inferred_family,
        "best_matching_setup_profile": best_match,
        "selected_vs_inferred_mismatch": bool(
            hardware_class and inferred_family != "unknown_other" and selected_family != inferred_family
        ),
        "confirmation_required": bool(pending_codes),
        "issues": issues,
        "reason_codes": reason_codes,
        "pending_issue_codes": pending_codes,
        "confirmed_issue_codes": confirmed_codes,
        "diagnostics": {
            "signals": {
                "cells": cells,
                "kv": kv,
                "prop_inches": prop_size,
                "stator_diameter": stator_mm,
                "frame_inches": frame_inches,
                "detected_frame_inches": detected_frame_inches,
                "weight_g": weight_g,
            },
            "selected_class": hardware_class,
            "selected_family": selected_family,
            "inferred_family_scores": inferred_scores,
            "inferred_evidence": inferred_evidence,
        },
    }


def _safe_str(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    return text if text else None
