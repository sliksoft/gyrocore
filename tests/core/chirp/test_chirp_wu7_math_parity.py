"""WU7: numeric parity of the Python system-ID port vs vendored Betaflight TypeScript.

Expected values: ``tests/fixtures/chirp/wu7/upstream_math_reference.json``,
produced by ``tools/chirp_reference/reference_harness.mjs`` running the vendored
``fft.ts`` / ``spectral_analysis.ts`` / ``useAutotune.ts`` / ``debugModes.ts``.
Tolerances are documented in ``docs/upstream/CHIRP_SYSTEM_ID_PARITY.md``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from gyrocore.chirp import debug_modes
from gyrocore.chirp import system_id as S
from gyrocore.chirp.sample_rate import upstream_autotune_compute_sample_rate_hz

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "tests" / "fixtures" / "chirp" / "wu7"
INPUTS = json.loads((FIX / "math_inputs.json").read_text())
REF = json.loads((FIX / "upstream_math_reference.json").read_text())

FFT_TOL = 1e-12  # relative to max |X|
WINDOW_TOL = 1e-15
H_RTOL = 1e-12
COH_ATOL = 1e-12
MAG_DB_ATOL = 1e-10
PHASE_DEG_ATOL = 1e-9
SPECTROGRAM_DB_ATOL = 1e-9
STEP_ATOL = 1e-12


def arr(values) -> np.ndarray:
    return np.array([float(v) for v in values], dtype=float)


def wrapped_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return np.abs((a - b + 180.0) % 360.0 - 180.0)


def test_reference_vectors_come_from_pinned_vendored_sources():
    prov = REF["provenance"]
    assert prov["upstream_commit"] == "a38c4a797a86a580106162653db92af7e14be787"
    assert prov["api_version_max_supported"] == debug_modes.API_VERSION_MAX_SUPPORTED
    for rel, digest in prov["vendored_sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel


FFT_CASES = [(spec, ref) for spec, ref in zip(INPUTS["fft"], REF["fft"]) if spec["n"] >= 2]


@pytest.mark.parametrize("spec,ref", FFT_CASES, ids=[f"{s['kind']}{'-inv' if s['inverse'] else ''}-n{s['n']}" for s, _ in FFT_CASES])
def test_complex_fft_matches_upstream_including_absolute_scale(spec, ref):
    out = S.complex_fft(spec["input"], inverse=spec["inverse"], kind=spec["kind"])
    expected = arr(ref["output"])
    assert out.shape == expected.shape
    scale = np.max(np.abs(expected))
    assert np.max(np.abs(out - expected)) <= FFT_TOL * scale
    # No hidden global factor: energies agree, not just ratios.
    assert np.linalg.norm(out) / np.linalg.norm(expected) == pytest.approx(1.0, abs=1e-14)


def test_upstream_complex_fft_size_one_is_degenerate_and_documented():
    # ComplexFFT(1) has no radix factors and leaves its output untouched (zeros);
    # the DFT of one sample is the sample itself. Never reached by CHIRP paths
    # (welch segments are >= 4, spectrogram windows >= 4).
    for spec, ref in zip(INPUTS["fft"], REF["fft"]):
        if spec["n"] == 1:
            assert arr(ref["output"]).tolist() == [0.0, 0.0]
            out = S.complex_fft(spec["input"], inverse=spec["inverse"], kind=spec["kind"])
            assert out[0] == pytest.approx(float(spec["input"][0]))


def test_fft_sign_convention_is_negative_exponent_forward():
    x = np.zeros(8)
    x[1] = 1.0
    out = S.complex_fft(x, kind="real")
    k = 1
    assert out[2 * k] == pytest.approx(np.cos(-2 * np.pi * k / 8))
    assert out[2 * k + 1] == pytest.approx(np.sin(-2 * np.pi * k / 8))


@pytest.mark.parametrize("ref", REF["hanning"], ids=lambda r: f"n{r['size']}")
def test_hanning_window_parity(ref):
    assert np.max(np.abs(S.hanning_window(ref["size"]) - arr(ref["window"]))) <= WINDOW_TOL


WELCH = list(zip(INPUTS["welch"], REF["welch"]))


@pytest.mark.parametrize("spec,ref", WELCH, ids=[s["name"] for s, _ in WELCH])
def test_welch_transfer_function_parity(spec, ref):
    tf = S.welch_transfer_function(spec["input"], spec["output"], spec["sample_rate"], spec["segment_size"], spec["overlap"])
    ut = ref["transferFunction"]
    assert tf.num_segments == ut["numSegments"]
    assert np.array_equal(tf.frequencies, arr(ut["frequencies"]))
    expected_h = arr(ut["hReal"]) + 1j * arr(ut["hImag"])
    scale = max(np.max(np.abs(expected_h)), 1e-300)
    assert np.all(np.abs(tf.h - expected_h) <= H_RTOL * np.abs(expected_h) + 1e-15 * scale)
    assert np.max(np.abs(tf.coherence - arr(ut["coherence"]))) <= COH_ATOL
    mag = arr(ut["magnitude"])
    assert np.array_equal(np.isfinite(tf.magnitude_db), np.isfinite(mag))
    fin = np.isfinite(mag)
    if fin.any():
        assert np.max(np.abs(tf.magnitude_db[fin] - mag[fin])) <= MAG_DB_ATOL
    significant = np.abs(expected_h) > 1e-9 * scale
    assert np.all(wrapped_deg(tf.phase_deg, arr(ut["phase"]))[significant] <= PHASE_DEG_ATOL)


@pytest.mark.parametrize("spec,ref", WELCH, ids=[s["name"] for s, _ in WELCH])
def test_sensitivity_open_loop_and_step_parity(spec, ref):
    tf = S.welch_transfer_function(spec["input"], spec["output"], spec["sample_rate"], spec["segment_size"], spec["overlap"])

    sens = S.compute_sensitivity(tf)
    us = ref["sensitivity"]
    um = arr(us["magnitude"])
    assert np.array_equal(np.isfinite(sens.magnitude_db), np.isfinite(um))
    fin = np.isfinite(um)
    assert np.max(np.abs(sens.magnitude_db[fin] - um[fin]), initial=0.0) <= MAG_DB_ATOL
    peak = float(us["peakDb"])
    assert (sens.peak_db == peak) if not np.isfinite(peak) else sens.peak_db == pytest.approx(peak, abs=MAG_DB_ATOL)

    ol = S.open_loop_response(tf)
    uo = ref["openLoop"]
    assert ol.start_index == uo["startIndex"]
    om, op = arr(uo["magnitude"]), arr(uo["phase"])
    assert np.array_equal(np.isnan(ol.magnitude), np.isnan(om))
    ok = ~np.isnan(om)
    assert np.all(np.abs(ol.magnitude[ok] - om[ok]) <= 1e-10 * om[ok] + 1e-14)
    assert np.max(np.abs(ol.phase_deg[ok] - op[ok]), initial=0.0) <= PHASE_DEG_ATOL

    ur = ref["stepResponse"]
    step = S.compute_step_response(tf, spec["sample_rate"], ur["segmentSize"])
    assert np.array_equal(step.time_ms, arr(ur["timeMs"]))
    assert np.max(np.abs(step.response - arr(ur["response"])), initial=0.0) <= STEP_ATOL
    assert step.overshoot_pct == pytest.approx(ur["overshootPct"], abs=1e-9)
    assert step.rise_time_ms == pytest.approx(ur["riseTimeMs"], abs=1e-12)
    assert step.settling_time_ms == pytest.approx(ur["settlingTimeMs"], abs=1e-12)


SPECTRO = list(zip(INPUTS["spectrogram"], REF["spectrogram"]))


@pytest.mark.parametrize("spec,ref", SPECTRO, ids=[s["name"] for s, _ in SPECTRO])
def test_spectrogram_parity_absolute_power(spec, ref):
    sg = S.compute_spectrogram(spec["signal"], spec["sample_rate"], spec["window_size"], spec["overlap"])
    assert (sg.num_segments, sg.num_bins) == (ref["numSegments"], ref["numBins"])
    assert np.array_equal(sg.time_ms, arr(ref["timeMs"]))
    assert np.array_equal(sg.freq_hz, arr(ref["freqHz"]))
    expected = arr(ref["power"]).reshape(ref["numSegments"], ref["numBins"])
    assert np.max(np.abs(sg.power_db - expected)) <= SPECTROGRAM_DB_ATOL


def test_choose_segment_size_parity():
    for row in REF["segmentSize"]:
        assert S.choose_segment_size(row["sampleRate"]) == row["segmentSize"]


def test_upstream_compute_sample_rate_parity():
    for row in REF["sampleRate"]:
        sc = row["sysConfig"]
        got = upstream_autotune_compute_sample_rate_hz(sc["looptime"], sc["pid_process_denom"], sc["frameIntervalPDenom"])
        assert got == pytest.approx(row["sampleRate"], rel=1e-15)


def test_chirp_debug_mode_index_parity():
    for row in REF["debugModes"]:
        assert debug_modes.chirp_debug_mode_index(row["apiVersion"]) == row["chirpIndex"], row


def test_js_round_is_half_up():
    assert S.js_round(62.5) == 63
    assert S.js_round(127.5) == 128
    assert S.js_round(0.49999) == 0
    tf = S.welch_transfer_function(np.arange(400.0), np.arange(400.0), 1000.0, 125, 0.5)
    assert tf.spectra is not None and tf.spectra.hop_size == 63
