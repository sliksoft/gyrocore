"""Parser round-trip: apply then rollback, WU2 semantic equality."""

from __future__ import annotations

from gyrocore.betaflight.cli import parse_cli_dump
from gyrocore.cli import authorize_cli
from gyrocore.cli.emit import flatten_absolute_tune, overlay_settings, parse_authorized_cli
from gyrocore.cli.settings import CANONICAL_SET_ORDER, PID_CLI_KEYS
from tests.core.cli.helpers import pass_with_delta, pipeline, proposal_with_dmax_delta, sliders
from gyrocore.safety import run_safety_pipeline
from tests.core.cli.helpers import clean_analysis


def _wu2_overlay(base: dict[str, int], cli_text: str) -> dict[str, int]:
    parsed = parse_cli_dump(cli_text)
    out = dict(base)
    pid = parsed.get("pid") or {}
    for axis, comp, key in PID_CLI_KEYS:
        donor = "ff" if comp == "ff" else comp
        if comp == "d_max":
            continue
        block = pid.get(axis) or {}
        if donor in block:
            out[key] = int(block[donor])
    dmin = parsed.get("d_min") or {}
    for axis, key in (("roll", "d_min_roll"), ("pitch", "d_min_pitch"), ("yaw", "d_min_yaw")):
        if axis in dmin:
            out[key] = int(dmin[axis])
    filters = parsed.get("filters") or {}
    for key in CANONICAL_SET_ORDER:
        if key in filters:
            out[key] = int(filters[key])
    return out


def _assert_roundtrip(final) -> None:
    auth = authorize_cli(final)
    assert auth.authorized
    bundle = auth.bundle
    current = dict(bundle.current_values)
    target = dict(bundle.target_values)
    after_apply = overlay_settings(current, bundle.apply_cli)
    after_wu2 = _wu2_overlay(current, bundle.apply_cli)
    for key in target:
        assert after_apply[key] == target[key], f"apply overlay {key}"
        assert after_wu2[key] == target[key], f"wu2 apply {key}"
    after_rollback = overlay_settings(target, bundle.rollback_cli)
    after_wu2_rb = _wu2_overlay(target, bundle.rollback_cli)
    for key in current:
        if key in bundle.changed_settings:
            assert after_rollback[key] == current[key], f"rollback overlay {key}"
            assert after_wu2_rb[key] == current[key], f"wu2 rollback {key}"
    parsed_apply = parse_authorized_cli(bundle.apply_cli)
    parsed_rb = parse_authorized_cli(bundle.rollback_cli)
    assert parsed_apply["profile"] == bundle.target_profile
    assert parsed_rb["profile"] == bundle.source_profile
    assert parsed_apply["settings"] == dict(bundle.changed_settings)
    assert parsed_rb["settings"] == {k: current[k] for k in bundle.changed_settings}


def test_apply_and_rollback_roundtrip_pid():
    _assert_roundtrip(pass_with_delta("slider_pi_gain"))


def test_apply_and_rollback_roundtrip_ff():
    _assert_roundtrip(pass_with_delta("slider_feedforward_gain"))


def test_apply_and_rollback_roundtrip_filters():
    _assert_roundtrip(pass_with_delta("slider_dterm_filter_multiplier"))


def test_apply_and_rollback_roundtrip_all():
    _assert_roundtrip(
        pipeline(
            sliders(
                100,
                slider_pi_gain=108,
                slider_d_gain=106,
                slider_feedforward_gain=106,
                slider_dterm_filter_multiplier=101,
            )
        )
    )


def test_apply_and_rollback_roundtrip_dmax():
    final = run_safety_pipeline(proposal_with_dmax_delta(4), analysis=clean_analysis())
    _assert_roundtrip(final)


def test_wu2_parse_cli_dump_profile_and_pid():
    final = pass_with_delta("slider_pi_gain")
    auth = authorize_cli(final)
    parsed = parse_cli_dump(auth.bundle.apply_cli)
    assert parsed["meta"]["pid_profile"] == auth.bundle.target_profile
    assert parsed["pid"]["roll"]["p"] == auth.bundle.changed_settings["p_roll"]
    assert flatten_absolute_tune(final.clamped_tune)["p_roll"] == parsed["pid"]["roll"]["p"]
