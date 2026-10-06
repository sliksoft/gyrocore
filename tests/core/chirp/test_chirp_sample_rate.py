"""
WU5 — regression for upstream CHIRP sample-rate behavior.

Encodes Betaflight Configurator ``useAutotune.computeSampleRate`` without
"fixing" header-only / P-num-ignored risks. See
``docs/upstream/CHIRP_SAMPLE_RATE.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gyrocore.chirp.sample_rate import (
    compute_sample_rate_from_sysconfig,
    compute_sample_rate_hz,
    pid_loop_frequency_hz,
)

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "chirp" / "header_cases.json"


@pytest.fixture(scope="module")
def header_cases() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_points_at_upstream_symbol(header_cases: dict) -> None:
    upstream = header_cases["upstream"]
    assert upstream["symbol"] == "computeSampleRate"
    assert "useAutotune.ts" in upstream["path"]
    assert "frameIntervalPDenom" in upstream["formula"]


@pytest.mark.parametrize(
    "case_id",
    [
        "full_rate_8k_pid_denom_1",
        "half_rate_log_vs_pid",
        "pid_denom_2_full_bb",
        "pid_denom_2_and_bb_denom_2",
        "missing_fields_use_upstream_defaults",
        "frame_interval_p_num_ignored",
    ],
)
def test_upstream_sample_rate_cases(header_cases: dict, case_id: str) -> None:
    case = next(c for c in header_cases["cases"] if c["id"] == case_id)
    sys_config = case["sysConfig"]
    rate = compute_sample_rate_from_sysconfig(sys_config)
    pid_hz = pid_loop_frequency_hz(
        sys_config.get("looptime"),
        sys_config.get("pid_process_denom"),
    )
    assert rate == pytest.approx(case["expected_sample_rate_hz"])
    assert pid_hz == pytest.approx(case["expected_pid_loop_hz"])
    slower = rate < pid_hz - 1e-9
    assert slower is case["blackbox_slower_than_pid"]


def test_when_blackbox_slower_than_pid_rate_is_pid_divided_by_bb_denom() -> None:
    """Explicit audit case: logging every 2nd PID loop halves analysis rate."""
    looptime = 125
    pid_denom = 1
    bb_denom = 2
    pid_hz = pid_loop_frequency_hz(looptime, pid_denom)
    bb_hz = compute_sample_rate_hz(looptime, pid_denom, bb_denom)
    assert pid_hz == pytest.approx(8000.0)
    assert bb_hz == pytest.approx(4000.0)
    assert bb_hz == pytest.approx(pid_hz / bb_denom)


def test_frame_interval_p_num_does_not_affect_upstream_formula() -> None:
    """Documented risk: only frameIntervalPDenom scales the rate."""
    a = compute_sample_rate_hz(125, 1, 2)
    b = compute_sample_rate_from_sysconfig(
        {
            "looptime": 125,
            "pid_process_denom": 1,
            "frameIntervalPNum": 99,
            "frameIntervalPDenom": 2,
        }
    )
    assert a == pytest.approx(b)
    assert a == pytest.approx(4000.0)
