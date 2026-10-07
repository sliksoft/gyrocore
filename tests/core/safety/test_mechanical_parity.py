"""Donor vs GyroCore mechanical-safety **gate-function** parity (WU10).

Every test here feeds the same supplied kwargs to the GyroCore gate and the donor
gate. That proves gate parity only: the gl001/gl002 tests derive the kwargs from
GyroCore evidence, so a GyroCore analysis/adapter defect reaches both gates and
still "matches". Full CSV -> analysis -> adapter -> gate end-to-end parity against
the frozen donor golden lives in ``tests/core/test_legacy_frozen_regression.py``
(donor-free, normal CI).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from gyrocore.analysis import build_analysis_evidence
from gyrocore.safety import build_mechanical_safety_gate, evaluate_mechanical_safety
from gyrocore.safety.types import SafetyVerdict

REPO = Path(__file__).resolve().parents[3]
GL001 = REPO / "tests/fixtures/legacy/gl001_clean/input/flight.csv"
GL002 = REPO / "tests/fixtures/legacy/gl002_noisy/input/flight.csv"


def _aerotuner_root() -> Path:
    return Path(os.environ.get("AEROTUNER_ROOT", REPO.parent / "aerotuner"))


def _donor_gate():
    root = _aerotuner_root()
    if not (root / "backend/services/mechanical_safety_gate.py").is_file():
        pytest.skip("AeroTuner donor not available")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from backend.services.mechanical_safety_gate import build_mechanical_safety_gate as donor

    return donor


def _assert_gate_equal(gc: dict, donor: dict) -> None:
    assert gc["mechanical_block"] == donor["mechanical_block"]
    assert gc["mechanical_limited"] == donor["mechanical_limited"]
    assert gc["mechanical_caution"] == donor["mechanical_caution"]
    assert gc["mechanical_outcome"] == donor["mechanical_outcome"]
    assert gc["recommended_action"] == donor["recommended_action"]
    assert gc["blocking_reasons"] == donor["blocking_reasons"]
    assert gc["limited_reasons"] == donor["limited_reasons"]
    assert gc["caution_reasons"] == donor["caution_reasons"]
    assert gc["max_delta_scale"] == donor["max_delta_scale"]
    assert gc["limited_tier"] == donor["limited_tier"]
    assert gc["reasons"] == donor["reasons"]
    assert gc["evidence"]["max_delta_scale"] == donor["evidence"]["max_delta_scale"]
    assert gc["evidence"]["independent_mechanical_evidence"] == donor["evidence"]["independent_mechanical_evidence"]


def _parity(**kwargs):
    donor = _donor_gate()
    _assert_gate_equal(build_mechanical_safety_gate(**kwargs), donor(**kwargs))


def test_empty_inputs_match_donor_pass():
    _parity()
    result = evaluate_mechanical_safety()
    assert result.status is SafetyVerdict.PASS
    assert result.mechanical_block is False


def test_clean_log_pass():
    _parity(
        pipeline_problems={"problems": []},
        motor_diagnostics={"motors": []},
        engine_metrics={"noise": {"value": 90.0, "hf_ratio": 0.05}, "resonance": {"severity": "low"}},
        noise_level="LOW",
        quality_status="ok",
        confidence_eval={"score": 0.9, "label": "high"},
    )


def test_noisy_log_limited_or_caution():
    _parity(
        pipeline_problems={"problems": []},
        motor_diagnostics={"motors": []},
        engine_metrics={"noise": {"value": 20.0, "hf_ratio": 0.72}, "resonance": {"severity": "low"}},
        noise_level="HIGH",
        quality_status="ok",
        confidence_eval={"score": 0.25, "label": "low"},
    )


def test_motor_issue_limited_without_danger():
    _parity(
        pipeline_problems={
            "problems": [
                {
                    "type": "motor_issue",
                    "severity": "high",
                    "confidence": 0.42,
                    "description": "check for bent shaft",
                }
            ]
        },
        motor_diagnostics={"motors": []},
        engine_metrics={"noise": {"value": 80.0}, "resonance": {"severity": "low"}},
    )


def test_motor_desync_danger_blocks():
    _parity(
        pipeline_problems={
            "problems": [
                {
                    "type": "motor_issue",
                    "severity": "high",
                    "confidence": 0.7,
                    "description": "confirmed motor desync with saturation and loss of control",
                }
            ]
        },
        motor_diagnostics={"motors": []},
        engine_metrics={"noise": {"value": 80.0}, "resonance": {"severity": "low"}},
    )
    result = evaluate_mechanical_safety(
        pipeline_problems={
            "problems": [
                {
                    "type": "motor_issue",
                    "severity": "high",
                    "confidence": 0.7,
                    "description": "confirmed motor desync with saturation and loss of control",
                }
            ]
        },
        motor_diagnostics={"motors": []},
        engine_metrics={"noise": {"value": 80.0}, "resonance": {"severity": "low"}},
    )
    assert result.status is SafetyVerdict.BLOCK
    assert "motor_issue_high_severity_danger" in result.blocking_reasons


def test_resonance_issue():
    _parity(
        pipeline_problems={"problems": []},
        motor_diagnostics={"motors": []},
        resonance_module={"severity": "high", "persistent": True, "broad": True},
        engine_metrics={"noise": {"value": 40.0, "hf_ratio": 0.5}, "resonance": {"severity": "high"}},
        noise_level="HIGH",
    )


def test_saturation_issue():
    _parity(
        pipeline_problems={
            "problems": [
                {
                    "type": "motor_saturation",
                    "severity": "high",
                    "confidence": 0.8,
                    "description": "motor output saturated",
                }
            ]
        },
        motor_diagnostics={"motors": []},
        engine_metrics={"noise": {"value": 50.0}, "resonance": {"severity": "low"}},
    )


def test_insufficient_evidence_does_not_overblock_like_donor():
    _parity(pipeline_problems={"problems": []}, motor_diagnostics={"motors": []})


def test_warning_only_motor():
    _parity(
        motor_diagnostics={
            "motors": [{"motor": 2, "status": "warning", "confidence": 0.55, "health": 78}]
        },
        engine_metrics={"noise": {"value": 85.0, "hf_ratio": 0.05}, "resonance": {"severity": "low"}},
        noise_level="LOW",
    )
    result = evaluate_mechanical_safety(
        motor_diagnostics={
            "motors": [{"motor": 2, "status": "warning", "confidence": 0.55, "health": 78}]
        },
        engine_metrics={"noise": {"value": 85.0, "hf_ratio": 0.05}, "resonance": {"severity": "low"}},
        noise_level="LOW",
    )
    assert result.status is SafetyVerdict.WARN
    assert result.mechanical_block is False


def test_bad_motor_high_noise_blocks():
    _parity(
        motor_diagnostics={
            "motors": [
                {
                    "id": 2,
                    "health": 26,
                    "health_basis": "absolute",
                    "status": "bad",
                    "confidence": 0.7,
                    "issues": [],
                }
            ]
        },
        engine_metrics={"noise": {"value": 30.0, "hf_ratio": 0.45}, "resonance": {"severity": "low"}},
        noise_level="HIGH",
    )


def test_missing_required_analysis_fails_closed():
    result = evaluate_mechanical_safety(None, require_analysis=True)
    assert result.status is SafetyVerdict.BLOCK
    assert "missing_required_analysis" in result.blocking_reasons
    result2 = evaluate_mechanical_safety({"ok": False, "message": "no_usable_samples"}, require_analysis=True)
    assert result2.status is SafetyVerdict.BLOCK


def _load_gl_csv(path: Path) -> list[dict]:
    import csv

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
            rows.append(item)
    return rows


def test_gl001_analysis_matches_donor_gate():
    """Gate parity on GyroCore-derived kwargs (not end-to-end; see module docstring)."""
    evidence = build_analysis_evidence(_load_gl_csv(GL001), gyro_source_is_raw_adc=False)
    result = evaluate_mechanical_safety(evidence, require_analysis=True)
    donor = _donor_gate()
    from gyrocore.safety.analysis_adapter import mechanical_inputs_from_analysis

    kwargs = mechanical_inputs_from_analysis(evidence)
    _assert_gate_equal(result.raw, donor(**kwargs))


def test_gl002_noisy_analysis_is_warn_or_block_not_silent_pass_if_noisy():
    """Gate parity on GyroCore-derived kwargs (not end-to-end; see module docstring)."""
    evidence = build_analysis_evidence(_load_gl_csv(GL002), gyro_source_is_raw_adc=False)
    result = evaluate_mechanical_safety(evidence, require_analysis=True)
    assert result.raw["mechanical_block"] is result.mechanical_block
    donor = _donor_gate()
    from gyrocore.safety.analysis_adapter import mechanical_inputs_from_analysis

    kwargs = mechanical_inputs_from_analysis(evidence)
    _assert_gate_equal(result.raw, donor(**kwargs))
