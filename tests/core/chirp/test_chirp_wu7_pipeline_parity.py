"""WU7: end-to-end CHIRP parity on synthetic BBL fixtures.

Each case in ``tests/fixtures/chirp/wu7/cases.json`` is a BBL that:

- the vendored Betaflight ``parseChirpLog`` + ``useAutotune`` analysis read via
  ``tools/chirp_reference/reference_harness.mjs`` (-> ``upstream_reference.json``)
- GyroCore reads via ``blackbox_decode`` -> ``identify_chirp_system``

Classification per case (``exact_upstream_parity`` / ``mathematical_equivalence`` /
``intentional_gyrocore_hardening``) is asserted below.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from gyrocore.chirp import (
    identify_chirp_system,
    identify_chirp_system_from_bbl,
    welch_transfer_function,
)
from gyrocore.chirp.sysconfig import parse_chirp_sysconfig

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "tests" / "fixtures" / "chirp" / "wu7"
MANIFEST = json.loads((FIX / "cases.json").read_text())["cases"]
UPSTREAM = {c["case_id"]: c for c in json.loads((FIX / "upstream_reference.json").read_text())["cases"]}
CASES = {c["case_id"]: c for c in MANIFEST}

H_RTOL = 1e-9
COH_ATOL = 1e-10
MAG_DB_ATOL = 1e-8
PHASE_DEG_ATOL = 1e-6
STEP_ATOL = 1e-10
SPECTROGRAM_DB_ATOL = 1e-8

needs_decoder = pytest.mark.skipif(shutil.which("blackbox_decode") is None, reason="blackbox_decode not on PATH")


def arr(values) -> np.ndarray:
    return np.array([float(v) for v in values], dtype=float)


def f32_digest(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float32).tobytes()).hexdigest()


def bbl_bytes(case_id: str) -> bytes:
    return gzip.decompress((FIX / CASES[case_id]["bbl"]).read_bytes())


_RESULTS: dict[str, object] = {}


def run_case(case_id: str, tmp_root: Path):
    if case_id not in _RESULTS:
        path = tmp_root / f"{case_id}.bbl"
        path.write_bytes(bbl_bytes(case_id))
        _RESULTS[case_id] = identify_chirp_system_from_bbl(path, include_spectrogram=True)
    return _RESULTS[case_id]


@pytest.fixture(scope="module")
def tmp_root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("wu7_bbl")


def assert_tf_matches(tf, ut):
    assert tf.num_segments == ut["numSegments"]
    assert np.array_equal(tf.frequencies, arr(ut["frequencies"]))
    expected = arr(ut["hReal"]) + 1j * arr(ut["hImag"])
    scale = np.max(np.abs(expected))
    assert np.all(np.abs(tf.h - expected) <= H_RTOL * np.abs(expected) + 1e-12 * scale)
    assert np.max(np.abs(tf.coherence - arr(ut["coherence"]))) <= COH_ATOL
    mag = arr(ut["magnitude"])
    assert np.array_equal(np.isfinite(tf.magnitude_db), np.isfinite(mag))
    fin = np.isfinite(mag)
    assert np.max(np.abs(tf.magnitude_db[fin] - mag[fin])) <= MAG_DB_ATOL
    significant = np.abs(expected) > 1e-6 * scale
    dphase = np.abs((tf.phase_deg - arr(ut["phase"]) + 180.0) % 360.0 - 180.0)
    assert np.max(dphase[significant]) <= PHASE_DEG_ATOL


def test_fixture_manifest_integrity():
    assert len(MANIFEST) >= 13
    for c in MANIFEST:
        assert hashlib.sha256(bbl_bytes(c["case_id"])).hexdigest() == c["bbl_sha256"]
        assert UPSTREAM[c["case_id"]]["bbl_sha256"] == c["bbl_sha256"]
        assert set(c["classification"]) <= {
            "exact_upstream_parity",
            "mathematical_equivalence",
            "intentional_gyrocore_hardening",
        }


@pytest.mark.parametrize("case_id", [c for c in CASES if "chirpData" in UPSTREAM[c]])
def test_sysconfig_header_parity(case_id):
    sc = parse_chirp_sysconfig(bbl_bytes(case_id))
    up = UPSTREAM[case_id]["sysConfig"]
    assert sc.upstream_value("looptime") == up["looptime"]
    assert sc.upstream_value("pid_process_denom") == up["pid_process_denom"]
    assert sc.upstream_value("p_interval_num") == up["frameIntervalPNum"]
    assert sc.upstream_value("p_interval_denom") == up["frameIntervalPDenom"]
    assert sc.upstream_value("i_interval") == up["frameIntervalI"]
    assert sc.upstream_value("debug_mode") == up["debug_mode"]
    assert sc.upstream_value("blackbox_high_resolution") == up["blackbox_high_resolution"]
    assert sc.chirp_frequency_start_deci_hz == up["chirp_frequency_start_deci_hz"]
    assert sc.chirp_frequency_end_deci_hz == up["chirp_frequency_end_deci_hz"]
    assert sc.firmware_revision == up["firmwareRevision"]


@needs_decoder
@pytest.mark.parametrize("case_id", [c for c in CASES if "chirpData" in UPSTREAM[c]])
def test_extraction_bit_exact_vs_parse_chirp_log(case_id, tmp_root):
    result = run_case(case_id, tmp_root)
    ex = result.extraction
    ud = UPSTREAM[case_id]["chirpData"]
    assert ex is not None and ex.flag_gating == "flight_mode_flags"
    assert ex.sample_count == ud["sampleCount"]
    assert [(s.axis, s.start_idx, s.end_idx) for s in ex.segments] == [
        (s["axis"], s["startIdx"], s["endIdx"]) for s in ud["segments"]
    ]
    for i in range(3):
        assert f32_digest(ex.setpoint[i]) == ud["digests"]["setpoint"][i]
        assert f32_digest(ex.gyro[i]) == ud["digests"]["gyro"][i]
    for i in range(4):
        assert f32_digest(ex.debug[i]) == ud["digests"]["debug"][i]
    selected = UPSTREAM[case_id]["analysis"]["selectedSegmentByAxis"]
    if selected:
        assert {str(a): i for a, i in ex.selected_by_axis.items()} == selected


@needs_decoder
@pytest.mark.parametrize("case_id", [c for c in CASES if "chirpData" in UPSTREAM[c]])
def test_system_id_parity_at_upstream_rate(case_id, tmp_root):
    """Same samples, same rate/segment as upstream -> same numbers (all parseable cases)."""
    result = run_case(case_id, tmp_root)
    ex = result.extraction
    ua = UPSTREAM[case_id]["analysis"]
    for useg in ua["segments"]:
        if "transferFunction" not in useg:
            continue
        seg = ex.segments[useg["index"]]
        x, y, _ = ex.segment_signals(seg)
        assert f32_digest(x) == useg["inputDigest"] and f32_digest(y) == useg["outputDigest"]
        tf = welch_transfer_function(x, y, ua["sampleRate"], ua["segmentSize"], 0.5)
        assert_tf_matches(tf, useg["transferFunction"])


@needs_decoder
@pytest.mark.parametrize(
    "case_id",
    [c for c in CASES if "exact_upstream_parity" in CASES[c]["classification"] and "chirpData" in UPSTREAM[c]],
)
def test_pipeline_matches_upstream_analysis(case_id, tmp_root):
    """Exact-parity cases: GyroCore's resolved rate/segment equal upstream's, so its outputs do too."""
    result = run_case(case_id, tmp_root)
    ua = UPSTREAM[case_id]["analysis"]
    for useg in ua["segments"]:
        if useg["index"] not in result.extraction.selected_by_axis.values():
            continue
        axis = result.axes[useg["axis"]]
        assert axis.upstream_sample_rate_hz == pytest.approx(ua["sampleRate"], rel=1e-15)
        assert axis.effective_rate_hz == pytest.approx(ua["sampleRate"], rel=1e-12)
        assert axis.segment_size == ua["segmentSize"]
        if "transferFunction" not in useg:
            assert axis.transfer_function is None
            continue
        assert_tf_matches(axis.transfer_function, useg["transferFunction"])
        us = useg["sensitivity"]
        assert axis.sensitivity.peak_db == pytest.approx(float(us["peakDb"]), abs=MAG_DB_ATOL)
        st = useg["stepResponse"]
        assert np.max(np.abs(axis.step_response.response - arr(st["response"]))) <= STEP_ATOL
        assert axis.step_response.overshoot_pct == pytest.approx(st["overshootPct"], abs=1e-7)
        assert axis.step_response.rise_time_ms == pytest.approx(st["riseTimeMs"], abs=1e-9)
        assert axis.step_response.settling_time_ms == pytest.approx(st["settlingTimeMs"], abs=1e-9)
        ol = useg["openLoop"]
        om = arr(ol["magnitude"])
        assert np.array_equal(np.isnan(axis.open_loop.magnitude), np.isnan(om))
        ok = ~np.isnan(om)
        assert np.all(np.abs(axis.open_loop.magnitude[ok] - om[ok]) <= 1e-8 * om[ok] + 1e-12)
        sg = useg["spectrogram"]
        assert (axis.spectrogram.num_segments, axis.spectrogram.num_bins) == (sg["numSegments"], sg["numBins"])
        assert np.max(np.abs(axis.spectrogram.power_db[0] - arr(sg["powerFirstRow"]))) <= SPECTROGRAM_DB_ATOL
        assert np.max(np.abs(axis.spectrogram.power_db[-1] - arr(sg["powerLastRow"]))) <= SPECTROGRAM_DB_ATOL
        assert float(axis.spectrogram.power_db.sum()) == pytest.approx(sg["powerSum"], rel=1e-12)


@needs_decoder
@pytest.mark.parametrize("case_id", list(CASES))
def test_case_expectations(case_id, tmp_root):
    expect = CASES[case_id]["expect"]
    result = run_case(case_id, tmp_root)
    if "error" in expect:
        assert result.status == "error"
        assert result.errors[0].split(":", 1)[0] == expect["error"]
        assert "parseError" in UPSTREAM[case_id]
        return
    assert result.usable is expect["usable"], result.to_dict(include_arrays=False)
    failed = {code.split(":", 1)[1] for code in result.errors}
    for gate in expect.get("gates", []):
        assert gate in failed
    if expect["usable"]:
        assert not failed
    if "effective_rate_hz" in expect:
        assert all(a.effective_rate_hz == pytest.approx(expect["effective_rate_hz"]) for a in result.axes.values())
    if "rate_source" in expect:
        assert all(a.sample_rate.source.value == expect["rate_source"] for a in result.axes.values())
    if "axes" in expect:
        assert sorted(result.axes) == expect["axes"]


@needs_decoder
@pytest.mark.parametrize(
    "case_id,gain,delay",
    [("known_gain", 0.5, 0), ("known_phase_delay", 1.0, 4), ("log_rate_below_pid", 0.9, 1)],
)
def test_known_plant_recovered(case_id, gain, delay, tmp_root):
    """Mathematical equivalence: H recovers the synthetic plant inside the usable band."""
    axis = run_case(case_id, tmp_root).axes[0]
    tf = axis.transfer_function
    f = tf.frequencies
    band = axis.quality.usable_mask & (f >= 5) & (f <= 100)
    assert band.sum() >= 20
    assert np.max(np.abs(np.abs(tf.h[band]) / gain - 1.0)) < 0.08
    expected_phase = -360.0 * f[band] * delay / tf.sample_rate_hz
    dphase = np.abs((np.angle(tf.h[band], deg=True) - expected_phase + 180.0) % 360.0 - 180.0)
    assert np.max(dphase) < 1.0


@needs_decoder
def test_three_axis_gains_and_delays(tmp_root):
    result = run_case("three_axis_sequence", tmp_root)
    for axis, gain, delay in ((0, 1.0, 1), (1, 0.9, 2), (2, 0.7, 3)):
        a = result.axes[axis]
        f = a.transfer_function.frequencies
        band = a.quality.usable_mask & (f >= 5) & (f <= 100)
        h = a.transfer_function.h[band]
        assert np.max(np.abs(np.abs(h) / gain - 1.0)) < 0.08
        exp = -360.0 * f[band] * delay / a.effective_rate_hz
        assert np.max(np.abs((np.angle(h, deg=True) - exp + 180.0) % 360.0 - 180.0)) < 1.0


@needs_decoder
def test_repeated_axis_keeps_last_segment_like_upstream(tmp_root):
    result = run_case("repeated_axis", tmp_root)
    assert len(result.extraction.segments) == 2
    assert result.extraction.selected_by_axis == {0: 1}
    tf = result.axes[0].transfer_function
    band = (tf.frequencies >= 5) & (tf.frequencies <= 100)
    assert np.allclose(np.abs(tf.h[band]), 1.0, atol=1e-9)
    assert "repeated_axis_segments_last_selected" in result.warnings


# --- intentional GyroCore hardening (documented divergences) ---------------


@needs_decoder
def test_hardening_pnum_pdenom(tmp_root):
    result = run_case("pnum_pdenom", tmp_root)
    axis = result.axes[0]
    up = UPSTREAM["pnum_pdenom"]["analysis"]
    assert up["sampleRate"] == pytest.approx(2000.0 / 3.0)
    assert axis.upstream_sample_rate_hz == pytest.approx(up["sampleRate"])
    assert axis.sample_rate.header_rate_hz == pytest.approx(4000.0 / 3.0)
    assert not axis.spacing.uniform
    assert not result.usable
    assert "roll:non_uniform_sampling" in result.errors


@needs_decoder
def test_hardening_missing_rate_headers(tmp_root):
    result = run_case("malformed_missing_rate_headers", tmp_root)
    up = UPSTREAM["malformed_missing_rate_headers"]["analysis"]
    assert up["sampleRate"] == 8000 and up["result"] is None  # upstream silently assumes 8 kHz, skips axis
    axis = result.axes[0]
    assert axis.effective_rate_hz == pytest.approx(1000.0)
    assert axis.sample_rate.status.value == "timestamp_only"
    assert result.status == "usable_with_warnings"


@needs_decoder
def test_hardening_dropped_frames_detected(tmp_root):
    result = run_case("dropped_timestamps", tmp_root)
    assert UPSTREAM["dropped_timestamps"]["analysis"]["result"] == "axes"  # upstream analyses it
    spacing = result.axes[0].spacing
    assert spacing.gap_count == 6 and spacing.missing_samples_estimate == 90
    assert not result.usable


@needs_decoder
def test_hardening_insufficient_samples(tmp_root):
    result = run_case("insufficient_samples", tmp_root)
    assert UPSTREAM["insufficient_samples"]["analysis"]["result"] is None
    assert result.axes[0].transfer_function is None
    assert "roll:insufficient_samples" in result.errors


@needs_decoder
def test_csv_route_equals_bbl_route(tmp_root):
    from gyrocore.decode import decode_bbl

    path = tmp_root / "clean_single_axis.bbl"
    path.write_bytes(bbl_bytes("clean_single_axis"))
    decoded = decode_bbl(path)
    r1 = identify_chirp_system(csv_text=decoded.csv_text, headers=bbl_bytes("clean_single_axis"))
    r2 = run_case("clean_single_axis", tmp_root)
    assert np.array_equal(r1.axes[0].transfer_function.h, r2.axes[0].transfer_function.h)


@needs_decoder
def test_result_is_analysis_only(tmp_root):
    d = run_case("clean_single_axis", tmp_root).to_dict()
    assert d["analysis_only"] is True and d["tuning_recommendations"] is None
    provenance = d.pop("provenance")
    assert "spectral_analysis.ts:recommendGains" in provenance["not_ported"]
    text = json.dumps(d).lower()
    for forbidden in ("recommendgains", "proposed", "msp", "cli_command", "pid_apply", "gains"):
        assert forbidden not in text
    axis = d["axes"]["roll"]
    for key in ("effective_rate_hz", "transfer_function", "usable_mask", "quality", "segment"):
        assert key in axis
    tf = axis["transfer_function"]
    for key in ("frequencies_hz", "h_real", "h_imag", "magnitude_db", "phase_deg", "coherence"):
        assert key in tf
