from __future__ import annotations

import numpy as np
import pytest

from tools.analysis_stability.policies import Sample, synthetic_samples
from tools.analysis_stability.qualified import SpectralEvidence, qualify


def _signal(
    *,
    seconds: float = 16.0,
    tones: tuple[tuple[float, float], ...] = (),
    noise_sigma: float = 0.0,
    seed: int = 0,
) -> list[Sample]:
    count = round(seconds * 2_000)
    time = np.arange(count) / 2_000
    value = sum(amplitude * np.sin(2 * np.pi * frequency * time) for frequency, amplitude in tones)
    value += np.random.default_rng(seed).normal(0.0, noise_sigma, count)
    return [Sample(t=index * 500, gx=float(v), gy=float(v), gz=float(v), throttle=.5, motors=[.5] * 4)
            for index, v in enumerate(value)]


def _near(frequency: float, evidence: SpectralEvidence) -> bool:
    return any(abs(peak.frequency_hz - frequency) <= 1.0 for peak in evidence.peaks)


@pytest.mark.parametrize("frequency", [180.0, 180.48828125])
def test_weak_tone_survives_strong_remote_tone(frequency: float) -> None:
    evidence = qualify(_signal(tones=((73.8, 10.0), (frequency, 2.0)), noise_sigma=.2, seed=71))
    assert _near(frequency, evidence)


@pytest.mark.parametrize("separation", [3.0, 5.0])
def test_close_tones_are_resolved_above_three_bins(separation: float) -> None:
    evidence = qualify(_signal(tones=((180.0, 4.0), (180.0 + separation, 4.0)), noise_sigma=.05, seed=41))
    assert _near(180.0, evidence)
    assert _near(180.0 + separation, evidence)


def test_noise_only_does_not_promote_clusters() -> None:
    for seed in range(16):
        evidence = qualify(_signal(noise_sigma=2.0, seed=seed))
        assert evidence.peaks == ()


@pytest.mark.parametrize("position", [.2, .5, .8])
def test_gaps_only_reject_overlapping_windows(position: float) -> None:
    samples = _signal(seconds=32, tones=((180.0, 2.0),), noise_sigma=.1, seed=11)
    start = int(len(samples) * position)
    evidence = qualify(samples[:start] + samples[start + 10:])
    assert evidence.rejected_windows >= 1
    assert _near(180.0, evidence)


def test_tail_change_keeps_earlier_stationary_evidence() -> None:
    samples = _signal(seconds=32, tones=((180.0, 2.0),), noise_sigma=.1, seed=22)
    assert qualify(samples).peaks == qualify(samples[:-10]).peaks


@pytest.mark.parametrize("start", [0.0, 1_024 / 2_000, 16.0 - .25])
def test_burst_boundaries_remain_event_evidence(start: float) -> None:
    samples = _signal(seconds=16)
    for sample in samples:
        time = sample["t"] / 1e6
        if start <= time < start + .25:
            value = 20 * np.sin(2 * np.pi * 481 * time)
            sample["gx"] = value
            sample["gy"] = value
            sample["gz"] = value
    evidence = qualify(samples)
    assert any(abs(peak.frequency_hz - 481.0) <= 4.0 for peak in evidence.event_peaks)


@pytest.mark.parametrize("removed", [1, 10, 200])
def test_missing_intervals_reduce_coverage_without_erasing_tone(removed: int) -> None:
    samples = _signal(seconds=32, tones=((180.0, 2.0),), noise_sigma=.1, seed=17)
    start = len(samples) // 2
    evidence = qualify(samples[:start] + samples[start + removed:])
    assert evidence.rejected_windows >= 1
    assert _near(180.0, evidence)


def test_burst_is_event_evidence_not_stationary_persistence() -> None:
    evidence = qualify(synthetic_samples(burst=True))
    stationary = next(peak for peak in evidence.peaks if abs(peak.frequency_hz - 481.0) <= evidence.bin_hz)
    assert stationary.supporting_windows < evidence.windows / 10
    assert any(abs(peak.frequency_hz - 481.0) <= evidence.bin_hz and peak.supporting_windows >= 1
               for peak in evidence.event_peaks)
