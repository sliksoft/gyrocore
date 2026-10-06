"""WU11 authorization gate, preview/denial, bypass, and save policy."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from gyrocore.autotune import MERGE_REQUIRES_REVIEW, propose_absolute_tune
from gyrocore.autotune.current_tune import TuneValue, ValueSource
from gyrocore.cli import ActionableTuneBundle, authorize_cli
from gyrocore.cli.authorize import (
    DENY_MERGE,
    DENY_MISSING_BASELINE,
    DENY_PROFILE,
    DENY_UNSUPPORTED,
    DENY_WARN_NOT_ACTIONABLE,
)
from gyrocore.cli.emit import PREVIEW_BANNER, flatten_absolute_tune, format_set_line, parse_authorized_cli
from gyrocore.cli.results import TuneCliDenial, TuneCliPreview
from gyrocore.safety import (
    FinalSafeTuneResult,
    SafeTuneCandidate,
    SafetyVerdict,
    StageBypassError,
    run_safety_pipeline,
)
from gyrocore.safety.results import make_final_safe_tune, make_safe_tune_candidate, make_tuning_output_safety
from tests.core.cli.helpers import (
    NOMINAL_CLI,
    clean_analysis,
    pass_with_delta,
    pipeline,
    profile_cli,
    proposal,
    proposal_with_dmax_delta,
    recommendation,
    sliders,
)
from tests.golden.safety import assert_safety_invariants, assert_wu11_cli_invariants

CLI_PKG = Path(__file__).resolve().parents[3] / "core" / "gyrocore" / "cli"


def _wu0(final) -> None:
    tos = final.output_safety.to_legacy_dict()
    assert_safety_invariants(
        {
            "ai_disabled": True,
            "tuning_output_safety": {**tos, "present": True},
            "mechanical_safety": final.mechanical.to_legacy_dict(),
            "authoritative_cli": "",
            "decision_engine_cli_authoritative": False,
        }
    )


def test_clean_pass_actionable_cli():
    final = pass_with_delta("slider_pi_gain")
    _wu0(final)
    auth = authorize_cli(final)
    assert_wu11_cli_invariants(auth.to_dict())
    assert auth.authorized is True
    assert auth.bundle is not None
    assert auth.bundle.authorized is True
    assert auth.bundle.actionable is True
    assert "set p_roll" in auth.bundle.apply_cli
    assert auth.bundle.apply_cli.strip().endswith("save")
    assert auth.bundle.rollback_cli.strip().endswith("save")
    assert auth.bundle.source_profile == 0
    assert auth.bundle.target_profile == 0
    assert auth.bundle.profile_command_required is True
    assert auth.preview is None
    assert auth.denial is None


def test_pass_p_change_within_step_cap():
    final = pass_with_delta("slider_pi_gain")
    assert final.status is SafetyVerdict.PASS
    auth = authorize_cli(final)
    assert auth.authorized
    assert "p_roll" in auth.bundle.changed_settings


def test_pass_i_change_within_step_cap():
    final = pass_with_delta("slider_i_gain")
    auth = authorize_cli(final)
    assert auth.authorized
    assert any(k.startswith("i_") for k in auth.bundle.changed_settings)


def test_pass_d_change_within_step_cap():
    final = pass_with_delta("slider_d_gain")
    auth = authorize_cli(final)
    assert auth.authorized
    assert any(k.startswith("d_") and not k.startswith("d_min") for k in auth.bundle.changed_settings)


def test_pass_ff_change_within_step_cap():
    final = pass_with_delta("slider_feedforward_gain")
    auth = authorize_cli(final)
    assert auth.authorized
    assert any(k.startswith("f_") for k in auth.bundle.changed_settings)


def test_pass_filter_change_within_step_cap():
    final = pass_with_delta("slider_dterm_filter_multiplier")
    auth = authorize_cli(final)
    assert auth.authorized
    assert any("dterm" in k for k in auth.bundle.changed_settings)


def test_pass_multiple_simultaneous_within_cap():
    final = pipeline(
        sliders(
            100,
            slider_pi_gain=108,
            slider_d_gain=106,
            slider_feedforward_gain=106,
            slider_dterm_filter_multiplier=101,
        )
    )
    assert final.status is SafetyVerdict.PASS
    auth = authorize_cli(final)
    assert auth.authorized
    keys = set(auth.bundle.changed_settings)
    assert any(k.startswith("p_") for k in keys)
    assert any(k.startswith("i_") for k in keys)
    assert any(k.startswith("d_") and "dterm" not in k and not k.startswith("d_min") for k in keys)
    assert any(k.startswith("f_") for k in keys)
    assert any("dterm" in k for k in keys)


def test_yaw_d_zero_preserved():
    final = pass_with_delta("slider_pi_gain")
    auth = authorize_cli(final)
    assert auth.bundle.target_values["d_yaw"] == 0
    assert "d_yaw" not in auth.bundle.changed_settings or auth.bundle.changed_settings["d_yaw"] == 0


def test_zero_off_filter_preserved():
    cli = NOMINAL_CLI.replace("set gyro_lpf2_static_hz = 500", "set gyro_lpf2_static_hz = 0")
    final = pipeline(sliders(100, slider_pi_gain=108), cli=cli)
    assert final.status is SafetyVerdict.PASS
    auth = authorize_cli(final)
    assert auth.authorized
    assert auth.bundle.current_values["gyro_lpf2_static_hz"] == 0
    assert auth.bundle.target_values["gyro_lpf2_static_hz"] == 0


def test_dmax_emitted_when_target_differs():
    final = run_safety_pipeline(proposal_with_dmax_delta(4), analysis=clean_analysis())
    assert final.status is SafetyVerdict.PASS
    auth = authorize_cli(final)
    assert auth.authorized
    assert "d_min_roll" in auth.bundle.changed_settings
    assert "set d_min_roll = " in auth.bundle.apply_cli
    assert "d_max_roll" not in auth.bundle.apply_cli


def test_pid_profile_zero_and_two():
    for idx in (0, 2):
        final = pipeline(sliders(100, slider_pi_gain=108), cli=profile_cli(idx))
        auth = authorize_cli(final)
        assert auth.authorized
        assert auth.bundle.source_profile == idx
        assert auth.bundle.target_profile == idx
        parsed = parse_authorized_cli(auth.bundle.apply_cli)
        assert parsed["profile"] == idx
        assert auth.bundle.apply_cli.startswith(f"profile {idx}\n")


def test_multiple_profiles_uses_active_block():
    cli = (
        NOMINAL_CLI.replace("profile 0\n", "profile 0\nset p_roll = 41\n", 1)
        + "\nprofile 1\n"
        + NOMINAL_CLI.split("profile 0\n", 1)[1].replace("set p_roll = 45", "set p_roll = 45")
        + "\n# restore original profile selection: 1\n"
    )
    final = pipeline(sliders(100, slider_pi_gain=108), cli=cli)
    auth = authorize_cli(final)
    assert auth.authorized
    assert auth.bundle.source_profile == final.current_tune.active_pid_profile.value
    assert parse_authorized_cli(auth.bundle.apply_cli)["profile"] == auth.bundle.source_profile


def test_noop_tune_authorized_without_save():
    final = pipeline(sliders(100))
    assert final.status is SafetyVerdict.PASS
    auth = authorize_cli(final)
    assert auth.authorized
    assert auth.bundle.changed_settings == {}
    assert auth.bundle.apply_cli == "profile 0\n"
    assert auth.bundle.rollback_cli == "profile 0\n"
    assert "save" not in auth.bundle.apply_cli


def test_warn_not_actionable():
    final = pipeline(sliders(100, slider_pi_gain=200))
    assert final.status is SafetyVerdict.WARN
    auth = authorize_cli(final)
    assert_wu11_cli_invariants(auth.to_dict())
    assert auth.authorized is False
    assert auth.bundle is None
    assert isinstance(auth.preview, TuneCliPreview)
    assert auth.preview.actionable is False
    assert auth.preview.authorized is False
    assert auth.preview.preview_cli.startswith(PREVIEW_BANNER)
    assert not any(line.strip() == "save" for line in auth.preview.preview_cli.splitlines())
    payload = auth.preview.to_dict()
    assert "apply_cli" not in payload
    assert "actionable_cli" not in payload
    assert "paste_ready_cli" not in payload
    assert DENY_WARN_NOT_ACTIONABLE in auth.preview.reasons


def test_block_not_actionable():
    final = pipeline(analysis={**clean_analysis(), "ok": False, "message": "no_usable_samples"})
    assert final.status is SafetyVerdict.BLOCK
    auth = authorize_cli(final)
    assert_wu11_cli_invariants(auth.to_dict())
    assert auth.authorized is False
    assert auth.bundle is None
    assert auth.preview is None
    assert isinstance(auth.denial, TuneCliDenial)
    payload = auth.denial.to_dict()
    for key in ("apply_cli", "actionable_cli", "paste_ready_cli", "preview_cli"):
        assert key not in payload
    assert payload["notice"].startswith("BLOCK")


def test_unresolved_merge_blocked():
    rec = recommendation(sliders(110))
    rec = replace(
        rec,
        axes={
            0: rec.axes[0],
            1: replace(rec.axes[1], recommendation=type(rec.axes[1].recommendation)(sliders(150))),
            2: rec.axes[2],
        },
    )
    prop = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
    assert prop.status == MERGE_REQUIRES_REVIEW
    final = run_safety_pipeline(prop, analysis=clean_analysis())
    auth = authorize_cli(final)
    assert auth.authorized is False
    assert auth.denial is not None
    assert DENY_MERGE in auth.denial.blocked_reasons or any("merge" in r for r in auth.denial.blocked_reasons)


def test_missing_baseline_blocks():
    final = pass_with_delta("slider_pi_gain")
    missing = TuneValue("roll.p", None, ValueSource.MISSING, "none", None, "stripped")
    new_current = replace(final.current_tune, roll=replace(final.current_tune.roll, p=missing))
    new_proposal = replace(final.proposal, current=new_current)
    cand = make_safe_tune_candidate(
        status=final.candidate.status,
        proposal=new_proposal,
        mechanical=final.mechanical,
        current_config=final.candidate.current_config,
        proposed_config=final.candidate.proposed_config,
        clamped_config=final.candidate.clamped_config,
        clamped_tune=final.candidate.clamped_tune,
        max_delta_used=final.candidate.max_delta_used,
        clamp_ids=final.candidate.clamp_ids,
        checks=final.candidate.checks,
        blocked_reasons=final.candidate.blocked_reasons,
        warnings=final.candidate.warnings,
        provenance=final.candidate.provenance,
    )
    tos = make_tuning_output_safety(
        status=final.output_safety.status,
        candidate=cand,
        blocking_reasons=final.output_safety.blocking_reasons,
        warning_reasons=final.output_safety.warning_reasons,
        checks=final.output_safety.checks,
        donor_status=final.output_safety.donor_status,
        provenance=final.output_safety.provenance,
    )
    mutated = make_final_safe_tune(
        status=SafetyVerdict.PASS,
        output_safety=tos,
        warnings=(),
        blocked_reasons=(),
        provenance=final.provenance,
    )
    auth = authorize_cli(mutated)
    assert auth.authorized is False
    assert DENY_MISSING_BASELINE in auth.denial.blocked_reasons


def test_unsupported_setting_rejected():
    with pytest.raises(ValueError, match="unsupported_cli_key"):
        format_set_line("simplified_pi_gain", 100)
    with pytest.raises(ValueError, match="unsupported_cli_key"):
        format_set_line("d_max_roll", 40)
    auth = authorize_cli(pass_with_delta("slider_pi_gain"))
    assert "simplified_" not in auth.bundle.apply_cli
    assert "d_max_" not in auth.bundle.apply_cli


def test_unsupported_betaflight_version_blocked():
    final = pass_with_delta("slider_pi_gain")
    prov = dict(final.proposal.provenance)
    prov["firmware"] = {"version": "3.1.7", "name": "Betaflight"}
    new_proposal = replace(final.proposal, provenance=prov)
    cand = make_safe_tune_candidate(
        status=final.candidate.status,
        proposal=new_proposal,
        mechanical=final.mechanical,
        current_config=final.candidate.current_config,
        proposed_config=final.candidate.proposed_config,
        clamped_config=final.candidate.clamped_config,
        clamped_tune=final.candidate.clamped_tune,
        max_delta_used=final.candidate.max_delta_used,
        clamp_ids=final.candidate.clamp_ids,
        checks=final.candidate.checks,
        blocked_reasons=(),
        warnings=(),
        provenance=final.candidate.provenance,
    )
    tos = make_tuning_output_safety(
        status=SafetyVerdict.PASS,
        candidate=cand,
        blocking_reasons=(),
        warning_reasons=(),
        checks=final.output_safety.checks,
        donor_status=final.output_safety.donor_status,
        provenance=final.output_safety.provenance,
    )
    mutated = make_final_safe_tune(
        status=SafetyVerdict.PASS,
        output_safety=tos,
        warnings=(),
        blocked_reasons=(),
        provenance=final.provenance,
    )
    auth = authorize_cli(mutated)
    assert auth.authorized is False
    assert DENY_UNSUPPORTED in auth.denial.blocked_reasons


def test_malformed_final_blocked():
    with pytest.raises(StageBypassError):
        authorize_cli(object())  # type: ignore[arg-type]
    with pytest.raises(StageBypassError):
        authorize_cli({"status": "pass"})  # type: ignore[arg-type]


def test_unknown_profile_blocks():
    final = pass_with_delta("slider_pi_gain")
    missing = TuneValue("active_pid_profile", None, ValueSource.MISSING, "none", None, "stripped")
    new_current = replace(final.current_tune, active_pid_profile=missing)
    new_target = replace(final.clamped_tune, active_pid_profile=missing)
    new_proposal = replace(final.proposal, current=new_current)
    cand = make_safe_tune_candidate(
        status=final.candidate.status,
        proposal=new_proposal,
        mechanical=final.mechanical,
        current_config=final.candidate.current_config,
        proposed_config=final.candidate.proposed_config,
        clamped_config=final.candidate.clamped_config,
        clamped_tune=new_target,
        max_delta_used=final.candidate.max_delta_used,
        clamp_ids=(),
        checks=final.candidate.checks,
        blocked_reasons=(),
        warnings=(),
        provenance=final.candidate.provenance,
    )
    tos = make_tuning_output_safety(
        status=SafetyVerdict.PASS,
        candidate=cand,
        blocking_reasons=(),
        warning_reasons=(),
        checks=(),
        donor_status="actionable",
    )
    mutated = make_final_safe_tune(status=SafetyVerdict.PASS, output_safety=tos, warnings=(), blocked_reasons=())
    auth = authorize_cli(mutated)
    assert auth.authorized is False
    assert DENY_PROFILE in auth.denial.blocked_reasons


def test_bypass_from_proposal_and_candidate():
    prop = proposal(sliders(108))
    with pytest.raises(StageBypassError):
        authorize_cli(prop)  # type: ignore[arg-type]
    final = pipeline(sliders(108))
    with pytest.raises(StageBypassError):
        authorize_cli(final.candidate)  # type: ignore[arg-type]


def test_direct_unauthorized_bundle_construction_blocked():
    final = pass_with_delta("slider_pi_gain")
    with pytest.raises(StageBypassError):
        ActionableTuneBundle(
            apply_cli="set p_roll = 1\nsave\n",
            rollback_cli="set p_roll = 45\nsave\n",
            source_profile=0,
            target_profile=0,
            profile_command_required=True,
            current_values={},
            target_values={},
            changed_settings={},
            unchanged_settings=(),
            warnings=(),
            verification_expectations={},
            safety_provenance={},
            firmware_provenance={},
            bundle_id="x",
            checks=(),
            final=final,
        )
    with pytest.raises(StageBypassError):
        TuneCliPreview(
            preview_cli="set p_roll = 1\n",
            reasons=(),
            current_values={},
            target_values={},
            changed_settings={},
            final=final,
        )
    with pytest.raises(StageBypassError):
        TuneCliDenial(blocked_reasons=("x",), diagnostic_values={}, final_status="block")
    with pytest.raises(StageBypassError):
        FinalSafeTuneResult(status=SafetyVerdict.PASS, output_safety=None, warnings=(), blocked_reasons=())  # type: ignore[arg-type]
    with pytest.raises(StageBypassError):
        SafeTuneCandidate(
            status=SafetyVerdict.PASS,
            proposal=proposal(),
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


def test_deterministic_output():
    final = pass_with_delta("slider_pi_gain")
    a = authorize_cli(final)
    b = authorize_cli(final)
    assert a.bundle.apply_cli == b.bundle.apply_cli
    assert a.bundle.rollback_cli == b.bundle.rollback_cli
    assert a.bundle.bundle_id == b.bundle.bundle_id


def test_save_command_policy():
    changed = authorize_cli(pass_with_delta("slider_pi_gain"))
    assert changed.bundle.apply_cli.strip().splitlines()[-1] == "save"
    assert changed.bundle.rollback_cli.strip().splitlines()[-1] == "save"
    noop = authorize_cli(pipeline(sliders(100)))
    assert "save" not in noop.bundle.apply_cli
    warn = authorize_cli(pipeline(sliders(100, slider_pi_gain=200)))
    assert not any(line.strip() == "save" for line in warn.preview.preview_cli.splitlines())
    blocked = authorize_cli(pipeline(analysis={**clean_analysis(), "ok": False}))
    assert blocked.denial is not None
    assert "apply_cli" not in blocked.denial.to_dict()


def test_safety_provenance_preserved():
    auth = authorize_cli(pass_with_delta("slider_pi_gain"))
    prov = auth.bundle.safety_provenance
    assert prov["mechanical"]["status"] == "pass"
    assert "clamp_ids" in prov["clamps"]
    assert prov["tuning_output_safety"]["cli_actionable"] is False
    assert prov["cli_authorization"] == "authorize_cli"
    assert auth.bundle.firmware_provenance["version"] == "2026.6.2"


def test_cli_package_has_no_msp_or_fc_io():
    forbidden = (
        "MSP_SET_PID",
        "MSP_SET_FILTER_CONFIG",
        "sendMsp",
        "serial.Serial",
        "FastAPI",
        "redis",
        "SQLAlchemy",
        "generate_cli",
    )
    for path in CLI_PKG.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        blob = ast.dump(tree)
        for name in forbidden:
            assert name not in blob, f"{path} contains {name}"
        assert "serial.Serial" not in text
        assert "MSP_SET" not in text
