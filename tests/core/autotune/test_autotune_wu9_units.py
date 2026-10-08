"""WU9 units: current absolute tune, merge policy, non-actionable proposal."""

from __future__ import annotations

import ast
import inspect
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

import gyrocore.autotune as autotune
from gyrocore.autotune import (
    MERGE_REQUIRES_REVIEW,
    AbsoluteTuneProposal,
    AutotuneRecommendationResult,
    AxisRecommendation,
    RecommendationStatus,
    extract_absolute_tune,
    extract_current_tune,
    merge_autotune_sliders,
    propose_absolute_tune,
)
from gyrocore.autotune.absolute import NON_ACTIONABLE_NOTICE as ABS_NOTICE
from gyrocore.autotune.absolute import PROPOSAL_KIND
from gyrocore.autotune.engine import REQUIRED_DOWNSTREAM_STAGES
from gyrocore.betaflight.simplified_tuning import (
    PID_SIMPLIFIED_TUNING_RPY,
    SimplifiedSliders,
    apply_simplified_tuning_pids,
    firmware_default_pid_profile,
)

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
# restore original profile selection
profile 0
"""

INCONSISTENT_CLI = NOMINAL_CLI.replace("set p_roll = 45", "set p_roll = 60")

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
        blocked_reasons=("blocked",) if blocked else (),
        warnings=(),
        system_id=None,
        recommendation=None if blocked else _StubGains(sliders or {}),
        current_sliders=None,
        sample_rate_hz=None,
        upstream_sample_rate_hz=None,
    )


def _recommendation(*axes: AxisRecommendation, cli: str = NOMINAL_CLI) -> AutotuneRecommendationResult:
    tune = extract_current_tune(cli_dump=cli)
    return AutotuneRecommendationResult(
        status=RecommendationStatus.PROPOSED,
        target_phase_margin_deg=60.0,
        current_tune=tune,
        axes={a.axis: a for a in axes},
        provenance={"test": True},
    )


# ---------------------------------------------------------------------------
# Current absolute baseline
# ---------------------------------------------------------------------------


def test_nominal_cli_is_slider_consistent():
    abs_tune = extract_absolute_tune(cli_dump=NOMINAL_CLI)
    assert abs_tune.roll.p.value == 45 and abs_tune.roll.f.value == 120 and abs_tune.roll.d_max.value == 40
    assert abs_tune.sliders.d_max_gain == 100 and abs_tune.sliders.pitch_pi_gain == 100
    assert abs_tune.active_pid_profile.value == 0
    profile = abs_tune.to_pid_profile()
    gyro = abs_tune.to_gyro()
    assert profile is not None and gyro is not None
    from gyrocore.betaflight.simplified_tuning import validate_simplified_tuning

    v = validate_simplified_tuning(profile, gyro)
    assert v.pids_valid and v.dterm_valid and v.gyro_valid and not v.pid_mismatches


def test_inconsistent_cli_records_pid_mismatch_evidence():
    abs_tune = extract_absolute_tune(cli_dump=INCONSISTENT_CLI)
    v = abs_tune.to_pid_profile()
    from gyrocore.betaflight.simplified_tuning import firmware_default_gyro, validate_simplified_tuning

    ev = validate_simplified_tuning(v, abs_tune.to_gyro() or firmware_default_gyro())
    assert ev.pids_valid is False
    assert any(m.field == "roll.p" and m.current == 60 and m.expected_from_sliders == 45 for m in ev.pid_mismatches)


def test_missing_values_stay_missing():
    abs_tune = extract_absolute_tune(cli_dump="set p_roll = 45\nset simplified_pids_mode = RPY\n")
    assert abs_tune.roll.p.value == 45
    assert abs_tune.roll.f.source.value == "missing"
    assert abs_tune.roll.d_max.source.value == "missing"
    assert abs_tune.sliders.d_max_gain is None
    assert abs_tune.sliders.gyro_filter_multiplier is None
    assert abs_tune.to_pid_profile() is None


def test_does_not_invent_another_cli_parser():
    src = inspect.getsource(autotune.absolute)
    assert "parse_cli_profile_blocks" in src
    assert "extract_current_tune" in src
    assert "def parse_cli" not in src


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def test_single_axis_matches_upstream_apply_one_axis():
    current = SimplifiedSliders()
    proposed = _sliders(110, slider_d_gain=90)
    merge = merge_autotune_sliders({0: _axis(0, proposed)}, current)
    assert merge.status == "merged"
    assert merge.participating_axes == ("roll",)
    assert merge.proposed_sliders == proposed
    assert merge.simplified.d_gain == 90
    assert merge.simplified.d_max_gain == 100  # untouched
    assert merge.fields["slider_d_gain"].constrained_by == ("roll",)
    assert merge.policy_kind == "gyrocore"


def test_roll_pitch_agreement_merges():
    current = SimplifiedSliders()
    proposed = _sliders(120)
    merge = merge_autotune_sliders(
        {0: _axis(0, proposed), 1: _axis(1, dict(proposed))},
        current,
    )
    assert merge.status == "merged"
    assert merge.participating_axes == ("roll", "pitch")
    assert merge.proposed_sliders["slider_pi_gain"] == 120


def test_roll_pitch_disagreement_requires_review():
    current = SimplifiedSliders()
    merge = merge_autotune_sliders(
        {
            0: _axis(0, _sliders(110)),
            1: _axis(1, _sliders(110, slider_d_gain=90)),
        },
        current,
    )
    assert merge.status == MERGE_REQUIRES_REVIEW
    assert "slider_disagreement:slider_d_gain" in merge.review_reasons
    assert merge.proposed_sliders is None
    assert merge.fields["slider_d_gain"].agreed is False
    assert merge.fields["slider_pi_gain"].agreed is True


def test_three_axis_agreement_and_conflict():
    current = SimplifiedSliders()
    agree = _sliders(105)
    ok = merge_autotune_sliders(
        {0: _axis(0, agree), 1: _axis(1, dict(agree)), 2: _axis(2, dict(agree))},
        current,
    )
    assert ok.status == "merged" and ok.participating_axes == ("roll", "pitch", "yaw")
    bad = merge_autotune_sliders(
        {
            0: _axis(0, _sliders(105)),
            1: _axis(1, _sliders(105)),
            2: _axis(2, _sliders(80)),
        },
        current,
    )
    assert bad.status == MERGE_REQUIRES_REVIEW
    assert any(r.startswith("slider_disagreement:") for r in bad.review_reasons)


def test_no_participating_axes_requires_review():
    merge = merge_autotune_sliders({0: _axis(0, _sliders(), blocked=True)}, SimplifiedSliders())
    assert merge.status == MERGE_REQUIRES_REVIEW
    assert merge.review_reasons == ("no_participating_axes",)


def test_blocked_axis_is_ignored_when_another_participates():
    merge = merge_autotune_sliders(
        {0: _axis(0, _sliders(130)), 2: _axis(2, None, blocked=True)},
        SimplifiedSliders(),
    )
    assert merge.status == "merged" and merge.participating_axes == ("roll",)


# ---------------------------------------------------------------------------
# Proposal
# ---------------------------------------------------------------------------


def test_proposal_from_unanimous_axes_maps_firmware_pids():
    rec = _recommendation(_axis(0, _sliders(slider_master_multiplier=200)), _axis(1, _sliders(slider_master_multiplier=200)))
    proposal = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
    assert proposal.actionable is False
    assert proposal.status == "proposed"
    assert proposal.proposed is not None
    mapped = apply_simplified_tuning_pids(
        replace(firmware_default_pid_profile(), sliders=proposal.merge.simplified)
    )
    assert proposal.proposed.roll.p.value == mapped.roll.p == 90
    assert proposal.proposed.pitch.p.value == mapped.pitch.p == 94
    assert proposal.deltas["roll.p"]["delta"] == 45
    assert proposal.current_validity.pids_valid
    assert proposal.proposed_validity.pids_valid
    d = proposal.to_dict()
    assert d["actionable"] is False and d["kind"] == PROPOSAL_KIND
    json.dumps(d)


def test_proposal_disagreement_does_not_invent_merge():
    rec = _recommendation(_axis(0, _sliders(110)), _axis(1, _sliders(90)))
    proposal = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
    assert proposal.status == MERGE_REQUIRES_REVIEW
    assert proposal.proposed is None
    assert proposal.per_axis_recommendations["roll"]["slider_pi_gain"] == 110
    assert proposal.per_axis_recommendations["pitch"]["slider_pi_gain"] == 90
    assert proposal.actionable is False


def test_proposal_one_axis_only():
    rec = _recommendation(_axis(0, _sliders(slider_master_multiplier=150)))
    proposal = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
    assert proposal.status == "proposed"
    assert proposal.merge.participating_axes == ("roll",)
    assert proposal.proposed.roll.p.value == 67  # 45 * 1.5 truncated


def test_inconsistent_current_is_flagged_not_reconstructed():
    rec = _recommendation(_axis(0, _sliders(100)), cli=INCONSISTENT_CLI)
    proposal = propose_absolute_tune(rec, cli_dump=INCONSISTENT_CLI)
    assert proposal.current_validity.pids_valid is False
    assert proposal.proposed is not None
    assert proposal.proposed.roll.p.value == 45  # mapped from sliders, not the inconsistent 60
    assert proposal.current.roll.p.value == 60


def test_proposal_structurally_non_actionable():
    fields = {f.name: f for f in AbsoluteTuneProposal.__dataclass_fields__.values()}
    assert fields["actionable"].init is False and fields["actionable"].default is False
    rec = _recommendation(_axis(0, _sliders()))
    proposal = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
    with pytest.raises(TypeError):
        AbsoluteTuneProposal(
            status="proposed",
            current=proposal.current,
            merge=proposal.merge,
            per_axis_recommendations={},
            proposed=None,
            current_validity=proposal.current_validity,
            proposed_validity=None,
            deltas={},
            actionable=True,
        )
    d = proposal.to_dict()
    assert d["actionable"] is False and d["non_actionable_notice"] == ABS_NOTICE
    assert d["required_downstream_stages"] == list(REQUIRED_DOWNSTREAM_STAGES)


def test_autotune_package_still_has_no_apply_path():
    pkg = Path(autotune.__file__).parent
    forbidden_calls = {"MSP_SET_SIMPLIFIED_TUNING", "MSP_EEPROM_WRITE", "MSP_SET_PID", "sendMsp", "send_msp", "serial", "write_eeprom"}
    for src in pkg.glob("*.py"):
        text = src.read_text()
        tree = ast.parse(text)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not (names & forbidden_calls), (src.name, names & forbidden_calls)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                s = node.value.lstrip()
                assert not s.startswith("set simplified_"), (src.name, s)
                assert "save\n" not in s
    public = [n for n in dir(AbsoluteTuneProposal) if not n.startswith("_")]
    assert not [n for n in public if any(w in n.lower() for w in ("apply", "cli", "msp", "write", "paste"))]
