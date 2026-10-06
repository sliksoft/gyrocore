"""WU1 foundation tests: models, config, errors, dependency boundary."""

from __future__ import annotations

import ast
import copy
import importlib
import sys
from pathlib import Path

import pytest

import gyrocore
from gyrocore import (
    AnalyzeOptions,
    AnalyzeRequest,
    AnalyzeResult,
    CoreConfig,
    FirmwareContext,
    FlightSelection,
    GyroCoreError,
    HardwareContext,
    InvalidInputError,
    MechanicalSafetyView,
    TuningOutputSafetyStatus,
    TuningOutputSafetyView,
    actionable_cli_allowed,
)
from gyrocore.errors import (
    AnalysisError,
    ConfigurationError,
    DecodeError,
    ParseError,
    SafetyBlockedError,
    UnsupportedFirmwareError,
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
    "react",
    "electron",
    "tauri",
}


def test_core_package_imports():
    assert gyrocore.__version__ == "0.1.0"
    assert hasattr(gyrocore, "AnalyzeRequest")
    assert hasattr(gyrocore, "CoreConfig")
    assert hasattr(gyrocore, "betaflight")
    assert hasattr(gyrocore, "decode")
    assert hasattr(gyrocore, "parse")
    assert not hasattr(gyrocore, "GyroCore")  # no placeholder analyze API yet


def test_analyze_request_accepts_bbl_path_without_session_id():
    req = AnalyzeRequest(
        bbl_path="/home/user/flights/test.BBL",
        cli_text="set p_roll = 40\n",
        firmware=FirmwareContext(firmware="Betaflight 4.5.0", board_name="BETAFPVG473"),
        hardware=HardwareContext(payload={"motor_poles": 12, "battery": "1S"}),
        flight=FlightSelection(selected_flight_index=0),
        options=AnalyzeOptions(ai_enabled=False, style="Racing", goals=("racing_aggressive",)),
    )
    assert req.bbl_path == "/home/user/flights/test.BBL"
    assert req.has_cli is True
    assert not hasattr(req, "session_id")
    assert "session_id" not in req.__dataclass_fields__
    ui = req.legacy_user_inputs()
    assert ui["hardware"]["motor_poles"] == 12
    assert ui["style"] == "Racing"


def test_analyze_request_accepts_samples():
    samples = [{"t": 0, "gx": 1.0, "gy": 0.0, "gz": 0.0}]
    req = AnalyzeRequest(samples=samples)
    assert req.samples is samples
    assert req.bbl_path is None


def test_analyze_request_rejects_both_or_neither():
    with pytest.raises(InvalidInputError):
        AnalyzeRequest()
    with pytest.raises(InvalidInputError):
        AnalyzeRequest(bbl_path="/x.BBL", samples=[{"t": 0}])


def test_core_config_defaults_and_validation():
    cfg = CoreConfig.defaults()
    assert cfg.ai_enabled is False
    assert cfg.allow_arbitrary_local_paths is True
    assert cfg.decode_timeout_s > 0
    oracle = CoreConfig.for_deterministic_oracle()
    assert oracle.ai_enabled is False
    with pytest.raises(ConfigurationError):
        CoreConfig(decode_timeout_s=0)
    updated = cfg.with_updates(blackbox_decode_path="/usr/local/bin/blackbox_decode")
    assert updated.blackbox_decode_path == "/usr/local/bin/blackbox_decode"
    assert cfg.blackbox_decode_path is None


def test_error_hierarchy():
    assert issubclass(InvalidInputError, GyroCoreError)
    assert issubclass(DecodeError, GyroCoreError)
    assert issubclass(ParseError, GyroCoreError)
    assert issubclass(UnsupportedFirmwareError, GyroCoreError)
    assert issubclass(AnalysisError, GyroCoreError)
    assert issubclass(SafetyBlockedError, GyroCoreError)
    assert issubclass(ConfigurationError, GyroCoreError)
    assert issubclass(InvalidInputError, ValueError)


def test_safety_status_and_actionable_cli_helper():
    blocked = TuningOutputSafetyView.from_legacy(
        {
            "status": "blocked",
            "cli_actionable": False,
            "present": True,
            "blocking_reasons": ["safe_tune_v2_skipped"],
            "mechanical": {"mechanical_block": False, "mechanical_outcome": "clear"},
        }
    )
    assert blocked.status is TuningOutputSafetyStatus.BLOCKED
    assert blocked.allows_actionable_cli() is False
    assert actionable_cli_allowed(blocked) is False
    assert actionable_cli_allowed(None) is False

    actionable = TuningOutputSafetyView.from_legacy(
        {
            "status": "actionable",
            "cli_actionable": True,
            "cli_availability": "paste_ready",
            "present": True,
            "mechanical": {"mechanical_block": False},
        }
    )
    assert actionable_cli_allowed(actionable) is True

    # Blocked + claimed actionable fails closed.
    inconsistent = TuningOutputSafetyView.from_legacy(
        {"status": "blocked", "cli_actionable": True, "present": True}
    )
    assert actionable_cli_allowed(inconsistent) is False


def test_analyze_result_preserves_domain_without_mutation():
    domain = {
        "analysis_status": "ok",
        "authoritative_cli": "set p_roll = 40\nsave",
        "tuning_output_safety": {
            "status": "actionable",
            "cli_actionable": True,
            "present": True,
        },
        "mechanical_safety": {
            "mechanical_block": False,
            "mechanical_outcome": "clear",
            "status": "ok",
        },
    }
    original = copy.deepcopy(domain)
    result = AnalyzeResult.from_domain(domain)
    domain["analysis_status"] = "mutated"
    domain["tuning_output_safety"]["cli_actionable"] = False
    assert result.domain["analysis_status"] == "ok"
    assert result.cli_is_actionable() is True
    assert result.authoritative_cli.startswith("set p_roll")
    assert result.mechanical_safety.mechanical_block is False
    # domain_copy is independent
    copied = result.domain_copy()
    copied["analysis_status"] = "x"
    assert result.analysis_status == "ok"
    assert original["analysis_status"] == "ok"


def test_mechanical_safety_view_from_legacy():
    view = MechanicalSafetyView.from_legacy(
        {
            "mechanical_block": True,
            "mechanical_limited": False,
            "mechanical_outcome": "mechanical_block",
            "reasons": ["dangerous_flight_event"],
            "blocking_reasons": ["dangerous_flight_event"],
        }
    )
    assert view.mechanical_block is True
    assert "dangerous_flight_event" in view.blocking_reasons


def _iter_package_py_files() -> list[Path]:
    root = Path(__file__).resolve().parents[2] / "core" / "gyrocore"
    return sorted(root.rglob("*.py"))


def test_dependency_boundary_no_forbidden_imports_in_source():
    """Static AST check: Core source must not import forbidden packages."""
    forbidden_hits: list[str] = []
    for path in _iter_package_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top in FORBIDDEN_TOP_LEVEL:
                        forbidden_hits.append(f"{path.name}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                top = node.module.split(".")[0]
                if top in FORBIDDEN_TOP_LEVEL:
                    forbidden_hits.append(f"{path.name}: from {node.module}")
    assert forbidden_hits == []


def test_dependency_boundary_import_does_not_load_forbidden_modules():
    # Re-import in isolation of names; record modules present after import.
    before = set(sys.modules)
    importlib.reload(gyrocore)
    after = set(sys.modules)
    newly = after - before
    offenders = sorted(
        name
        for name in newly
        if name.split(".")[0] in FORBIDDEN_TOP_LEVEL
    )
    # Also ensure forbidden names are not loaded as side effect if already present —
    # the package itself must not require them. Check gyrocore submodule graph only.
    gyro_modules = [
        mod for name, mod in sys.modules.items() if name == "gyrocore" or name.startswith("gyrocore.")
    ]
    for mod in gyro_modules:
        file = getattr(mod, "__file__", None) or ""
        assert "fastapi" not in file
        assert "redis" not in file
    assert offenders == []
