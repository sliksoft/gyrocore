"""WU8: ``recommendGains`` math parity against the vendored Betaflight TypeScript.

Reference vectors: ``tests/fixtures/autotune/wu8/upstream_autotune_reference.json.gz``
produced by ``tools/autotune_reference/autotune_harness.mjs`` running the vendored
``spectral_analysis.ts`` / ``useAutotune.ts`` (and the vendored test helper
``makeSyntheticTf``).

Every vector is replayed here with the *upstream* transfer-function arrays as
input, so differences can only come from the recommendation math itself.

Tolerances (``docs/upstream/AUTOTUNE_RECOMMENDATION_PARITY.md`` §8):

- exact: every boolean flag, every proposed slider integer, the sensitivity scan
  gain grid, ``openLoop.startIndex`` / NaN pattern, which branch was taken
  (crossover / target found or not, held scan, NaN / ±Infinity results)
- ``CONT_RTOL`` (1e-11 relative) for continuous values; observed max 1.1e-15
  except the sensitivity peaks (1.7e-13), which go through ``Math.hypot``
- ``DB_ATOL`` (1e-10 dB absolute) for dB values that can sit at ~0 dB
- ``PHASE_ATOL_DEG`` (1e-10 deg absolute) for phase (``Math.atan2`` ulps x 180/pi)
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pytest

from gyrocore.autotune import CurrentSliders, recommend_gains
from gyrocore.autotune.recommend import (
    DEFAULT_DTERM_FILTER_HZ,
    GAIN_SCALE_MAX,
    GAIN_SCALE_MIN,
    GAIN_SCAN_STEP,
    MAX_SENSITIVITY_PEAK,
    SENSITIVITY_BIND_TOLERANCE,
    CROSSOVER_COHERENCE_MIN,
    PHASE_MARGIN_PRESETS,
    compute_low_freq_error,
    compute_mean_coherence,
    estimate_loop_delay_ms,
    find_bandwidth,
    find_max_achievable_phase_margin,
    find_noise_floor,
    find_open_loop_crossover,
    find_resonant_peak,
    find_target_crossover,
    gain_clamp_limit_of,
    integral_scale,
    js_math_round,
    peak_sensitivity_at_gain,
    resonance_backoffs,
    robust_gain,
    scan_sensitivity,
)
from gyrocore.chirp.system_id import MIN_OPEN_LOOP_HZ, TransferFunction, open_loop_response

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "tests" / "fixtures" / "autotune" / "wu8"
REF = json.loads(gzip.decompress((FIX / "upstream_autotune_reference.json.gz").read_bytes()))

CONT_RTOL = 1e-11
DB_ATOL = 1e-10
PHASE_ATOL_DEG = 1e-10
DB_KEYS = {"predictedSensitivityPeakDb", "lowFreqErrorDb", "resonantPeakDb"}
PHASE_KEYS = {"phaseMarginDeg", "maxAchievablePhaseMarginDeg"}


def num(v) -> float:
    return float(v)  # jsonReplacer writes non-finite numbers as "NaN" / "Infinity" / "-Infinity"


def arr(values) -> np.ndarray:
    return np.array([num(v) for v in values], dtype=float)


def tf_from(ut) -> TransferFunction:
    return TransferFunction(
        frequencies=arr(ut["frequencies"]),
        magnitude_db=arr(ut["magnitude"]),
        phase_deg=arr(ut["phase"]),
        coherence=arr(ut["coherence"]),
        h_real=arr(ut["hReal"]),
        h_imag=arr(ut["hImag"]),
        num_segments=ut["numSegments"] or 0,
        segment_size=0,
        sample_rate_hz=0.0,
    )


def close(actual, expected, key: str = "") -> bool:
    a, e = num(actual), num(expected)
    if math.isnan(e) or math.isinf(e):
        return (math.isnan(a) and math.isnan(e)) or a == e
    if not math.isfinite(a):
        return False
    if key in DB_KEYS:
        return abs(a - e) <= DB_ATOL
    if key in PHASE_KEYS:
        return abs(a - e) <= PHASE_ATOL_DEG
    return abs(a - e) <= CONT_RTOL * abs(e) or a == e


def vectors():
    for c in REF["synthetic"]:
        yield f"synthetic:{c['case_id']}", c["transferFunction"], c["openLoop"], c["sliders"]
    for c in REF["bbl"]:
        for ax, a in sorted(c["axes"].items()):
            if "recommendations" in a:
                yield f"bbl:{c['case_id']}:{ax}", a["transferFunction"], a["openLoop"], c["currentSliders"]


VECTORS = {vid: (tf, ol, sl) for vid, tf, ol, sl in vectors()}
RECS = {vid: recs for vid, recs in (
    [(f"synthetic:{c['case_id']}", c["recommendations"]) for c in REF["synthetic"]]
    + [(f"bbl:{c['case_id']}:{ax}", a["recommendations"]) for c in REF["bbl"] for ax, a in c["axes"].items() if "recommendations" in a]
)}
ALL_RECS = [(vid, r) for vid, recs in RECS.items() for r in recs]


def test_reference_provenance_and_constants():
    prov = REF["provenance"]
    assert prov["upstream_commit"] == "a38c4a797a86a580106162653db92af7e14be787"
    for rel, digest in prov["vendored_sha256"].items():
        assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, rel
    c = prov["constants"]
    assert c["MIN_OPEN_LOOP_HZ"] == MIN_OPEN_LOOP_HZ
    assert c["CROSSOVER_COHERENCE_MIN"] == CROSSOVER_COHERENCE_MIN
    assert c["DEFAULT_DTERM_FILTER_HZ"] == DEFAULT_DTERM_FILTER_HZ
    assert c["GAIN_SCALE_MIN"] == GAIN_SCALE_MIN
    assert c["GAIN_SCALE_MAX"] == GAIN_SCALE_MAX
    assert c["MAX_SENSITIVITY_PEAK"] == MAX_SENSITIVITY_PEAK
    assert c["SENSITIVITY_BIND_TOLERANCE"] == SENSITIVITY_BIND_TOLERANCE
    assert c["GAIN_SCAN_STEP"] == GAIN_SCAN_STEP
    assert prov["phaseMarginPresets"] == PHASE_MARGIN_PRESETS


def test_vector_counts():
    assert len(REF["synthetic"]) == 23
    assert len(REF["bbl"]) == 19
    assert len(ALL_RECS) == 139


@pytest.mark.parametrize("vid", sorted(VECTORS))
def test_open_loop_parity(vid):
    tfj, olj, _ = VECTORS[vid]
    ol = open_loop_response(tf_from(tfj))
    assert ol.start_index == olj["startIndex"]
    um, up = arr(olj["magnitude"]), arr(olj["phase"])
    assert np.array_equal(np.isnan(ol.magnitude), np.isnan(um))
    m = ~np.isnan(um)
    assert np.all(np.abs(ol.magnitude[m] - um[m]) <= CONT_RTOL * np.abs(um[m]))
    assert np.all(np.abs(ol.phase_deg[m] - up[m]) <= PHASE_ATOL_DEG)


def _crossover_matches(py, up):
    if up is None:
        return py is None
    return py is not None and close(py.frequency_hz, up["frequencyHz"])


@pytest.mark.parametrize("vid", sorted(VECTORS))
def test_recommend_gains_parity(vid):
    tfj, olj, sliders = VECTORS[vid]
    tf = tf_from(tfj)
    ol = open_loop_response(tf)
    cs = CurrentSliders.from_upstream(sliders)
    for r in RECS[vid]:
        pm = r["targetPhaseMarginDeg"]
        it = r["intermediates"]
        rec = recommend_gains(tf, cs, pm, open_loop=ol)

        # recommendGains() output: proposed sliders exact, analysis per key.
        assert rec.proposed == {k: float(v) for k, v in r["proposed"].items()}, (vid, pm)
        py = rec.analysis()
        assert set(py) == set(r["analysis"]), (vid, pm)
        for key, expected in r["analysis"].items():
            if isinstance(expected, bool):
                assert py[key] is expected, (vid, pm, key)
            else:
                assert close(py[key], expected, key), (vid, pm, key, py[key], expected)

        # Helper results.
        xo = find_open_loop_crossover(tf, ol)
        assert _crossover_matches(xo, it["crossover"]), (vid, pm)
        if xo is not None:
            assert close(xo.phase_margin_deg, it["crossover"]["phaseMarginDeg"], "phaseMarginDeg")
        tc = find_target_crossover(tf, ol, pm)
        assert _crossover_matches(tc, it["target"]), (vid, pm)
        if tc is not None:
            assert close(tc.gain_scale, it["target"]["gainScale"])
        rdb, rf = find_resonant_peak(tf)
        assert close(rf, it["resonant"]["resonantFreqHz"]) and close(rdb, it["resonant"]["resonantPeakDb"], "resonantPeakDb")
        assert close(find_bandwidth(tf), it["bandwidthHz"])
        assert close(compute_low_freq_error(tf), it["lowFreqErrorDb"], "lowFreqErrorDb")
        assert close(find_noise_floor(tf), it["noiseFloorHz"])
        assert close(compute_mean_coherence(tf), it["meanCoherence"])
        assert close(estimate_loop_delay_ms(tf, ol), it["loopDelayMs"])
        assert close(find_max_achievable_phase_margin(tf, ol), it["maxAchievablePhaseMarginDeg"], "maxAchievablePhaseMarginDeg")

        # Sensitivity scan: grid exact, peaks continuous, outcome exact.
        scan = rec.metrics.sensitivity_scan
        grid = it["metricsScanGrid"]
        assert list(scan.gains) == [num(g) for g in grid["gains"]], vid
        assert len(scan.peaks) == len(grid["peaks"])
        assert all(close(a, b) for a, b in zip(scan.peaks, grid["peaks"])), vid
        us = it["metricsScan"]
        assert close(scan.within_bound, us["withinBound"]) and close(scan.least_bad, us["leastBad"])
        assert scan.held is (not math.isfinite(num(grid["peaks"][-1])))
        assert scan_sensitivity(tf, ol, MAX_SENSITIVITY_PEAK) == scan

        # Shaping terms (computeGainScales locals) and the robust PI gain.
        s = rec.scales
        assert (s.resonance_backoff, s.ff_resonance_backoff) == (it["backoffs"]["resonanceBackoff"], it["backoffs"]["ffResonanceBackoff"])
        assert resonance_backoffs(rec.metrics.resonant_peak_db) == (s.resonance_backoff, s.ff_resonance_backoff)
        assert close(s.gain_for_margin, it["gainForMargin"])
        assert close(s.admissible_max, it["admissibleMax"])
        assert close(gain_clamp_limit_of(s.gain_clamped, s.requested_gain), it["gainClampLimit"])
        assert close(s.robust.peak_at_admissible_max, it["peakAtAdmissible"])
        rg = robust_gain(tf, ol, s.admissible_max)
        assert close(rg.pi_scale, it["robust"]["piScale"]) and rg.sensitivity_unreachable is it["robust"]["sensitivityUnreachable"]
        assert close(s.robust_pi_scale, it["robust"]["piScale"])
        if it["robustScan"] is None:
            assert rg.scan is None
        else:
            assert close(rg.scan.within_bound, it["robustScan"]["withinBound"])
            assert close(rg.scan.least_bad, it["robustScan"]["leastBad"])
        assert close(s.robustness_factor, it["robustnessFactor"])
        assert close(s.raw_i_scale, it["rawIScale"]) and s.raw_i_scale == integral_scale(rec.metrics.low_freq_error_db)
        assert close(s.raw_ff_scale, it["rawFfScale"])
        assert close(s.raw_filter_scale, it["rawFilterScale"])
        assert close(peak_sensitivity_at_gain(tf, ol, s.pi_scale), it["predictedSensitivityPeak"])

        # buildProposedSliders: current, scale, raw product, slider clamp, Math.round.
        for key, sp in rec.sliders.items():
            u = it["rawSliders"][key]
            assert sp.current == u["current"] and close(sp.scale, u["scale"]), (vid, key)
            assert close(sp.raw, u["raw"]) and close(sp.clamped, u["clamped"]), (vid, key)
            assert sp.rounded == u["rounded"] == r["proposed"][key], (vid, key)


def test_js_math_round_semantics():
    # Math.round: half toward +Infinity (not banker's rounding, not half-away-from-zero).
    xs = (0.5, 1.5, 2.5, -0.5, -1.5, -2.5, 212.5, 100.49999999999999, 0.49999999999999994)
    assert [js_math_round(x) for x in xs] == [1, 2, 3, 0, -1, -2, 213, 100, 0]
    assert math.isnan(js_math_round(math.nan))


def test_harness_clamp_stub_matches_vendored_clamp():
    """The harness stubs utils/common.ts (it imports the app model); the stubbed
    clamp must be the vendored one verbatim."""
    common = (ROOT / "third_party/betaflight/configurator/src/js/utils/common.ts").read_text()
    body = "export function clamp(value: number, min: number, max: number): number {\n    return Math.min(Math.max(value, min), max);\n}"
    assert body in common
    stub = (ROOT / "tools/chirp_reference/stage_vendored.mjs").read_text()
    assert "export function clamp(value: number, min: number, max: number): number { return Math.min(Math.max(value, min), max); }" in stub
    assert "third_party/betaflight/configurator/src/js/utils/common.ts" in REF["provenance"]["vendored_sha256"]


def _flags():
    for vid, r in ALL_RECS:
        a = r["analysis"]
        yield vid, r, a


def test_reference_vectors_reach_every_branch():
    """The fixture set must exercise every clamp / flag / fallback, not only the happy path."""
    seen = set()
    for vid, r, a in _flags():
        it = r["intermediates"]
        if a["gainClamped"] and num(a["gainClampLimit"]) == GAIN_SCALE_MAX:
            seen.add("per_pass_clamp_upper")
        if a["gainClamped"] and num(a["gainClampLimit"]) == GAIN_SCALE_MIN:
            seen.add("per_pass_clamp_lower")
        if a["sensitivityBinds"]:
            seen.add("sensitivity_binds")
        if a["sensitivityUnreachable"]:
            seen.add("sensitivity_unreachable")
        if math.isnan(num(a["targetCrossoverHz"])):
            seen.add("target_unreachable_gain_held")
        if math.isnan(num(a["openLoopCrossoverHz"])):
            seen.add("no_open_loop_crossover")
        if it["robustScan"] is not None:
            seen.add("robust_scan_run")
        if not math.isfinite(num(it["metricsScanGrid"]["peaks"][-1])):
            seen.add("scan_held_nonfinite")
        if it["backoffs"]["resonanceBackoff"] == 0.75:
            seen.add("resonance_backoff_6db")
        if it["backoffs"]["resonanceBackoff"] == 0.9:
            seen.add("resonance_backoff_3db")
        if it["rawIScale"] > 1:
            seen.add("integral_increase")
        if it["rawIScale"] < 1:
            seen.add("integral_decrease")
        if num(it["rawFilterScale"]) < 1:
            seen.add("filter_tighten")
        if num(it["rawFilterScale"]) > 1:
            seen.add("filter_capped_at_1")
        if math.isnan(num(a["noiseFloorHz"])):
            seen.add("noise_floor_nan")
        for key, sp in it["rawSliders"].items():
            if sp["raw"] > 250:
                seen.add("slider_clamp_upper")
            if sp["raw"] < 25:
                seen.add("slider_clamp_lower")
            frac = sp["clamped"] - math.floor(sp["clamped"])
            if frac == 0.5:
                seen.add("rounding_exact_half")
        if num(a["ffScale"]) != num(a["piScale"]):
            seen.add("ff_differs_from_pi")
    missing = {
        "per_pass_clamp_upper", "per_pass_clamp_lower", "sensitivity_binds", "sensitivity_unreachable",
        "target_unreachable_gain_held", "no_open_loop_crossover", "robust_scan_run", "scan_held_nonfinite",
        "resonance_backoff_6db", "resonance_backoff_3db", "integral_increase", "integral_decrease",
        "filter_tighten", "filter_capped_at_1", "noise_floor_nan", "slider_clamp_upper",
        "slider_clamp_lower", "rounding_exact_half", "ff_differs_from_pi",
    } - seen
    assert not missing, missing


def test_upstream_slider_default_substitution_vectors():
    """``currentSliders`` fields undefined -> ``?? 1`` inside buildProposedSliders."""
    case = next(c for c in REF["synthetic"] if c["case_id"] == "sliders_undefined")
    assert case["sliders"] == {}
    assert CurrentSliders.from_upstream(case["sliders"]) == CurrentSliders()
    for r in case["recommendations"]:
        for sp in r["intermediates"]["rawSliders"].values():
            assert sp["current"] == 1


def test_zero_sliders_pass_through_buildproposedsliders():
    """``?? 1`` only replaces undefined: a 0 current slider stays 0 and clamps to 25."""
    case = next(c for c in REF["synthetic"] if c["case_id"] == "sliders_zero")
    for r in case["recommendations"]:
        assert set(r["proposed"].values()) == {25}
