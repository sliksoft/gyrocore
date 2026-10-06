"""WU12 desktop worker bridge + architecture guards."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "apps" / "desktop" / "worker" / "gyrocore_worker.py"
DESKTOP_UI = ROOT / "apps" / "desktop" / "gyrocore-app" / "src"
WORKER_PKG = ROOT / "apps" / "desktop" / "worker"


def _call(op: str, params: dict | None = None) -> dict:
    import os

    req = json.dumps({"id": "t", "op": op, "params": params or {}}) + "\n"
    py = os.environ.get("GYROCORE_PYTHON") or sys.executable
    env = {**os.environ, "PYTHONPATH": f"{ROOT}:{ROOT / 'core'}"}
    out = subprocess.check_output(
        [py, str(WORKER)],
        input=req.encode(),
        cwd=str(ROOT),
        env=env,
    )
    return json.loads(out.decode().strip().splitlines()[-1])


def test_worker_ping():
    raw = _call("ping")
    assert raw["ok"] is True
    assert raw["result"]["pong"] is True


def test_demo_pass_authorized_cli():
    raw = _call("demo", {"scenario": "pass"})
    assert raw["ok"]
    cli = raw["result"]["cli"]
    assert cli["authorized"] is True
    assert "apply_cli" in cli and "rollback_cli" in cli
    assert "save" in cli["apply_cli"]
    assert raw["result"]["controls"]["fc_apply_button"] is False


def test_demo_warn_preview_not_actionable():
    raw = _call("demo", {"scenario": "warn"})
    cli = raw["result"]["cli"]
    assert cli["authorized"] is False
    assert cli["actionable"] is False
    assert "preview_cli" in cli
    assert "apply_cli" not in cli


def test_demo_block_no_cli():
    raw = _call("demo", {"scenario": "block"})
    cli = raw["result"]["cli"]
    assert cli["state"] == "denied"
    assert "apply_cli" not in cli
    assert "preview_cli" not in cli


def test_demo_no_chirp():
    raw = _call("demo", {"scenario": "no_chirp"})
    assert raw["result"]["chirp"]["available"] is False


def test_demo_merge_review():
    raw = _call("demo", {"scenario": "merge_review"})
    assert raw["result"]["overview"]["final_safety"] == "BLOCK"
    assert raw["result"]["cli"]["authorized"] is False


def test_ui_has_no_fc_apply_or_msp():
    forbidden = ("MSP_SET", "serial.Serial", "applyToFc", "sendMsp")
    for path in DESKTOP_UI.rglob("*"):
        if path.suffix not in {".ts", ".tsx", ".js", ".jsx"}:
            continue
        if path.name.endswith(".test.tsx") or path.name.endswith(".test.ts"):
            continue
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path} contains {token}"
        # Production UI must not offer an FC apply control.
        assert "Apply to FC" not in text or "No Apply to FC" in text, f"{path} may expose FC apply"


def test_worker_has_no_http_server():
    forbidden = ("FastAPI", "flask", "uvicorn", "redis", "SQLAlchemy")
    for path in WORKER_PKG.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        blob = ast.dump(tree)
        for name in forbidden:
            assert name not in blob


def test_worker_does_not_reimplement_safety_math():
    """Desktop worker must call Core authorize_cli / run_safety_pipeline."""
    demo = (WORKER_PKG / "demo_scenarios.py").read_text(encoding="utf-8")
    assert "authorize_cli" in demo
    assert "run_safety_pipeline" in demo
    assert "def recommend_gains" not in demo
    assert "def apply_simplified_tuning" not in demo


def test_invalid_file_inspect():
    raw = _call("inspect", {"path": "/no/such/file.bbl"})
    assert raw["ok"] is False
    assert raw["error"]["code"] == "invalid_input"
