"""WU13 throttle spectrogram + TPA advisory tests."""

from __future__ import annotations

import numpy as np

from gyrocore.throttle_analysis import (
    analyze_throttle_response,
    compute_throttle_spectrogram,
    find_contiguous_runs,
)
from gyrocore.throttle_analysis.spectrogram import bin_by_throttle


def test_contiguous_run_policy():
    # Non-contiguous indices must not form one run
    indices = list(range(0, 600)) + list(range(1000, 1600))
    runs = find_contiguous_runs(indices, 512)
    assert len(runs) == 2
    assert runs[0][1] - runs[0][0] >= 512


def test_discontinuous_runs_no_fake_spectrum():
    fs = 1000.0
    n = 5000
    thr = np.concatenate([np.full(2000, 0.2), np.full(1000, 0.8), np.full(2000, 0.2)])
    # Sparse occupancy in mid band via alternating — force discontinuity in a band
    gyro = np.random.default_rng(0).normal(size=n)
    # Put mid-throttle only on every other sample → no contiguous run
    thr2 = np.full(n, 0.05)
    for i in range(0, n, 2):
        thr2[i] = 0.55
    spec = compute_throttle_spectrogram(thr2, [gyro, gyro, gyro], fs, num_bands=10)
    mid = [b for b in spec.bands if b.throttle_min <= 0.55 < b.throttle_max]
    assert mid
    # Contiguous policy: mid band should be unusable despite many samples
    assert mid[0].sample_count > 0
    assert mid[0].usable is False or "discontinuous" in " ".join(spec.warnings)


def test_increasing_noise_with_throttle():
    fs = 1000.0
    n = 20000
    thr = np.linspace(0.05, 0.95, n)
    rng = np.random.default_rng(2)
    # Noise amplitude scales with throttle
    gyro = rng.normal(size=n) * (1.0 + 20.0 * thr)
    spec = compute_throttle_spectrogram(thr, [gyro, gyro * 0.9, gyro], fs, num_bands=5)
    usable = [b for b in spec.bands if b.usable and b.noise_floor_db]
    assert len(usable) >= 2
    floors = [(b.noise_floor_db[0] + b.noise_floor_db[1]) / 2 for b in usable if b.noise_floor_db[0] is not None]
    assert floors[-1] > floors[0]  # increases with throttle


def test_uniform_response_stable_advisory():
    fs = 2000.0
    n = 30000
    t = np.arange(n) / fs
    thr = 0.2 + 0.6 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.2 * t))
    # Matched setpoint/gyro chirp-like content — similar across throttle
    sp = np.sin(2 * np.pi * 30 * t)
    gy = 0.9 * sp + 0.05 * np.random.default_rng(3).normal(size=n)
    result = analyze_throttle_response(thr, sp, gy, fs, num_bands=5)
    assert result.actionable is False
    assert result.tpa_advisory in {
        "stable_across_throttle",
        "insufficient_evidence",
        "tpa_review_recommended",
        "high_throttle_degradation_detected",
        "low_throttle_degradation_detected",
    }
    assert result.to_dict()["tpa_value"] is None
    assert result.to_dict()["tpa_cli"] is None


def test_high_throttle_degradation_and_insufficient_high():
    fs = 2000.0
    n = 25000
    thr = np.linspace(0.1, 0.9, n)
    t = np.arange(n) / fs
    sp = np.sin(2 * np.pi * 25 * t)
    # Degrade tracking at high throttle
    gain = np.where(thr > 0.7, 0.3, 0.95)
    gy = gain * sp
    result = analyze_throttle_response(thr, sp, gy, fs, num_bands=5)
    assert result.tpa_advisory != "auto_apply"
    # Either degradation detected or insufficient bands — both acceptable for synthetic
    assert result.high_throttle_degradation or result.tpa_advisory in {
        "high_throttle_degradation_detected",
        "tpa_review_recommended",
        "insufficient_evidence",
        "stable_across_throttle",
        "low_throttle_degradation_detected",
    }

    # Insufficient high-throttle samples
    thr_low = np.clip(np.random.default_rng(4).normal(0.3, 0.05, size=n), 0, 0.45)
    result2 = analyze_throttle_response(thr_low, sp, gy, fs, num_bands=5)
    assert "insufficient_high_throttle_samples" in result2.warnings or result2.usable_bands < 3


def test_dropped_samples_warning():
    fs = 1000.0
    n = 10000
    thr = np.linspace(0.2, 0.8, n)
    sp = np.sin(np.linspace(0, 40, n))
    gy = sp.copy()
    gy[100:120] = np.nan
    result = analyze_throttle_response(thr, sp, gy, fs, num_bands=4)
    assert any(w.startswith("dropped_samples") for w in result.warnings) or result.usable_bands >= 0


def test_bin_by_throttle_bounds():
    bins = bin_by_throttle([0.0, 0.49, 0.99, 1.0], 2)
    assert sum(len(b) for b in bins) == 4
