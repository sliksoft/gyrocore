"""Unit tests for WU0 parity harness (no AeroTuner runtime required for most cases)."""

from __future__ import annotations

import copy

import pytest

from tests.golden.compare import ParityMismatch, compare_projections
from tests.golden.normalize import normalize_cli_text
from tests.golden.projection import extract_domain_projection, strip_transport_fields
from tests.golden.safety import SafetyInvariantError, assert_safety_invariants


def _sample_response(**overrides):
    base = {
        "status": "ok",
        "quality_status": "ok",
        "grade": "B",
        "run_score": 80.0,
        "summary": {"valid_log": True, "grade": "B", "score": 80.0},
        "meta": {
            "session_id": "sess-123",
            "selected_flight_index": 0,
            "flight_count": 1,
            "flight_selection_mode": "auto",
        },
        "problems": {
            "problems": [
                {"type": "noise_issue", "severity": "medium"},
                {"type": "propwash", "severity": "low"},
            ]
        },
        "metrics": {
            "noise": {"value": 70.0, "hf_ratio": 0.2},
            "resonance": {"dominant_hz": 120.0, "severity": "low"},
            "propwash": {"confidence": 0.1},
            "motor": {"health": 90.0},
        },
        "erpm_analysis": {
            "dominant_frequency": 200.0,
            "erpm_sample_coverage": 0.5,
            "motor_poles": 14,
            "pole_pairs": 7,
        },
        "tuning": {
            "mode": "balanced",
            "pid": {"roll": {"p": 40, "i": 50, "d": 30}},
            "filters": {"gyro_lpf1_static_hz": 250, "motor_poles": 14},
            "cli": ["set gyro_lpf1_static_hz = 250", "save"],
        },
        "tuning_output_safety": {
            "status": "actionable",
            "cli_actionable": True,
            "cli_availability": "paste_ready",
            "blocking_reasons": [],
            "hard_block_reasons": [],
            "diagnostic_reasons": [],
            "reasons": [],
            "mechanical": {
                "mechanical_block": False,
                "mechanical_limited": False,
                "mechanical_caution": False,
                "mechanical_outcome": "clear",
                "severity": "ok",
                "reasons": [],
                "blocking_reasons": [],
                "limited_reasons": [],
            },
        },
        "tuning_decision": {"mode": "balanced", "status": "ok"},
        "result_view": {
            "hero": {"title": "Analysis Complete — CLI Ready", "tone": "positive"},
            "cards": {"readiness": {"status": "Ready", "tone": "good"}},
        },
        "explanation": {"summary": "AI prose should be ignored"},
        "session_id": "sess-123",
        "job_id": "job-9",
    }
    base.update(overrides)
    return base


def test_projection_strips_transport_fields():
    raw = {"session_id": "x", "job_id": "y", "status": "ok", "tuning_output_safety": {"present": True}}
    stripped = strip_transport_fields(raw)
    assert "session_id" not in stripped
    assert "job_id" not in stripped
    assert stripped["status"] == "ok"


def test_domain_projection_omits_ids_and_ai_prose():
    proj = extract_domain_projection(_sample_response(), ai_disabled=True)
    blob = str(proj)
    assert "sess-123" not in blob
    assert "job-9" not in blob
    assert "AI prose" not in blob
    assert proj["ai_disabled"] is True
    assert proj["authoritative_cli"] == "set gyro_lpf1_static_hz = 250\nsave"
    assert "noise_issue" in proj["problem_types"]


def test_cli_normalization_is_deterministic():
    a = normalize_cli_text("set foo = 1\r\n\nset bar = 2  \n")
    b = normalize_cli_text(["  set foo = 1 ", "set bar = 2"])
    assert a == b == "set foo = 1\nset bar = 2"


def test_tolerance_comparison_allows_small_metric_noise():
    expected = extract_domain_projection(_sample_response())
    actual = extract_domain_projection(
        _sample_response(
            metrics={
                "noise": {"value": 70.0004, "hf_ratio": 0.2000001},
                "resonance": {"dominant_hz": 120.2, "severity": "low"},
                "propwash": {"confidence": 0.1},
                "motor": {"health": 90.0},
            }
        )
    )
    assert compare_projections(expected, actual) == []


def test_changed_safety_status_fails_parity():
    expected = extract_domain_projection(_sample_response())
    blocked = _sample_response()
    blocked["tuning_output_safety"]["status"] = "blocked"
    blocked["tuning_output_safety"]["cli_actionable"] = False
    actual = extract_domain_projection(blocked)
    with pytest.raises(ParityMismatch):
        compare_projections(expected, actual)


def test_changed_authoritative_cli_fails_parity():
    expected = extract_domain_projection(_sample_response())
    changed = _sample_response()
    changed["tuning"]["cli"] = ["set gyro_lpf1_static_hz = 999", "save"]
    actual = extract_domain_projection(changed)
    with pytest.raises(ParityMismatch):
        compare_projections(expected, actual)


def test_missing_tuning_output_safety_fails_invariant():
    proj = extract_domain_projection(_sample_response())
    proj["tuning_output_safety"] = {"present": False}
    with pytest.raises(SafetyInvariantError):
        assert_safety_invariants(proj)


def test_blocked_cli_cannot_be_actionable():
    resp = _sample_response()
    resp["tuning_output_safety"]["status"] = "blocked"
    resp["tuning_output_safety"]["cli_actionable"] = True
    proj = extract_domain_projection(resp)
    with pytest.raises(SafetyInvariantError):
        assert_safety_invariants(proj)


def test_unchanged_frozen_projection_passes():
    expected = extract_domain_projection(_sample_response())
    actual = extract_domain_projection(copy.deepcopy(_sample_response()))
    assert compare_projections(expected, actual) == []


def test_new_core_side_is_not_implemented():
    from tests.golden.legacy_oracle import NewCoreNotImplemented

    core = NewCoreNotImplemented()
    assert core.status == "NOT_IMPLEMENTED"
    with pytest.raises(NotImplementedError):
        core.analyze(bbl_path="x.bbl")
