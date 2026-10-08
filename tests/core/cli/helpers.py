"""Shared WU11 fixtures. Reuses WU10 pipeline; does not change WU10 behavior."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from gyrocore.autotune import (
    AbsoluteTuneProposal,
    AutotuneRecommendationResult,
    AxisRecommendation,
    RecommendationStatus,
    extract_current_tune,
    propose_absolute_tune,
)
from gyrocore.cli.emit import flatten_absolute_tune
from gyrocore.safety import SafetyVerdict, run_safety_pipeline
from gyrocore.safety.results import FinalSafeTuneResult

ROOT = Path(__file__).resolve().parents[3]
GOLDEN_DIR = ROOT / "tests" / "fixtures" / "cli_wu11"

NOMINAL_CLI = """# Betaflight / STM32F7X2 2026.6.2
profile 0
set p_roll = 45
set i_roll = 80
set d_roll = 30
set f_roll = 120
set d_max_roll = 40
set p_pitch = 47
set i_pitch = 84
set d_pitch = 34
set f_pitch = 125
set d_max_pitch = 46
set p_yaw = 45
set i_yaw = 80
set d_yaw = 0
set f_yaw = 120
set d_max_yaw = 0
set dterm_lpf1_dyn_min_hz = 75
set dterm_lpf1_dyn_max_hz = 150
set dterm_lpf1_static_hz = 75
set dterm_lpf2_static_hz = 150
set gyro_lpf1_dyn_min_hz = 250
set gyro_lpf1_dyn_max_hz = 500
set gyro_lpf1_static_hz = 250
set gyro_lpf2_static_hz = 500
set simplified_pids_mode = RPY
set simplified_master_multiplier = 100
set simplified_pi_gain = 100
set simplified_i_gain = 100
set simplified_d_gain = 100
set simplified_d_max_gain = 100
set simplified_feedforward_gain = 100
set simplified_pitch_pi_gain = 100
set simplified_pitch_d_gain = 100
set simplified_dterm_filter = ON
set simplified_dterm_filter_multiplier = 100
set simplified_gyro_filter = ON
set simplified_gyro_filter_multiplier = 100
profile 0
"""

AUTOTUNE_KEYS = (
    "slider_master_multiplier",
    "slider_pi_gain",
    "slider_i_gain",
    "slider_d_gain",
    "slider_feedforward_gain",
    "slider_dterm_filter_multiplier",
)


def sliders(value: int = 100, **overrides: int) -> dict[str, int]:
    base = {k: value for k in AUTOTUNE_KEYS}
    base.update(overrides)
    return base


@dataclass
class _StubGains:
    proposed: dict[str, int]


def _axis(axis: int, slider_map: dict[str, int] | None, *, blocked: bool = False) -> AxisRecommendation:
    return AxisRecommendation(
        axis=axis,
        status=RecommendationStatus.BLOCKED if blocked else RecommendationStatus.PROPOSED,
        blocked_reasons=("sysid_unusable",) if blocked else (),
        warnings=(),
        system_id=None,
        recommendation=None if blocked else _StubGains(slider_map or {}),
        current_sliders=None,
        sample_rate_hz=None,
        upstream_sample_rate_hz=None,
    )


def recommendation(slider_map: dict[str, int] | None = None, *, cli: str = NOMINAL_CLI, blocked: bool = False) -> AutotuneRecommendationResult:
    s = slider_map or sliders(100)
    axes = (_axis(0, s, blocked=blocked), _axis(1, s), _axis(2, s))
    tune = extract_current_tune(cli_dump=cli)
    blocked_reasons = tuple(dict.fromkeys(r for a in axes for r in a.blocked_reasons))
    return AutotuneRecommendationResult(
        status=RecommendationStatus.BLOCKED if blocked_reasons else RecommendationStatus.PROPOSED,
        target_phase_margin_deg=60.0,
        current_tune=tune,
        axes={a.axis: a for a in axes},
        blocked_reasons=blocked_reasons,
        provenance={"test": True},
    )


def proposal(slider_map: dict[str, int] | None = None, *, cli: str = NOMINAL_CLI) -> AbsoluteTuneProposal:
    s = slider_map or sliders(100)
    return propose_absolute_tune(recommendation(s, cli=cli), cli_dump=cli)


def clean_analysis() -> dict:
    return {
        "ok": True,
        "quality": {"status": "ok", "score": 90},
        "confidence": {"score": 0.92, "label": "high"},
        "problems": {"problems": []},
        "metrics": {"noise": {"value": 90.0, "hf_ratio": 0.05, "level": "LOW"}},
        "motors": {"diagnostics": {"motors": [], "health": 100}},
        "resonance": {"severity": "low"},
    }


def pipeline(slider_map: dict[str, int] | None = None, *, cli: str = NOMINAL_CLI, analysis: dict | None = None) -> FinalSafeTuneResult:
    return run_safety_pipeline(proposal(slider_map, cli=cli), analysis=analysis if analysis is not None else clean_analysis())


def profile_cli(profile: int) -> str:
    return NOMINAL_CLI.replace("profile 0", f"profile {profile}")


def pass_with_delta(key: str = "slider_pi_gain") -> FinalSafeTuneResult:
    """Find a WU10 PASS whose authorized target differs from baseline (no clamp rewrite)."""
    candidates = [100 + b for b in (9, 8, 7, 6, 5, 4, 3, 2, 1)]
    candidates += [100 - b for b in (1, 2, 3, 4, 5)]
    for value in candidates:
        final = pipeline(sliders(100, **{key: value}))
        if final.status is not SafetyVerdict.PASS or final.clamped_tune is None:
            continue
        if flatten_absolute_tune(final.current_tune) != flatten_absolute_tune(final.clamped_tune):
            return final
    raise AssertionError(f"no PASS-with-delta slider for {key}")


def proposal_with_dmax_delta(delta: int = 4) -> AbsoluteTuneProposal:
    base = proposal(sliders(100))
    assert base.proposed is not None
    proposed = base.proposed

    def bump(axis_name: str):
        axis = getattr(proposed, axis_name)
        tv = axis.d_max
        return replace(axis, d_max=replace(tv, value=int(tv.value) + delta))

    return replace(base, proposed=replace(proposed, roll=bump("roll"), pitch=bump("pitch")))
