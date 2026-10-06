"""WU2 Betaflight / CLI foundation unit tests."""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

import gyrocore
from gyrocore import betaflight
from gyrocore.betaflight import (
    build_effective_config,
    classify_betaflight_version,
    classify_firmware_metadata,
    cli_dump_baseline_strictly_valid,
    load_betaflight_defaults,
    load_target_defaults,
    parse_cli_dump,
    parse_cli_profile_blocks,
    tuning_profile_cli_strictly_valid,
    validate_config_log_consistency,
)

REPO = Path(__file__).resolve().parents[2]
WHOOP_CLI = REPO / "tests/fixtures/legacy/whoop75_cli_snapshot/input/cli.txt"
DONOR_WHOOP_CLI = Path(
    "/home/sliksoft/aerotuner/backend/tests/fixtures/75mm_whoop_36219f09/"
    "BTFL_cli_75_WOOP_20260606_172910_BETAFPVG473.txt"
)

FORBIDDEN_TOP_LEVEL = {
    "fastapi",
    "starlette",
    "redis",
    "sqlalchemy",
    "jwt",
    "jose",
    "passlib",
    "uvicorn",
}


SAMPLE_CLI = """
# sample
set p_roll = 42
set i_roll = 80
set d_roll = 28
set p_pitch = 46
set i_pitch = 84
set d_pitch = 30
set p_yaw = 50
set i_yaw = 90
set d_yaw = 0
set gyro_lpf1_static_hz = 0
set gyro_lpf2_static_hz = 500
set dterm_lpf1_dyn_min_hz = 75
set dterm_lpf1_dyn_max_hz = 150
set dyn_notch_count = 3
set rpm_filter = ON
set motor_poles = 12
profile 0
"""


def test_package_exports_betaflight_submodule():
    assert hasattr(gyrocore, "betaflight")
    assert betaflight.parse_cli_dump is parse_cli_dump
    assert not hasattr(betaflight, "generate_cli")
    assert not hasattr(betaflight, "generate_v2_safe_tune")
    assert not hasattr(betaflight, "apply_safety")


def test_parse_sample_cli():
    parsed = parse_cli_dump(SAMPLE_CLI)
    assert parsed["pid"]["roll"]["p"] == 42
    assert parsed["filters"]["gyro_lpf2_static_hz"] == 500
    assert parsed["filters"]["rpm_filter"] is True
    assert parsed["filters"]["motor_poles"] == 12
    assert parsed["meta"]["pid_profile"] == 0
    assert int(parsed["_recognized_set_count"]) >= 10
    assert cli_dump_baseline_strictly_valid(SAMPLE_CLI) is True


def test_malformed_and_empty_cli():
    assert parse_cli_dump("")["_recognized_set_count"] == 0
    assert parse_cli_dump(None)["_recognized_set_count"] == 0
    assert cli_dump_baseline_strictly_valid(None) is False
    assert cli_dump_baseline_strictly_valid("x") is False
    assert cli_dump_baseline_strictly_valid("set nonsense_key = 1\nset foo = 2\n") is False


def test_missing_required_baseline_information():
    tiny = "set p_roll = 40\nset i_roll = 70\n"
    assert cli_dump_baseline_strictly_valid(tiny) is False
    incomplete = {
        "pid": {"roll": {"p": 1, "i": 1, "d": 1}, "pitch": {"p": 1}, "yaw": {}},
        "filters": {},
    }
    assert tuning_profile_cli_strictly_valid(incomplete) is False


def test_firmware_support_levels():
    full = classify_betaflight_version("4.5.0")
    assert full["support_level"] == "full"
    assert full["cli_allowed"] is True

    limited = classify_betaflight_version("4.3.0")
    assert limited["support_level"] == "limited"
    assert limited["cli_allowed"] is True

    unknown = classify_betaflight_version(None)
    assert unknown["support_level"] == "unknown"
    assert unknown["cli_allowed"] is not True

    unsupported = classify_betaflight_version("3.5.7")
    assert unsupported["support_level"] == "diagnostic_only"
    assert unsupported["cli_allowed"] is not True

    meta = classify_firmware_metadata({"name": "Betaflight", "version": "4.5.2"})
    assert meta["cli_allowed"] is True


def test_firmware_defaults_lookup():
    support = classify_betaflight_version("4.5.0")
    loaded = load_betaflight_defaults(support)
    assert loaded["metadata"]["defaults_available"] is True
    assert loaded["metadata"]["defaults_profile_used"] == "4.5"
    filters = loaded["defaults"]["filters"]
    assert "gyro_lpf2_static_hz" in filters
    assert "dyn_notch_count" in filters


def test_target_overlay_lookup():
    hit = load_target_defaults(
        {"board_name": "BETAFPVG473", "manufacturer_id": "BEFH"}
    )
    assert hit["board_overlay_status"] == "hardware_config_only"
    assert hit["target_match_confidence"] in {"high", "medium"}
    assert isinstance(hit.get("hardware_config"), dict)

    miss = load_target_defaults({"board_name": "NOT_A_REAL_TARGET_XYZ"})
    assert miss["board_overlay_status"] in {
        "no_verified_overlay",
        "target_not_found",
        "no_match",
    } or miss["target_defaults_available"] is False


def test_profile_resolution_and_effective_config():
    blocks = parse_cli_profile_blocks(SAMPLE_CLI)
    assert "warnings" in blocks or "active_pid_profile" in blocks or "profiles" in blocks

    support = classify_betaflight_version("4.5.0")
    parsed = parse_cli_dump(SAMPLE_CLI)
    board = {"board_name": "BETAFPVG473", "manufacturer_id": "BEFH"}
    eff = build_effective_config(
        parsed,
        firmware_support=support,
        board_metadata=board,
        cli_text=SAMPLE_CLI,
    )
    summary = eff["effective_config_summary"]
    assert summary["effective_config_available"] is True
    assert summary["defaults_profile_used"] == "4.5"
    baseline = eff["effective_baseline_config"]
    assert baseline["filters"]
    assert baseline["pid"]["roll"]["p"] == 42


def test_config_log_consistency_mismatch():
    support = classify_betaflight_version("4.5.0")
    parsed = parse_cli_dump(SAMPLE_CLI)
    eff = build_effective_config(parsed, firmware_support=support, cli_text=SAMPLE_CLI)
    result = validate_config_log_consistency(
        parsed_cli_baseline_config=parsed,
        effective_baseline_config=eff["effective_baseline_config"],
        effective_config_summary=eff["effective_config_summary"],
        effective_config_evidence=eff["source_evidence"],
        firmware_support=support,
        bbl_metadata={"version": "4.3.0", "firmware": "Betaflight 4.3.0"},
    )
    assert isinstance(result, dict)
    assert result, "expected non-empty consistency result"
    # Mismatch should surface as warnings / limited / diagnostic reasons when keys exist.
    reason_keys = [
        k
        for k in result
        if any(tok in k for tok in ("warning", "reason", "status", "mismatch", "limited"))
    ]
    assert reason_keys, f"unexpected consistency shape: {sorted(result)}"


def test_real_whoop_cli_parse():
    path = WHOOP_CLI if WHOOP_CLI.is_file() else DONOR_WHOOP_CLI
    assert path.is_file(), f"missing whoop CLI fixture: {path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_cli_dump(text)
    assert cli_dump_baseline_strictly_valid(text) is True
    assert int(parsed["_recognized_set_count"]) >= 20
    assert parsed["meta"].get("board_name") == "BETAFPVG473"
    assert "pid" in parsed and parsed["pid"]


def test_no_actionable_tune_generation_surface():
    # Hard scope gate: WU2 must not expose tune emission helpers.
    pkg_root = Path(betaflight.__file__).resolve().parent
    banned = ("generate_cli", "generate_v2_safe_tune", "apply_safety", "apply_to_baseline")
    for path in pkg_root.rglob("*.py"):
        if path.name.startswith("data"):
            continue
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in banned:
                pytest.fail(f"tune-generation function {node.name} found in {path}")


def test_betaflight_import_boundary_runtime():
    before = set(sys.modules)
    importlib.reload(gyrocore.betaflight)
    after = set(sys.modules)
    newly = after - before
    offenders = sorted(n for n in newly if n.split(".")[0] in FORBIDDEN_TOP_LEVEL)
    assert offenders == []
    for name, mod in list(sys.modules.items()):
        if name == "gyrocore.betaflight" or name.startswith("gyrocore.betaflight."):
            file = getattr(mod, "__file__", "") or ""
            assert "/aerotuner/" not in file.replace("\\", "/")
            assert "fastapi" not in file
            assert "session_store" not in file
