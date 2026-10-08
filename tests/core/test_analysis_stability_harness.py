"""Discriminating checks for offline experiments, not a production-policy gate."""

from __future__ import annotations

import numpy as np
import pytest
import json
from pathlib import Path

from gyrocore.analysis.resonance import analyze_resonance
from gyrocore.analysis.signal_composition import compute_spectral_bundle
from gyrocore.parse.blackbox_csv import parse_csv
from tools.analysis_stability.policies import (
    Sample, current_indices, fixed_window_psd, perturbations, select_current,
    synthetic_samples, noise_samples, window_summary,
)
from tools.analysis_stability.summarize import SourceMismatchError, summarize


@pytest.fixture(scope="module")
def stationary() -> list[Sample]:
    return synthetic_samples()


def test_experiment_reproduces_real_parser_round_selection() -> None:
    # Given a spill whose ratio differentiates floor from round.
    n = 20_051
    csv = "time (us),gyroADC[0],gyroADC[1],gyroADC[2]\n" + "\n".join(
        f"{i * 500},{i},0,0" for i in range(n))
    # When using the actual parser.
    parsed = parse_csv(csv)
    # Then source identities match our experimental baseline exactly.
    assert [int(s["gx"]) for s in parsed] == current_indices(n)


def test_perturbations_preserve_surviving_signal(stationary: list[Sample]) -> None:
    # Given deterministic timestamped data.
    cases = perturbations(stationary)
    # When removing an unrelated block.
    rows = next(rows for name, rows in cases if name == "gap_0.5_0.10pct")
    # Then no surviving time or signal value has been rewritten.
    assert len(rows) == 99_900
    assert all(row is stationary[row["source_index"]] for row in rows)


def test_current_policy_changes_confidence_on_tiny_tail_change(stationary: list[Sample]) -> None:
    # Given the unchanged physical 73.8Hz/180Hz stationary signal.
    confidences = []
    # When dropping only .05% tail and running production FFT/resonance.
    for rows in (stationary, stationary[:-50]):
        bundle = compute_spectral_bundle(select_current(rows))
        result = analyze_resonance(bundle["merged_freqs"], bundle["merged_spectrum"], bundle["gx"], bundle["fs"])
        confidences.append(result["primary"]["confidence"])
    # Then the experiment exposes a material current-policy instability.
    assert abs(confidences[0] - confidences[1]) > .05


@pytest.mark.parametrize("remove", [50, 100, 500])
def test_fixed_windows_ignore_incomplete_tail(stationary: list[Sample], remove: int) -> None:
    # Given a tail outside the last complete anchored window.
    _, original, _, _ = fixed_window_psd(stationary)
    # When shortening the tail.
    _, changed, _, _ = fixed_window_psd(stationary[:-remove])
    # Then no complete window or computed spectrum changes.
    np.testing.assert_array_equal(original, changed)


@pytest.mark.parametrize("position", [.2, .5, .8])
def test_gap_rejection_avoids_artificial_peak_explosion(position: float) -> None:
    # Given two clearly supra-threshold tones and an unrelated 100-row hole.
    # The weaker 2deg/s control is separately measured by the policy harness:
    # the experimental PSD threshold misses it, so D is not yet qualified.
    stationary = synthetic_samples()
    for sample in stationary:
        added = 3 * np.sin(2 * np.pi * 180 * sample["t"] / 1e6)
        sample["gx"] += float(added)
        sample["gy"] += float(.7 * added)
        sample["gz"] += float(.4 * added)
    start = int(len(stationary) * position)
    rows = stationary[:start] + stationary[start + 100:]
    # When measuring only complete, gap-free timestamp windows.
    result = window_summary(rows)
    # Then peaks remain the two genuine tones and rejected coverage is explicit.
    assert result["rejected_windows"] >= 1
    assert len(result["peaks_hz"]) == 2
    assert abs(result["peaks_hz"][0] - 73.8) < result["bin_hz"]
    assert abs(result["peaks_hz"][1] - 180) < result["bin_hz"]


def test_short_late_resonance_survives_window_event_union() -> None:
    # Given a 250ms 481Hz burst, well after the first contiguous 20k rows.
    samples = synthetic_samples(burst=True)
    # When retaining local peaks alongside the averaged PSD.
    result = window_summary(samples)
    # Then the short event remains observable, with low temporal occupancy.
    index = min(range(len(result["transient_peaks_hz"])), key=lambda i: abs(result["transient_peaks_hz"][i] - 481))
    assert abs(result["transient_peaks_hz"][index] - 481) < result["bin_hz"]
    assert 0 < result["transient_peak_windows"][index] < result["windows"] / 10


def test_true_frequency_change_changes_spectral_evidence(stationary: list[Sample]) -> None:
    # Given a real shift from 73.8Hz to 83.8Hz.
    baseline = window_summary(stationary)
    # When measuring the changed physical signal.
    changed = window_summary(synthetic_samples(shifted=True))
    # Then the dominant low-frequency peak moves by approximately 10Hz.
    assert 9 < changed["peaks_hz"][0] - baseline["peaks_hz"][0] < 11


def test_fixed_window_results_are_deterministic(stationary: list[Sample]) -> None:
    # Given the same timestamped input and explicit DSP parameters.
    first = window_summary(stationary)
    # When repeating the computation.
    second = window_summary(stationary)
    # Then spectra, peaks, coverage and event counts are identical.
    assert first == second


def test_missing_window_coverage_is_unavailable() -> None:
    # Given less than one complete window.
    samples = synthetic_samples(n=100)
    # When asking for a fixed-window spectrum.
    _, mean, stack, _ = fixed_window_psd(samples)
    # Then no spectrum is fabricated.
    assert mean.size == stack.size == 0


def test_missing_coverage_does_not_report_zero_noise() -> None:
    # Given a record shorter than one complete spectral window.
    samples = synthetic_samples(n=100)
    # When reporting its spectral evidence.
    summary = window_summary(samples)
    # Then absent coverage cannot be mistaken for a clean zero-power spectrum.
    assert summary["available"] is False
    assert summary["band_power"] == []


def test_psd_power_matches_known_physical_tones(stationary: list[Sample]) -> None:
    # Given amplitudes (10,7,4) and (2,1.4,.8) on the three axes.
    # Axis-mean sine variance is (100+49+16+4+1.96+.64)/6 = 28.6.
    # When integrating normalized one-sided PSD.
    summary = window_summary(stationary)
    # Then the power scale matches the independent variance oracle.
    assert sum(summary["band_power"]) == pytest.approx(28.6, rel=.001)


def test_psd_power_matches_seeded_white_noise_variance() -> None:
    # Given independent white noise with sigma=2deg/s per axis.
    samples = noise_samples()
    # When integrating normalized one-sided PSD.
    summary = window_summary(samples)
    # Then averaged signal variance is approximately sigma squared.
    assert sum(summary["band_power"]) == pytest.approx(4, rel=.05)


def test_timestamp_reset_cannot_be_sorted_into_a_fake_spectrum() -> None:
    # Given a source timebase reset within a record.
    samples = synthetic_samples(n=6000)
    samples[2000]["t"] = 0
    # When attempting windowed spectral evidence.
    summary = window_summary(samples)
    # Then unresolved continuity is unavailable rather than sorted/concatenated.
    assert summary["available"] is False
    assert summary["windows"] == 0


def test_summary_rejects_observations_from_different_real_sources(tmp_path: Path) -> None:
    # Given old observations and a different BBL supplied for D recomputation.
    source = tmp_path / "different.bbl"
    source.write_bytes(b"different physical flight")
    (tmp_path / "real_log1.json").write_text(json.dumps({"results": []}), encoding="utf-8")
    (tmp_path / "real_log1-source.json").write_text(json.dumps({"sha256": "0" * 64}), encoding="utf-8")
    # When building the combined summary.
    # Then mismatched source provenance fails before decoding or mixing evidence.
    with pytest.raises(SourceMismatchError):
        summarize(tmp_path, source)
