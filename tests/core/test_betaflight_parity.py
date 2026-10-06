"""Donor-vs-GyroCore parity tests for WU2 Betaflight/CLI foundation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from gyrocore.betaflight import (
    build_effective_config,
    classify_betaflight_version,
    classify_firmware_metadata,
    cli_dump_baseline_strictly_valid,
    effective_current_tune_baseline,
    load_betaflight_defaults,
    load_target_defaults,
    parse_cli_baseline_with_profile_isolation,
    parse_cli_dump,
    parse_cli_profile_blocks,
    resolve_support_matrix_policy,
    tuning_profile_cli_strictly_valid,
    validate_config_log_consistency,
)
from gyrocore.betaflight.parser import empty_tuning_profile, parse_tuning_headers

REPO = Path(__file__).resolve().parents[2]
WHOOP_CLI = REPO / "tests/fixtures/legacy/whoop75_cli_snapshot/input/cli.txt"


def _donor_root() -> Path:
    env = os.environ.get("AEROTUNER_ROOT")
    if env:
        return Path(env)
    return REPO.parent / "aerotuner"


@pytest.fixture(scope="module")
def donor():
    root = _donor_root()
    if not root.is_dir():
        pytest.skip(f"AeroTuner donor not available at {root}")
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    import backend.services.betaflight_version_support as d_version
    import backend.services.betaflight_defaults as d_defaults
    import backend.services.betaflight_target_defaults as d_target
    import backend.services.tuning_safe_v2 as d_tsv
    import backend.services.cli_profile_resolver as d_profile
    import backend.services.effective_config_builder as d_eff
    import backend.services.config_log_consistency_validator as d_cons
    import backend.services.current_tune_baseline as d_base
    import backend.services.support_matrix_policy as d_support
    import backend.services.tuning_parser as d_parser

    return {
        "version": d_version,
        "defaults": d_defaults,
        "target": d_target,
        "tsv": d_tsv,
        "profile": d_profile,
        "eff": d_eff,
        "cons": d_cons,
        "base": d_base,
        "support": d_support,
        "parser": d_parser,
    }


SAMPLE_CLI = """
board_name BETAFPVG473
manufacturer_id BEFH
profile 0
set p_roll = 42
set i_roll = 80
set d_roll = 28
set f_roll = 100
set p_pitch = 46
set i_pitch = 84
set d_pitch = 30
set f_pitch = 105
set p_yaw = 50
set i_yaw = 90
set d_yaw = 0
set f_yaw = 90
set gyro_lpf1_static_hz = 0
set gyro_lpf2_static_hz = 500
set dterm_lpf1_dyn_min_hz = 75
set dterm_lpf1_dyn_max_hz = 150
set dterm_lpf2_static_hz = 150
set dyn_notch_count = 3
set dyn_notch_min_hz = 100
set dyn_notch_max_hz = 600
set rpm_filter = ON
set motor_poles = 12
set anti_gravity_gain = 80
"""


def _assert_equal(a: Any, b: Any, *, label: str) -> None:
    assert a == b, f"{label}: core={a!r} donor={b!r}"


def test_parity_cli_parse_and_baseline_valid(donor):
    core = parse_cli_dump(SAMPLE_CLI)
    don = donor["tsv"].parse_cli_dump(SAMPLE_CLI)
    _assert_equal(core, don, label="parse_cli_dump")
    _assert_equal(
        cli_dump_baseline_strictly_valid(SAMPLE_CLI),
        donor["tsv"].cli_dump_baseline_strictly_valid(SAMPLE_CLI),
        label="cli_dump_baseline_strictly_valid",
    )


def test_parity_whoop_cli(donor):
    text = WHOOP_CLI.read_text(encoding="utf-8", errors="replace")
    _assert_equal(parse_cli_dump(text), donor["tsv"].parse_cli_dump(text), label="whoop parse")
    _assert_equal(
        cli_dump_baseline_strictly_valid(text),
        donor["tsv"].cli_dump_baseline_strictly_valid(text),
        label="whoop valid",
    )


def test_parity_firmware_classification(donor):
    cases = [None, "", "4.5.0", "4.5.2", "BTFL 4.5.2 STM32F7X2", "4.4.3", "4.6.0", "2025.12.4", "3.5.7", "nope"]
    for value in cases:
        _assert_equal(
            classify_betaflight_version(value),
            donor["version"].classify_betaflight_version(value),
            label=f"classify_betaflight_version({value!r})",
        )
    meta = {"name": "Betaflight", "version": "4.5.0", "board": "BETAFPVG473"}
    _assert_equal(
        classify_firmware_metadata(meta),
        donor["version"].classify_firmware_metadata(meta),
        label="classify_firmware_metadata",
    )


def test_parity_defaults_and_target_overlays(donor):
    support = classify_betaflight_version("4.5.0")
    _assert_equal(
        load_betaflight_defaults(support),
        donor["defaults"].load_betaflight_defaults(support),
        label="load_betaflight_defaults 4.5",
    )
    for ver in ("4.4.3", "4.6.0", "2025.12.4", None):
        s = classify_betaflight_version(ver)
        _assert_equal(
            load_betaflight_defaults(s),
            donor["defaults"].load_betaflight_defaults(s),
            label=f"defaults {ver!r}",
        )
    board = {"board_name": "BETAFPVG473", "manufacturer_id": "BEFH"}
    _assert_equal(
        load_target_defaults(board),
        donor["target"].load_target_defaults(board),
        label="load_target_defaults BETAFPVG473",
    )
    _assert_equal(
        load_target_defaults({"board_name": "NOT_A_REAL_TARGET_XYZ"}),
        donor["target"].load_target_defaults({"board_name": "NOT_A_REAL_TARGET_XYZ"}),
        label="load_target_defaults miss",
    )


def test_parity_profile_resolution(donor):
    text = WHOOP_CLI.read_text(encoding="utf-8", errors="replace")
    _assert_equal(
        parse_cli_profile_blocks(SAMPLE_CLI),
        donor["profile"].parse_cli_profile_blocks(SAMPLE_CLI),
        label="parse_cli_profile_blocks sample",
    )
    _assert_equal(
        parse_cli_profile_blocks(text),
        donor["profile"].parse_cli_profile_blocks(text),
        label="parse_cli_profile_blocks whoop",
    )
    _assert_equal(
        parse_cli_baseline_with_profile_isolation(text),
        donor["profile"].parse_cli_baseline_with_profile_isolation(text),
        label="parse_cli_baseline_with_profile_isolation whoop",
    )


def test_parity_effective_config(donor):
    text = WHOOP_CLI.read_text(encoding="utf-8", errors="replace")
    support = classify_betaflight_version("4.5.0")
    parsed = parse_cli_dump(text)
    board = {"board_name": "BETAFPVG473", "manufacturer_id": "BEFH"}
    core = build_effective_config(
        parsed, firmware_support=support, board_metadata=board, cli_text=text
    )
    don = donor["eff"].build_effective_config(
        parsed, firmware_support=support, board_metadata=board, cli_text=text
    )
    _assert_equal(core, don, label="build_effective_config whoop")


def test_parity_consistency_and_baseline(donor):
    text = SAMPLE_CLI
    support = classify_betaflight_version("4.5.0")
    parsed = parse_cli_dump(text)
    eff = build_effective_config(parsed, firmware_support=support, cli_text=text)
    kwargs = dict(
        parsed_cli_baseline_config=parsed,
        effective_baseline_config=eff["effective_baseline_config"],
        effective_config_summary=eff["effective_config_summary"],
        effective_config_evidence=eff["source_evidence"],
        firmware_support=support,
        bbl_metadata={"version": "4.3.0", "name": "Betaflight"},
    )
    _assert_equal(
        validate_config_log_consistency(**kwargs),
        donor["cons"].validate_config_log_consistency(**kwargs),
        label="validate_config_log_consistency",
    )
    uploaded = {
        "source": "uploaded_cli",
        "filters": dict(parsed["filters"]),
        "pid": dict(parsed["pid"]),
    }
    session = {"uploaded_cli_tune": uploaded}
    pkg = {
        "current_pid": parsed["pid"],
        "cli_baseline_config": parsed,
    }
    _assert_equal(
        effective_current_tune_baseline(session, pkg, None),
        donor["base"].effective_current_tune_baseline(session, pkg, None),
        label="effective_current_tune_baseline",
    )


def test_parity_support_matrix(donor):
    support = classify_betaflight_version("4.5.0")
    parsed = parse_cli_dump(SAMPLE_CLI)
    eff = build_effective_config(parsed, firmware_support=support, cli_text=SAMPLE_CLI)
    summary = eff["effective_config_summary"]
    # Pass explicit empty manifest via monkeypatch? resolve uses file path —
    # both should read their own default manifests; normalize by injecting summary-only path.
    # For parity of policy function itself, call with same inputs; real_log side may differ
    # if manifests differ. Force identical by temporarily aligning manifests is heavy —
    # instead compare after stripping real_log fields if they diverge only on path blockers.
    core = resolve_support_matrix_policy(support, summary, output_safety_passed=True)
    don = donor["support"].resolve_support_matrix_policy(
        support, summary, output_safety_passed=True
    )
    # Real-log proof may differ because default manifest roots differ; compare policy core.
    for key in (
        "backend_effective_support_level",
        "paste_ready_eligible",
        "displayed_support_level",
        "support_level",
        "engine_profile_used",
        "defaults_profile_used",
        "support_downgrade_reasons",
    ):
        _assert_equal(core.get(key), don.get(key), label=f"support_matrix.{key}")


def test_parity_tuning_profile_cli_valid(donor):
    empty = empty_tuning_profile()
    _assert_equal(
        tuning_profile_cli_strictly_valid(empty),
        donor["parser"].tuning_profile_cli_strictly_valid(empty),
        label="empty tuning valid",
    )
    headers = (
        "rollPID,42,80,28\n"
        "pitchPID,46,84,30\n"
        "yawPID,50,90,0\n"
        "gyro_lpf_hz,250\n"
    )
    # parse may differ on header key names; compare validity on constructed profiles
    prof = {
        "pid": {
            "roll": {"p": 42, "i": 80, "d": 28},
            "pitch": {"p": 46, "i": 84, "d": 30},
            "yaw": {"p": 50, "i": 90, "d": 0},
        },
        "filters": {"gyro_lpf1_static_hz": 250},
    }
    _assert_equal(
        tuning_profile_cli_strictly_valid(prof),
        donor["parser"].tuning_profile_cli_strictly_valid(prof),
        label="full tuning valid",
    )
    # header parse parity when possible
    _assert_equal(
        parse_tuning_headers(headers),
        donor["parser"].parse_tuning_headers(headers),
        label="parse_tuning_headers",
    )
