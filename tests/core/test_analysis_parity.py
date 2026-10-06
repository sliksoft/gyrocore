"""Donor-vs-GyroCore parity for WU4 analysis/preprocess subsystems."""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
GL001 = REPO / "tests/fixtures/legacy/gl001_clean/input/flight.csv"
GL002 = REPO / "tests/fixtures/legacy/gl002_noisy/input/flight.csv"
GOLDEN_ROOT = Path("/home/sliksoft/aerotuner/backend/test/golden_logs")

# Tight tolerances for float DSP parity (numpy FFT / filtering).
TOL_FFT_AMP = 1e-9
TOL_SCORE = 1e-9
TOL_HZ = 1e-9


def _donor_root() -> Path:
    return Path(os.environ.get("AEROTUNER_ROOT", REPO.parent / "aerotuner"))


@pytest.fixture(scope="module")
def donor():
    root = _donor_root()
    if not root.is_dir():
        pytest.skip("donor missing")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import backend.analysis.flight_split as d_split
    import backend.analysis.quality_engine_v2 as d_q
    import backend.analysis.signal as d_sig
    import backend.analysis.erpm_analysis as d_erpm
    import backend.analysis.spectral_windows as d_spec
    import backend.analysis.step_response_analysis as d_step
    import backend.analysis.d_effectiveness_analysis as d_deff
    import backend.analysis.problem_detection_engine as d_prob
    import backend.analysis.segment_engine as d_seg
    import backend.analysis.metrics_engine as d_met
    import backend.analysis.multi_axis_fft as d_fft
    import backend.analysis.resonance as d_res
    import backend.analysis.motor_saturation as d_sat
    import backend.routes.analyze as d_analyze

    return {
        "split": d_split,
        "q": d_q,
        "sig": d_sig,
        "erpm": d_erpm,
        "spec": d_spec,
        "step": d_step,
        "deff": d_deff,
        "prob": d_prob,
        "seg": d_seg,
        "met": d_met,
        "fft": d_fft,
        "res": d_res,
        "sat": d_sat,
        "analyze": d_analyze,
    }


def _load_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            item = {
                "t": float(row["t"]),
                "gx": float(row["gx"]),
                "gy": float(row["gy"]),
                "gz": float(row["gz"]),
                "throttle": float(row["throttle"]),
                "motors": [float(row[k]) for k in ("m0", "m1", "m2", "m3")],
                "setpoint_roll": float(row["setpoint_roll"]),
                "setpoint_pitch": float(row["setpoint_pitch"]),
                "setpoint_yaw": float(row["setpoint_yaw"]),
            }
            rows.append(item)
    return rows


def _assert_close(a, b, tol, label):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        assert abs(float(a) - float(b)) <= tol, f"{label}: {a} vs {b}"
    else:
        assert a == b, f"{label}: {a!r} vs {b!r}"


@pytest.mark.parametrize("fixture", [GL001, GL002], ids=["gl001", "gl002"])
def test_parity_normalize_and_flight_selection(donor, fixture):
    from gyrocore.preprocess.normalize import normalize_raw_samples
    from gyrocore.preprocess.flight_selection import select_best_flight_for_analysis

    raw = _load_rows(fixture)
    core_norm, core_meta = normalize_raw_samples(raw, gyro_source_is_raw_adc=False)
    don_norm, don_meta = donor["analyze"]._normalize_samples(
        raw, gyro_source_is_raw_adc=False
    )
    assert core_meta == don_meta
    assert len(core_norm) == len(don_norm)
    for c, d in zip(core_norm[:50], don_norm[:50]):
        assert c["gx"] == d["gx"] and c["gy"] == d["gy"] and c["gz"] == d["gz"]
        assert c["t"] == d["t"]

    c_sel, c_q, c_n, c_i = select_best_flight_for_analysis(core_norm)
    d_sel, d_q, d_n, d_i = donor["analyze"]._select_best_flight_for_analysis(don_norm)
    assert c_n == d_n and c_i == d_i and len(c_sel) == len(d_sel)
    _assert_close(c_q.get("score"), d_q.get("score"), TOL_SCORE, "selection_quality.score")


@pytest.mark.parametrize("fixture", [GL001, GL002], ids=["gl001", "gl002"])
def test_parity_sample_rate_quality_spectral_erpm(donor, fixture):
    from gyrocore.preprocess.normalize import normalize_raw_samples
    from gyrocore.analysis.signal import compute_sample_rate, time_us_to_seconds
    from gyrocore.analysis.metrics_engine import samples_dict_from_normalized_rows
    from gyrocore.analysis.quality_engine_v2 import evaluate_quality_v2
    from gyrocore.analysis.spectral_windows import build_spectral_evidence_from_samples
    from gyrocore.analysis.erpm_analysis import analyze_erpm

    raw = _load_rows(fixture)
    norm, _ = normalize_raw_samples(raw, gyro_source_is_raw_adc=False)
    ts = time_us_to_seconds([float(s["t"]) for s in norm])
    c_sr = float(compute_sample_rate(ts))
    d_sr = float(donor["sig"].compute_sample_rate(ts))
    _assert_close(c_sr, d_sr, TOL_HZ, "sample_rate")

    matrices = samples_dict_from_normalized_rows(norm)
    c_q = evaluate_quality_v2(matrices, norm, {})
    d_q = donor["q"].evaluate_quality_v2(matrices, norm, {})
    _assert_close(c_q.get("score"), d_q.get("score"), TOL_SCORE, "quality.score")
    assert c_q.get("status") == d_q.get("status")
    assert c_q.get("grade") == d_q.get("grade")

    c_spec = build_spectral_evidence_from_samples(norm, c_sr)
    d_spec = donor["spec"].build_spectral_evidence_from_samples(norm, d_sr)
    assert c_spec.get("method") == d_spec.get("method")
    assert c_spec.get("sample_count") == d_spec.get("sample_count")
    # dominant peak freqs exact when present
    c_peaks = c_spec.get("dominant_peaks") or []
    d_peaks = d_spec.get("dominant_peaks") or []
    assert len(c_peaks) == len(d_peaks)
    for cp, dp in zip(c_peaks, d_peaks):
        if isinstance(cp, dict) and isinstance(dp, dict):
            if "freq_hz" in cp and "freq_hz" in dp:
                _assert_close(cp["freq_hz"], dp["freq_hz"], TOL_HZ, "spectral.peak_hz")

    assert analyze_erpm(norm) == donor["erpm"].analyze_erpm(norm)


@pytest.mark.parametrize("fixture", [GL001, GL002], ids=["gl001", "gl002"])
def test_parity_fft_resonance_step_deff_problems(donor, fixture):
    from gyrocore.preprocess.normalize import normalize_raw_samples
    from gyrocore.analysis.signal import compute_sample_rate, time_us_to_seconds
    from gyrocore.analysis.multi_axis_fft import merge_axes_fft
    from gyrocore.analysis.resonance import analyze_resonance
    from gyrocore.analysis.metrics_engine import samples_dict_from_normalized_rows
    from gyrocore.analysis.segment_engine import detect_segments
    from gyrocore.analysis.step_response_analysis import analyze_step_response
    from gyrocore.analysis.d_effectiveness_analysis import analyze_d_effectiveness
    from gyrocore.analysis.problem_detection_engine import detect_problems
    from gyrocore.analysis.metrics_engine import build_metrics
    from gyrocore.analysis.motor_saturation import compute_motor_saturation

    raw = _load_rows(fixture)
    norm, _ = normalize_raw_samples(raw, gyro_source_is_raw_adc=False)
    sr = float(compute_sample_rate(time_us_to_seconds([float(s["t"]) for s in norm])))
    gx = np.asarray([s["gx"] for s in norm], dtype=float)
    gy = np.asarray([s["gy"] for s in norm], dtype=float)
    gz = np.asarray([s["gz"] for s in norm], dtype=float)
    c_f, c_s = merge_axes_fft(gx, gy, gz, fs=sr)
    d_f, d_s = donor["fft"].merge_axes_fft(gx, gy, gz, fs=sr)
    np.testing.assert_allclose(c_f, d_f, rtol=0, atol=TOL_FFT_AMP)
    np.testing.assert_allclose(c_s, d_s, rtol=0, atol=TOL_FFT_AMP)

    c_res = analyze_resonance(c_f, c_s, gx, sr)
    d_res = donor["res"].analyze_resonance(d_f, d_s, gx, sr)
    assert c_res.keys() == d_res.keys()
    # primary notch freq exact when numeric
    for key in ("spread",):
        if key in c_res and key in d_res:
            _assert_close(c_res[key], d_res[key], TOL_SCORE, f"resonance.{key}")

    matrices = samples_dict_from_normalized_rows(norm)
    c_seg = detect_segments(matrices)
    d_seg = donor["seg"].detect_segments(matrices)
    assert c_seg == d_seg

    c_step = analyze_step_response(matrices, c_seg)
    d_step = donor["step"].analyze_step_response(matrices, d_seg)
    assert c_step == d_step

    c_deff = analyze_d_effectiveness(matrices, None, response_analysis=c_step, segments=c_seg)
    d_deff = donor["deff"].analyze_d_effectiveness(
        matrices, None, response_analysis=d_step, segments=d_seg
    )
    assert c_deff == d_deff

    analysis = {"resonance_module": c_res, "sample_rate_hz": sr}
    fft_data = {"freqs": c_f.tolist(), "amps": c_s.tolist()}
    c_met = build_metrics(matrices, analysis, fft_data)
    d_met = donor["met"].build_metrics(matrices, analysis, fft_data)
    assert c_met == d_met

    c_prob = detect_problems(c_met, c_seg)
    d_prob = donor["prob"].detect_problems(d_met, d_seg)
    assert c_prob == d_prob

    motors = [s["motors"] for s in norm if isinstance(s.get("motors"), list)]
    assert compute_motor_saturation(motors) == donor["sat"].compute_motor_saturation(motors)


def test_parity_flight_split_empty_and_synthetic(donor):
    from gyrocore.analysis.flight_split import split_samples_into_flights

    assert split_samples_into_flights([]) == donor["split"].split_samples_into_flights([])
    # short synthetic log
    samples = [{"t": i * 1000, "gx": 0.0, "gy": 0.0, "gz": 0.0, "throttle": 0.5} for i in range(200)]
    assert split_samples_into_flights(samples) == donor["split"].split_samples_into_flights(samples)


def test_gl003_exists_for_matrix():
    path = GOLDEN_ROOT / "GL-003-motor_issue" / "log.csv"
    assert path.is_file()
