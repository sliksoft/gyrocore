"""WU4 preprocess + analysis unit tests."""

from __future__ import annotations

import ast
import csv
import importlib
import math
import sys
from pathlib import Path

import pytest

import gyrocore
from gyrocore.analysis import build_analysis_evidence
from gyrocore.preprocess import (
    infer_sample_rate_hz,
    normalize_raw_samples,
    select_best_flight_for_analysis,
)

REPO = Path(__file__).resolve().parents[2]
GL001 = REPO / "tests/fixtures/legacy/gl001_clean/input/flight.csv"
GL002 = REPO / "tests/fixtures/legacy/gl002_noisy/input/flight.csv"

FORBIDDEN = {"fastapi", "starlette", "redis", "sqlalchemy", "jwt", "jose", "uvicorn"}
TUNING_FORBIDDEN = {
    "tuning_engine_v2",
    "tuning_safe_v2",
    "safe_pid_tuning",
    "smart_filter_tuning",
    "tuning_decision_assembler",
    "tuning_output_safety",
    "mechanical_safety_gate",
}


def _load_gl_csv(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            item: dict = {
                "t": float(row["t"]),
                "gx": float(row["gx"]),
                "gy": float(row["gy"]),
                "gz": float(row["gz"]),
            }
            if row.get("throttle") not in (None, ""):
                item["throttle"] = float(row["throttle"])
            motors = []
            for key in ("m0", "m1", "m2", "m3"):
                if row.get(key) not in (None, ""):
                    motors.append(float(row[key]))
            if len(motors) == 4:
                item["motors"] = motors
            for key in ("setpoint_roll", "setpoint_pitch", "setpoint_yaw"):
                if row.get(key) not in (None, ""):
                    item[key] = float(row[key])
            rows.append(item)
    return rows


def test_package_exports_analysis_preprocess():
    assert hasattr(gyrocore, "analysis")
    assert hasattr(gyrocore, "preprocess")
    assert hasattr(gyrocore.analysis, "build_analysis_evidence")


def test_normalize_and_flight_selection_gl001():
    raw = _load_gl_csv(GL001)
    norm, meta = normalize_raw_samples(raw, gyro_source_is_raw_adc=False)
    assert len(norm) == len(raw)
    assert meta["gyro_applied_scale"] == 1.0
    selected, quality, count, idx = select_best_flight_for_analysis(norm)
    assert len(selected) == len(norm)
    assert count == 1
    assert idx == 0
    assert "score" in quality
    sr = infer_sample_rate_hz(selected)
    assert 50.0 < sr < 5000.0


def test_build_analysis_evidence_gl001_and_gl002():
    for path in (GL001, GL002):
        evidence = build_analysis_evidence(
            _load_gl_csv(path),
            gyro_source_is_raw_adc=False,
        )
        assert evidence["ok"] is True
        assert evidence["quality"] is not None
        assert evidence["spectral"] is not None
        assert evidence["resonance"] is not None
        assert evidence["erpm"] is not None
        assert evidence["step_response"] is not None
        assert evidence["d_effectiveness"] is not None
        assert evidence["problems"] is not None
        assert evidence["sample_rate_hz"] > 0
        # Hard scope: no tune outputs
        blob = str(evidence.keys())
        assert "cli" not in blob.lower() or "headers" in blob.lower()
        assert "pid_targets" not in evidence
        assert "filter_targets" not in evidence
        assert "generated_cli" not in evidence


def test_empty_samples_outcome():
    out = build_analysis_evidence([])
    assert out["ok"] is False
    assert out["message"] == "no_usable_samples"


def test_analysis_does_not_import_tuning():
    root = Path(__file__).resolve().parents[2] / "core" / "gyrocore"
    for sub in ("analysis", "preprocess"):
        for path in (root / sub).rglob("*.py"):
            if path.name == "PROVENANCE.txt":
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = []
                    if isinstance(node, ast.Import):
                        names = [a.name for a in node.names]
                    elif node.module:
                        names = [node.module]
                    for name in names:
                        for banned in TUNING_FORBIDDEN:
                            assert banned not in name, f"{path}: imports {name}"


def test_dependency_boundary_runtime():
    before = set(sys.modules)
    importlib.reload(gyrocore.analysis)
    importlib.reload(gyrocore.preprocess)
    after = set(sys.modules)
    newly = after - before
    offenders = sorted(n for n in newly if n.split(".")[0] in FORBIDDEN)
    assert offenders == []
    for name in list(sys.modules):
        if name.startswith("gyrocore.analysis") or name.startswith("gyrocore.preprocess"):
            mod = sys.modules[name]
            file = getattr(mod, "__file__", "") or ""
            assert "/aerotuner/" not in file.replace("\\", "/")
            assert "fastapi" not in file
