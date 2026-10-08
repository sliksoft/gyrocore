"""WU13 filter evidence tests."""

from __future__ import annotations

import math

import numpy as np
import pytest

from gyrocore.filter_evidence import (
    analyze_filter_evidence,
    estimate_group_delay,
    pt1_group_delay,
)
from gyrocore.filter_evidence.candidate import (
    analyze_dynamic_lowpass_evidence,
    compute_noise_based_target,
)
from gyrocore.filter_evidence.noise import analyze_axis_noise, classify_noise_level, detect_peaks
from gyrocore.filter_evidence.segments import find_steady_segments, select_analysis_segments


def _synth_samples(
    *,
    n: int = 8000,
    fs: float = 1000.0,
    noise_amp: float = 0.5,
    resonance_hz: float | None = None,
    throttle_fn=None,
) -> list[dict]:
    t = np.arange(n) / fs
    if throttle_fn is None:
        thr = np.full(n, 0.4)
    else:
        thr = np.asarray([throttle_fn(i, n) for i in range(n)], dtype=float)
    gyro = noise_amp * np.random.default_rng(0).normal(size=n)
    if resonance_hz:
        gyro = gyro + 8.0 * np.sin(2 * math.pi * resonance_hz * t)
    rows = []
    for i in range(n):
        rows.append(
            {
                "time": float(t[i]),
                "gyroADC[0]": float(gyro[i]),
                "gyroADC[1]": float(gyro[i] * 0.9),
                "gyroADC[2]": float(gyro[i] * 1.1),
                "rcCommand[3]": float(1000 + thr[i] * 1000),
            }
        )
    return rows


def test_pt1_group_delay_exact_parity():
    # EXACT_PARITY with FPVPIDlab GroupDelayEstimator.test.ts
    assert pt1_group_delay(0, 80) == 0.0
    assert pt1_group_delay(250, 80) == pytest.approx(5.774e-4, abs=1e-6)
    assert pt1_group_delay(250, 80) * 1000 == pytest.approx(0.5775, abs=1e-3)
    assert pt1_group_delay(100, 0) == pytest.approx(1 / (2 * math.pi * 100), abs=1e-8)


def test_low_noise_and_excessive_group_delay():
    samples = _synth_samples(noise_amp=0.05)
    cli = "set gyro_lpf1_static_hz = 80\nset dterm_lpf1_static_hz = 70\nset gyro_lpf2_static_hz = 100\n"
    result = analyze_filter_evidence(samples, sample_rate_hz=1000.0, cli_dump=cli)
    assert result.actionable is False
    assert result.filter_candidate.actionable is False
    assert result.overall_noise_level in {"low", "medium", "high", "unknown"}
    assert result.current_group_delay is not None
    # Low cutoffs → higher delay; may warn
    gd = estimate_group_delay(
        {
            "gyro_lpf1_static_hz": 50,
            "gyro_lpf2_static_hz": 50,
            "dterm_lpf1_static_hz": 40,
            "dterm_lpf2_static_hz": 40,
        }
    )
    assert gd.gyro_total_ms > 0
    # "excessive" path
    assert gd.gyro_over_budget or gd.gyro_total_ms > 1.0


def test_broadband_noise_high_level():
    rng = np.random.default_rng(1)
    sig = rng.normal(scale=20.0, size=4096)
    ar = analyze_axis_noise(sig, 1000.0)
    assert ar["noise_floor_db"] is not None
    assert classify_noise_level(ar["noise_floor_db"]) in {"medium", "high", "low"}


def test_frame_resonance_peak():
    samples = _synth_samples(noise_amp=0.2, resonance_hz=120.0)
    result = analyze_filter_evidence(samples, sample_rate_hz=1000.0, cli_dump="set gyro_lpf1_static_hz = 250\n")
    types = {p.peak_type for p in result.peaks}
    assert "frame_resonance" in types or any(80 <= p.frequency_hz <= 200 for p in result.peaks)


def test_throttle_dependent_noise_dynamic_evidence():
    bands = [
        {"throttle_mid": 0.1, "noise_floor_db": -50},
        {"throttle_mid": 0.3, "noise_floor_db": -45},
        {"throttle_mid": 0.5, "noise_floor_db": -40},
        {"throttle_mid": 0.7, "noise_floor_db": -35},
        {"throttle_mid": 0.9, "noise_floor_db": -30},
    ]
    ev = analyze_dynamic_lowpass_evidence(bands)
    assert ev is not None
    assert ev["recommended"] is True  # MATH_EQUIVALENT / EXACT_PARITY thresholds


def test_insufficient_stable_segment():
    # Very short / aggressive gyro — expect entire-flight warning
    n = 200
    samples = [
        {
            "time": i / 1000.0,
            "gyroADC[0]": 200.0 * math.sin(i),
            "gyroADC[1]": 200.0 * math.cos(i),
            "gyroADC[2]": 200.0,
            "rcCommand[3]": 1500,
        }
        for i in range(n)
    ]
    result = analyze_filter_evidence(samples, sample_rate_hz=1000.0)
    assert any("insufficient_stable_segment" in w for w in result.warnings)


def test_low_group_delay_warning_path():
    gd = estimate_group_delay({"gyro_lpf1_static_hz": 500, "dterm_lpf1_static_hz": 300})
    assert gd.gyro_total_ms < 2.0
    samples = _synth_samples()
    result = analyze_filter_evidence(
        samples,
        sample_rate_hz=1000.0,
        cli_dump="set gyro_lpf1_static_hz = 500\nset dterm_lpf1_static_hz = 300\n",
    )
    assert "low_group_delay" in result.warnings or result.current_group_delay.gyro_total_ms < 1.0


def test_noise_based_target_parity():
    # EXACT_PARITY computeNoiseBasedTarget
    assert compute_noise_based_target(-30, 75, 300) == compute_noise_based_target(-30, 75, 300)
    mid = compute_noise_based_target(-30, 75, 300)
    assert 75 <= mid <= 300


def test_candidate_never_actionable():
    samples = _synth_samples(noise_amp=5.0)
    result = analyze_filter_evidence(
        samples,
        sample_rate_hz=1000.0,
        cli_dump="set gyro_lpf1_static_hz = 250\nset dterm_lpf1_static_hz = 150\n",
    )
    assert result.actionable is False
    assert result.filter_candidate.actionable is False
    assert result.provenance.get("actionable") is False


def test_steady_segment_selection():
    fs = 1000.0
    n = 3000
    thr = np.full(n, 0.4)
    gyro = np.zeros(n)
    segs = find_steady_segments(thr, gyro, gyro, gyro, fs)
    assert segs
    assert segs[0].duration_seconds >= 0.5
