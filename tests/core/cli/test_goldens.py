"""Deterministic WU11 CLI goldens. Do not overwrite WU0 goldens."""

from __future__ import annotations

from gyrocore.cli import authorize_cli
from gyrocore.cli.emit import parse_authorized_cli
from gyrocore.safety import run_safety_pipeline
from tests.core.cli.helpers import (
    GOLDEN_DIR,
    clean_analysis,
    pipeline,
    profile_cli,
    proposal_with_dmax_delta,
    sliders,
)


def _read(name: str) -> str:
    return (GOLDEN_DIR / name).read_text(encoding="utf-8")


def _assert_golden(name: str, text: str) -> None:
    expected = _read(name)
    assert text == expected, f"{name} drifted:\n--- expected ---\n{expected}\n--- actual ---\n{text}"


def test_golden_basic_pid():
    auth = authorize_cli(pipeline(sliders(100, slider_pi_gain=108)))
    assert auth.authorized
    _assert_golden("basic_pid.apply.cli", auth.bundle.apply_cli)
    _assert_golden("basic_pid.rollback.cli", auth.bundle.rollback_cli)


def test_golden_pid_ff():
    auth = authorize_cli(pipeline(sliders(100, slider_pi_gain=108, slider_feedforward_gain=106)))
    assert auth.authorized
    _assert_golden("pid_ff.apply.cli", auth.bundle.apply_cli)
    _assert_golden("pid_ff.rollback.cli", auth.bundle.rollback_cli)


def test_golden_pid_filters():
    auth = authorize_cli(pipeline(sliders(100, slider_pi_gain=108, slider_dterm_filter_multiplier=101)))
    assert auth.authorized
    _assert_golden("pid_filters.apply.cli", auth.bundle.apply_cli)
    _assert_golden("pid_filters.rollback.cli", auth.bundle.rollback_cli)


def test_golden_all_supported_changed():
    auth = authorize_cli(
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
    assert auth.authorized
    _assert_golden("all_supported.apply.cli", auth.bundle.apply_cli)
    _assert_golden("all_supported.rollback.cli", auth.bundle.rollback_cli)
    parsed = parse_authorized_cli(auth.bundle.apply_cli)
    assert parsed["save"] is True
    assert parsed["profile"] == 0


def test_golden_profile_selection():
    auth = authorize_cli(pipeline(sliders(100, slider_pi_gain=108), cli=profile_cli(2)))
    assert auth.authorized
    _assert_golden("profile_2.apply.cli", auth.bundle.apply_cli)
    _assert_golden("profile_2.rollback.cli", auth.bundle.rollback_cli)
    assert auth.bundle.apply_cli.startswith("profile 2\n")


def test_golden_rollback_pair_dmax():
    final = run_safety_pipeline(proposal_with_dmax_delta(4), analysis=clean_analysis())
    auth = authorize_cli(final)
    assert auth.authorized
    _assert_golden("dmax.apply.cli", auth.bundle.apply_cli)
    _assert_golden("dmax.rollback.cli", auth.bundle.rollback_cli)
