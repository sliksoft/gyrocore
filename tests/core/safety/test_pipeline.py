"""WU10 staged pipeline matrix, fail-closed, bypass, and WU0 invariants."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from gyrocore.autotune import (
    MERGE_REQUIRES_REVIEW,
    AbsoluteTuneProposal,
    AutotuneRecommendationResult,
    AxisRecommendation,
    RecommendationStatus,
    extract_current_tune,
    propose_absolute_tune,
)
from gyrocore.autotune.absolute import extract_absolute_tune
from gyrocore.safety import (
    FinalSafeTuneResult,
    MechanicalSafetyResult,
    SafeTuneCandidate,
    SafetyVerdict,
    StageBypassError,
    TuningOutputSafetyResult,
    clamp_safe_tune,
    evaluate_mechanical_safety,
    evaluate_tuning_output_safety,
    finalize_safe_tune,
    run_safety_pipeline,
)
from gyrocore.safety.safe_tune import absolute_tune_to_config
from tests.golden.safety import assert_safety_invariants

ROOT = Path(__file__).resolve().parents[3]
SAFETY_PKG = ROOT / "core" / "gyrocore" / "safety"

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


def _sliders(value: int = 100, **overrides: int) -> dict[str, int]:
    base = {k: value for k in AUTOTUNE_KEYS}
    base.update(overrides)
    return base


@dataclass
class _StubGains:
    proposed: dict[str, int]


def _axis(axis: int, sliders: dict[str, int] | None, *, blocked: bool = False) -> AxisRecommendation:
    return AxisRecommendation(
        axis=axis,
        status=RecommendationStatus.BLOCKED if blocked else RecommendationStatus.PROPOSED,
        blocked_reasons=("sysid_unusable",) if blocked else (),
        warnings=(),
        system_id=None,
        recommendation=None if blocked else _StubGains(sliders or {}),
        current_sliders=None,
        sample_rate_hz=None,
        upstream_sample_rate_hz=None,
    )


def _recommendation(*axes: AxisRecommendation, cli: str = NOMINAL_CLI) -> AutotuneRecommendationResult:
    tune = extract_current_tune(cli_dump=cli)
    blocked = tuple(dict.fromkeys(r for a in axes for r in a.blocked_reasons))
    return AutotuneRecommendationResult(
        status=RecommendationStatus.BLOCKED if blocked else RecommendationStatus.PROPOSED,
        target_phase_margin_deg=60.0,
        current_tune=tune,
        axes={a.axis: a for a in axes},
        blocked_reasons=blocked,
        provenance={"test": True},
    )


def _proposal(sliders: dict[str, int] | None = None, *, cli: str = NOMINAL_CLI) -> AbsoluteTuneProposal:
    s = sliders or _sliders(100)
    rec = _recommendation(_axis(0, s), _axis(1, s), _axis(2, s), cli=cli)
    return propose_absolute_tune(rec, cli_dump=cli)


def _clean_analysis() -> dict:
    return {
        "ok": True,
        "quality": {"status": "ok", "score": 90},
        "confidence": {"score": 0.92, "label": "high"},
        "problems": {"problems": []},
        "metrics": {"noise": {"value": 90.0, "hf_ratio": 0.05, "level": "LOW"}},
        "motors": {"diagnostics": {"motors": [], "health": 100}},
        "resonance": {"severity": "low"},
    }


def _assert_wu0_view(final: FinalSafeTuneResult) -> None:
    tos = final.output_safety.to_legacy_dict()
    projection = {
        "ai_disabled": True,
        "tuning_output_safety": {**tos, "present": True},
        "mechanical_safety": final.mechanical.to_legacy_dict(),
        "authoritative_cli": "",
        "decision_engine_cli_authoritative": False,
    }
    assert_safety_invariants(projection)
    assert final.actionable is False
    assert final.output_safety.cli_actionable is False
    assert tos["cli_actionable"] is False


def test_clean_safe_proposal_no_clamps():
    proposal = _proposal(_sliders(100))
    analysis = _clean_analysis()
    final = run_safety_pipeline(proposal, analysis=analysis)
    _assert_wu0_view(final)
    assert final.status is SafetyVerdict.PASS
    assert final.clamped_tune is not None
    assert final.clamped_tune.roll.p.value == proposal.current.roll.p.value
    assert final.clamped_tune.yaw.d.value == proposal.current.yaw.d.value
    assert final.actionable is False
    assert final.candidate.clamp_ids == ()


def test_clean_proposal_requiring_no_clamps_pass():
    proposal = _proposal(_sliders(100))
    mech = evaluate_mechanical_safety(_clean_analysis(), require_analysis=True)
    cand = clamp_safe_tune(proposal, mech, analysis=_clean_analysis())
    assert cand.status is SafetyVerdict.PASS
    tos = evaluate_tuning_output_safety(cand, analysis=_clean_analysis())
    assert tos.status is SafetyVerdict.PASS
    final = finalize_safe_tune(tos)
    assert final.status is SafetyVerdict.PASS
    assert final.actionable is False


def _final_with_sliders(**overrides: int) -> FinalSafeTuneResult:
    return run_safety_pipeline(_proposal(_sliders(100, **overrides)), analysis=_clean_analysis())


def test_p_clamp():
    final = _final_with_sliders(slider_pi_gain=200)
    assert final.clamped_tune is not None
    current_p = final.current_tune.roll.p.value
    proposed_p = final.original_proposal_tune.roll.p.value
    clamped_p = final.clamped_tune.roll.p.value
    assert proposed_p - current_p > 4
    assert clamped_p == current_p + 4
    assert any("roll.p" in c.rule_id for c in final.candidate.checks)


def test_i_clamp():
    final = _final_with_sliders(slider_i_gain=200)
    current = final.current_tune.roll.i.value
    proposed = final.original_proposal_tune.roll.i.value
    clamped = final.clamped_tune.roll.i.value
    assert proposed - current > 8
    assert clamped == current + 8


def test_d_clamp():
    final = _final_with_sliders(slider_d_gain=200)
    current = final.current_tune.roll.d.value
    proposed = final.original_proposal_tune.roll.d.value
    clamped = final.clamped_tune.roll.d.value
    assert proposed - current > 6
    assert clamped == current + 6


def test_ff_clamp():
    final = _final_with_sliders(slider_feedforward_gain=200)
    current = final.current_tune.roll.f.value
    proposed = final.original_proposal_tune.roll.f.value
    clamped = final.clamped_tune.roll.f.value
    assert proposed - current > 8
    assert clamped == current + 8


def test_filter_clamp():
    final = _final_with_sliders(slider_dterm_filter_multiplier=50)
    current = final.current_tune.dterm.lpf1_dyn_min_hz.value
    proposed = final.original_proposal_tune.dterm.lpf1_dyn_min_hz.value
    clamped = final.clamped_tune.dterm.lpf1_dyn_min_hz.value
    assert proposed < current
    # step cap 20 then donor hard min 70
    assert clamped == 70
    assert any("dterm_lpf1_dyn_min" in c.rule_id for c in final.candidate.checks)


def test_multiple_simultaneous_clamps():
    final = _final_with_sliders(
        slider_pi_gain=200,
        slider_i_gain=200,
        slider_d_gain=200,
        slider_feedforward_gain=200,
        slider_dterm_filter_multiplier=50,
    )
    ids = " ".join(final.candidate.clamp_ids)
    assert "roll.p" in ids
    assert "roll.i" in ids
    assert "roll.d" in ids
    assert "roll.ff" in ids or "ff" in ids
    assert "dterm" in ids or "filter" in ids
    assert final.actionable is False


def test_blocked_mechanical_condition():
    proposal = _proposal()
    mech = evaluate_mechanical_safety(
        pipeline_problems={
            "problems": [
                {
                    "type": "motor_issue",
                    "severity": "high",
                    "confidence": 0.8,
                    "description": "confirmed motor desync with saturation and loss of control",
                }
            ]
        },
        motor_diagnostics={"motors": []},
        engine_metrics={"noise": {"value": 80.0}, "resonance": {"severity": "low"}},
    )
    cand = clamp_safe_tune(proposal, mech, analysis=_clean_analysis())
    tos = evaluate_tuning_output_safety(cand, analysis=_clean_analysis(), require_analysis=True)
    final = finalize_safe_tune(tos)
    assert mech.status is SafetyVerdict.BLOCK
    assert cand.status is SafetyVerdict.BLOCK
    assert tos.status is SafetyVerdict.BLOCK
    assert final.status is SafetyVerdict.BLOCK
    assert final.clamped_tune is None
    assert final.actionable is False
    assert "mechanical_hard_block" in final.blocked_reasons


def test_warning_only_mechanical_condition():
    proposal = _proposal()
    analysis = _clean_analysis()
    mech = evaluate_mechanical_safety(
        analysis,
        motor_diagnostics={
            "motors": [{"motor": 2, "status": "warning", "confidence": 0.55, "health": 78}]
        },
        engine_metrics={"noise": {"value": 85.0, "hf_ratio": 0.05}, "resonance": {"severity": "low"}},
        noise_level="LOW",
        require_analysis=False,
    )
    assert mech.status is SafetyVerdict.WARN
    cand = clamp_safe_tune(proposal, mech, analysis=analysis)
    tos = evaluate_tuning_output_safety(cand, analysis=analysis)
    final = finalize_safe_tune(tos)
    assert final.status is SafetyVerdict.WARN
    assert final.actionable is False
    assert not final.blocked_reasons or "mechanical_hard_block" not in final.blocked_reasons


def test_missing_mechanical_stage_cannot_clamp():
    proposal = _proposal()
    with pytest.raises(StageBypassError):
        clamp_safe_tune(proposal, object())  # type: ignore[arg-type]


def test_missing_safe_tune_stage_cannot_evaluate_tos():
    with pytest.raises(StageBypassError):
        evaluate_tuning_output_safety(object())  # type: ignore[arg-type]


def test_unresolved_multi_axis_merge():
    rec = _recommendation(
        _axis(0, _sliders(110)),
        _axis(1, _sliders(150)),
        _axis(2, _sliders(100)),
    )
    proposal = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
    assert proposal.status == MERGE_REQUIRES_REVIEW
    final = run_safety_pipeline(proposal, analysis=_clean_analysis())
    assert final.status is SafetyVerdict.BLOCK
    assert any("merge" in r for r in final.blocked_reasons)


def test_invalid_baseline():
    cli = "set simplified_pids_mode = RPY\nset simplified_pi_gain = 100\n"
    rec = _recommendation(_axis(0, _sliders(100)), _axis(1, _sliders(100)), _axis(2, _sliders(100)), cli=cli)
    proposal = propose_absolute_tune(rec, cli_dump=cli)
    final = run_safety_pipeline(proposal, analysis=_clean_analysis())
    assert final.status is SafetyVerdict.BLOCK
    assert any("baseline" in r or "malformed" in r or "incomplete" in r for r in final.blocked_reasons)


def test_system_id_unusable():
    rec = _recommendation(
        _axis(0, None, blocked=True),
        _axis(1, _sliders(100)),
        _axis(2, _sliders(100)),
    )
    proposal = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
    final = run_safety_pipeline(proposal, analysis=_clean_analysis())
    assert final.status is SafetyVerdict.BLOCK
    assert any("sysid" in r or "blocked" in r for r in final.blocked_reasons)


def test_slider_inconsistency_blocks():
    from dataclasses import replace

    from gyrocore.betaflight.simplified_tuning import FieldMismatch, SliderValidity

    proposal = replace(
        _proposal(),
        proposed_validity=SliderValidity(
            pids_valid=False,
            gyro_valid=True,
            dterm_valid=True,
            pid_mismatches=(FieldMismatch("roll.p", 45, 60),),
        ),
    )
    final = run_safety_pipeline(proposal, analysis=_clean_analysis())
    assert final.status is SafetyVerdict.BLOCK
    assert any("slider" in r for r in final.blocked_reasons)


def test_unsupported_config_simplified_off():
    cli = NOMINAL_CLI.replace("set simplified_pids_mode = RPY", "set simplified_pids_mode = OFF")
    rec = _recommendation(_axis(0, _sliders(110)), _axis(1, _sliders(110)), _axis(2, _sliders(110)), cli=cli)
    proposal = propose_absolute_tune(rec, cli_dump=cli)
    final = run_safety_pipeline(proposal, analysis=_clean_analysis())
    assert final.status is SafetyVerdict.BLOCK


def test_final_safety_pass_warn_block_and_actionable_false():
    passed = run_safety_pipeline(_proposal(_sliders(100)), analysis=_clean_analysis())
    warned = run_safety_pipeline(_proposal(_sliders(100, slider_pi_gain=200)), analysis=_clean_analysis())
    blocked = run_safety_pipeline(
        _proposal(),
        analysis={**_clean_analysis(), "ok": False, "message": "no_usable_samples"},
    )
    assert passed.status is SafetyVerdict.PASS
    assert warned.status in {SafetyVerdict.WARN, SafetyVerdict.PASS}
    if warned.candidate.clamp_ids:
        assert warned.status is SafetyVerdict.WARN
    assert blocked.status is SafetyVerdict.BLOCK
    for result in (passed, warned, blocked):
        assert result.actionable is False
        assert result.output_safety.cli_actionable is False


def test_bypass_attempt_and_construction_without_stage():
    with pytest.raises(StageBypassError):
        MechanicalSafetyResult(
            status=SafetyVerdict.PASS,
            mechanical_block=False,
            mechanical_limited=False,
            mechanical_caution=False,
            mechanical_outcome="mechanical_clear",
            recommended_action="none",
            reasons=(),
            blocking_reasons=(),
            limited_reasons=(),
            caution_reasons=(),
            max_delta_scale=1.0,
            evidence={},
            checks=(),
            raw={},
        )
    with pytest.raises(StageBypassError):
        finalize_safe_tune(object())  # type: ignore[arg-type]
    with pytest.raises(StageBypassError):
        FinalSafeTuneResult(
            status=SafetyVerdict.PASS,
            output_safety=None,  # type: ignore[arg-type]
            warnings=(),
            blocked_reasons=(),
        )
    with pytest.raises(StageBypassError):
        SafeTuneCandidate(
            status=SafetyVerdict.PASS,
            proposal=_proposal(),
            mechanical=None,  # type: ignore[arg-type]
            current_config={},
            proposed_config=None,
            clamped_config=None,
            clamped_tune=None,
            max_delta_used={},
            clamp_ids=(),
            checks=(),
            blocked_reasons=(),
            warnings=(),
        )
    with pytest.raises(StageBypassError):
        TuningOutputSafetyResult(
            status=SafetyVerdict.PASS,
            candidate=None,  # type: ignore[arg-type]
            blocking_reasons=(),
            warning_reasons=(),
            checks=(),
            donor_status="actionable",
        )


def test_no_public_jump_from_proposal_to_final():
    import gyrocore.safety as pkg

    assert not hasattr(pkg, "proposal_to_final")
    assert not hasattr(pkg, "apply_cli")
    src = Path(__import__("inspect").getfile(pkg)).read_text(encoding="utf-8")
    assert "run_safety_pipeline" in src


def test_safety_package_has_no_cli_msp_or_fc_write():
    forbidden_names = {
        "MSP_SET_PID",
        "MSP_SET_FILTER_CONFIG",
        "sendMsp",
        "write_eeprom",
        "generate_cli",
        "FastAPI",
        "redis",
        "SQLAlchemy",
    }
    for path in SAFETY_PKG.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        blob = ast.dump(tree)
        for name in forbidden_names:
            assert name not in blob, f"{path} contains {name}"
        assert "serial.Serial" not in text
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value.startswith("set simplified_") and "save" in text.lower():
                    raise AssertionError(f"{path} looks like paste-ready CLI")


def test_wu0_blocked_cannot_expose_cli():
    final = run_safety_pipeline(
        _proposal(),
        analysis={**_clean_analysis(), "ok": False},
    )
    _assert_wu0_view(final)
    assert final.status is SafetyVerdict.BLOCK
    assert final.to_dict()["actionable"] is False


def test_missing_analysis_fails_closed():
    final = run_safety_pipeline(_proposal(), analysis=None, require_analysis=True)
    assert final.status is SafetyVerdict.BLOCK
    assert "missing_required_analysis" in final.blocked_reasons


def test_trace_answers_why():
    final = _final_with_sliders(slider_pi_gain=200)
    payload = final.to_dict()
    assert payload["mechanical_safety"]["checks"]
    assert payload["clamp_evidence"]["checks"]
    assert payload["tuning_output_safety"]["checks"]
    assert any(c.get("before") is not None for c in payload["clamp_evidence"]["checks"])


def test_absolute_tune_config_roundtrip_keys():
    tune = extract_absolute_tune(cli_dump=NOMINAL_CLI)
    cfg, missing = absolute_tune_to_config(tune)
    assert missing == ()
    assert "p" in cfg["pid"]["roll"]
    assert "dterm_lpf1_dyn_min_hz" in cfg["filters"]
