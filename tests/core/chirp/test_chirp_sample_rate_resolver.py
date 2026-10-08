"""WU6 — CHIRP sample-rate resolver parity and policy tests."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from gyrocore.chirp.sample_rate import (
    MISMATCH_TOLERANCE_FRACTION,
    SampleRateSource,
    SampleRateStatus,
    compute_sample_rate_hz,
    estimate_timestamp_rate_hz,
    header_logged_rate_hz,
    pid_loop_frequency_hz,
    resolve_chirp_sample_rate,
    resolve_from_sysconfig,
    upstream_autotune_compute_sample_rate_hz,
)

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "chirp"
PARITY = json.loads((FIXTURES / "sample_rate_parity_vectors.json").read_text(encoding="utf-8"))
WU5 = json.loads((FIXTURES / "header_cases.json").read_text(encoding="utf-8"))


def _timestamps(dt_us: float, count: int, gap_every: int | None = None, gap_extra_us: float = 0.0) -> np.ndarray:
    t = [0.0]
    for i in range(1, count):
        step = dt_us
        if gap_every and i % gap_every == 0:
            step += gap_extra_us
        t.append(t[-1] + step)
    return np.asarray(t, dtype=float)


def test_mismatch_tolerance_matches_viewer() -> None:
    assert MISMATCH_TOLERANCE_FRACTION == pytest.approx(0.05)


def test_header_formula_uses_num_and_denom() -> None:
    # Viewer: 8000 * 2/3
    assert header_logged_rate_hz(125, 1, 2, 3) == pytest.approx(8000.0 * 2.0 / 3.0)
    # Autotune upstream ignores num → 8000/3
    assert upstream_autotune_compute_sample_rate_hz(125, 1, 3) == pytest.approx(8000.0 / 3.0)


@pytest.mark.parametrize("case", PARITY["cases"], ids=lambda c: c["id"])
def test_parity_vectors(case: dict) -> None:
    cfg = dict(case.get("sysConfig", {}))
    for key in case.get("omit_keys", []):
        cfg.pop(key, None)

    looptime = cfg.get("looptime")
    pid_denom = cfg.get("pid_process_denom")
    p_num = cfg.get("frameIntervalPNum")
    p_den = cfg.get("frameIntervalPDenom")

    if case.get("expect_header_rate_null"):
        from gyrocore.chirp.sample_rate import try_header_logged_rate_hz

        assert try_header_logged_rate_hz(looptime, pid_denom, p_num, p_den) is None
    elif "expected_header_rate_hz" in case:
        assert header_logged_rate_hz(looptime, pid_denom, p_num, p_den) == pytest.approx(
            case["expected_header_rate_hz"]
        )
        assert pid_loop_frequency_hz(looptime, pid_denom) == pytest.approx(case["expected_pid_loop_hz"])
        if "expected_upstream_autotune_hz" in case:
            assert upstream_autotune_compute_sample_rate_hz(looptime, pid_denom, p_den) == pytest.approx(
                case["expected_upstream_autotune_hz"]
            )

    timestamps = None
    if "timestamp_dt_us" in case:
        timestamps = _timestamps(
            case["timestamp_dt_us"],
            case["timestamp_count"],
            case.get("gap_every"),
            case.get("gap_extra_us", 0.0),
        )

    if case.get("expect_status_without_timestamps") and timestamps is None:
        ev = resolve_from_sysconfig(cfg, timestamps_us=None)
        assert ev.status.value == case["expect_status_without_timestamps"]
        assert ev.usable is False
        assert ev.effective_rate_hz is None
        return

    if "expected_status" in case:
        ev = resolve_from_sysconfig(cfg, timestamps_us=timestamps)
        assert ev.status.value == case["expected_status"]
        if "expected_source" in case:
            assert ev.source.value == case["expected_source"]
        assert ev.effective_rate_hz == pytest.approx(case["expected_effective_hz"])
        assert ev.usable is True


def test_wu5_upstream_mirror_still_holds() -> None:
    """WU5 denom-only Autotune mirror remains available for historical parity."""
    for case in WU5["cases"]:
        if case["id"] == "frame_interval_p_num_ignored":
            # Still true for the *upstream mirror*, not for GyroCore header rate
            rate = compute_sample_rate_hz(
                case["sysConfig"].get("looptime"),
                case["sysConfig"].get("pid_process_denom"),
                case["sysConfig"].get("frameIntervalPDenom"),
            )
            assert rate == pytest.approx(case["expected_sample_rate_hz"])
            # GyroCore improvement: num is honored
            assert header_logged_rate_hz(125, 1, 3, 2) == pytest.approx(8000.0 * 3.0 / 2.0)


def test_timestamp_estimate_rejects_non_positive_dt() -> None:
    # Mostly 250 us with a few zero/negative glitches
    t = [0.0]
    for i in range(40):
        if i in (5, 12):
            t.append(t[-1])  # zero dt
        elif i == 20:
            t.append(t[-1] - 10.0)  # negative
        else:
            t.append(t[-1] + 250.0)
    rate = estimate_timestamp_rate_hz(t)
    assert rate == pytest.approx(4000.0)


def test_silent_full_rate_fallback_removed() -> None:
    ev = resolve_chirp_sample_rate(
        looptime_us=125,
        pid_process_denom=1,
        frame_interval_p_num=None,
        frame_interval_p_denom=None,
        timestamps_us=None,
    )
    assert ev.status is SampleRateStatus.UNUSABLE
    assert ev.effective_rate_hz is None
    assert "p_interval_metadata_missing" in ev.warnings
    assert "no_trustworthy_sample_rate" in ev.warnings


def test_disagreement_prefers_timestamp() -> None:
    ts = _timestamps(250.0, 64)
    ev = resolve_chirp_sample_rate(
        looptime_us=125,
        pid_process_denom=1,
        frame_interval_p_num=1,
        frame_interval_p_denom=1,
        timestamps_us=ts,
    )
    assert ev.status is SampleRateStatus.MISMATCH
    assert ev.source is SampleRateSource.TIMESTAMP
    assert ev.header_rate_hz == pytest.approx(8000.0)
    assert ev.timestamp_rate_hz == pytest.approx(4000.0)
    assert ev.effective_rate_hz == pytest.approx(4000.0)
    assert ev.difference_percent is not None and ev.difference_percent > 5.0
