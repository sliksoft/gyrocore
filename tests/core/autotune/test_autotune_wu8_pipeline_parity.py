"""WU8: end-to-end Autotune recommendation parity on closed-loop BBL fixtures.

Each case in ``tests/fixtures/autotune/wu8/bbl_cases.json`` is a simulated
closed-loop CHIRP BBL (``tools/autotune_reference/make_autotune_cases.py``):

- upstream: vendored ``parseChirpLog`` -> ``extractCurrentSliders`` ->
  ``computeAxisResult`` (welch -> ``recommendGains``) via
  ``tools/autotune_reference/autotune_harness.mjs``
- GyroCore: ``blackbox_decode`` -> ``identify_chirp_system`` (WU7) ->
  ``extract_current_tune`` -> ``recommend_from_system_id``

Here the transfer function is GyroCore's own (WU7 parity ~1e-13), so continuous
tolerances are looser than the math-parity file (``E2E_RTOL``); every discrete
output — proposed sliders, flags, clamp limits — must still be identical.

Intentional differences (``intentional_gyrocore_hardening``): GyroCore blocks
where upstream silently recommends (unusable system ID, invalid sample rate,
missing / zero sliders, ``simplified_pids_mode`` OFF, yaw in RP mode).
"""

from __future__ import annotations

import gzip
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pytest

from gyrocore.autotune import (
    REQUIRED_DOWNSTREAM_STAGES,
    RecommendationStatus,
    extract_current_tune,
    recommend_autotune_from_bbl,
    recommend_from_system_id,
)
from gyrocore.chirp import identify_chirp_system
from gyrocore.chirp.sysconfig import read_bbl_header_text

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "tests" / "fixtures" / "autotune" / "wu8"
MANIFEST = json.loads((FIX / "bbl_cases.json").read_text())
CASES = {c["case_id"]: c for c in MANIFEST["cases"]}
SYNTHETIC = json.loads((FIX / "synthetic_cases.json").read_text())["cases"]
REF = json.loads(gzip.decompress((FIX / "upstream_autotune_reference.json.gz").read_bytes()))
UPSTREAM = {c["case_id"]: c for c in REF["bbl"]}
PRESETS = MANIFEST["presets"]

H_RTOL = 1e-9
E2E_RTOL = 1e-9
E2E_DB_ATOL = 1e-8
E2E_PHASE_ATOL_DEG = 1e-7
DB_KEYS = {"predictedSensitivityPeakDb", "lowFreqErrorDb", "resonantPeakDb"}
PHASE_KEYS = {"phaseMarginDeg", "maxAchievablePhaseMarginDeg"}

# Python blocks by design while upstream emits sliders (see module docstring).
UPSTREAM_RECOMMENDS_GYROCORE_BLOCKS = {
    "low_coherence": {0: ["system_id:low_coherence"]},
    "insufficient_frequency_range": {0: ["system_id:unusable_frequency_range"]},
    "invalid_sample_rate": {0: ["system_id:invalid_sample_rate"]},
    "missing_tune_headers": {0: ["current_tune_missing:pi_gain"]},
    "zero_slider": {0: ["current_tune_zero:feedforward_gain"]},
    "pids_mode_off": {0: ["simplified_pids_mode_off"]},
    "pids_mode_rp_yaw": {2: ["yaw_not_under_slider_control"]},
}

REQUIRED_COVERAGE = {
    "nominal_roll", "nominal_pitch", "nominal_yaw", "low_plant_gain", "high_plant_gain", "delayed_plant",
    "noisy_usable", "near_quality_threshold", "low_coherence", "insufficient_frequency_range",
    "invalid_sample_rate", "slider_clamp_upper", "slider_clamp_lower", "unusual_current_pids",
    "missing_current_tune", "logging_rate_2k", "logging_rate_4k", "logging_rate_below_pid",
}

needs_decoder = pytest.mark.skipif(shutil.which("blackbox_decode") is None, reason="blackbox_decode not on PATH")


def num(v) -> float:
    return float(v)


def arr(values) -> np.ndarray:
    return np.array([num(v) for v in values], dtype=float)


def close(actual, expected, key: str) -> bool:
    a, e = num(actual), num(expected)
    if not math.isfinite(e):
        return (math.isnan(a) and math.isnan(e)) or a == e
    if not math.isfinite(a):
        return False
    if key in DB_KEYS:
        return abs(a - e) <= E2E_DB_ATOL
    if key in PHASE_KEYS:
        return abs(a - e) <= E2E_PHASE_ATOL_DEG
    return abs(a - e) <= E2E_RTOL * abs(e) or a == e


_SID: dict[str, tuple] = {}


def system_id_for(case_id: str, tmp_root: Path):
    if case_id not in _SID:
        from gyrocore.decode import decode_bbl

        path = tmp_root / f"{case_id}.bbl"
        path.write_bytes(gzip.decompress((FIX / CASES[case_id]["bbl"]).read_bytes()))
        decoded = decode_bbl(path)
        headers = read_bbl_header_text(path.read_bytes(), decoded.decoded_embedded_log_index or 0)
        sid = identify_chirp_system(csv_text=decoded.csv_text, headers=headers)
        _SID[case_id] = (path, sid, extract_current_tune(headers=headers))
    return _SID[case_id]


@pytest.fixture(scope="module")
def tmp_root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("wu8_bbl")


def test_fixture_integrity_and_coverage():
    import hashlib

    for c in MANIFEST["cases"]:
        assert hashlib.sha256(gzip.decompress((FIX / c["bbl"]).read_bytes())).hexdigest() == c["bbl_sha256"]
        assert UPSTREAM[c["case_id"]]["bbl_sha256"] == c["bbl_sha256"]
    covered = {x for c in MANIFEST["cases"] for x in c["covers"]} | {x for c in SYNTHETIC for x in c["covers"]}
    assert REQUIRED_COVERAGE <= covered, REQUIRED_COVERAGE - covered
    rates = {c["nominal_log_rate_hz"] for c in MANIFEST["cases"]}
    assert {1000.0, 2000.0, 4000.0} <= rates


@needs_decoder
@pytest.mark.parametrize("case_id", sorted(CASES))
def test_upstream_slider_defaults_mode_matches_upstream(case_id, tmp_root):
    """With upstream's ``|| 100`` substitution allowed, every axis GyroCore's
    system-ID gate passes must reproduce upstream exactly (discrete) / within
    E2E tolerances (continuous)."""
    _, sid, tune = system_id_for(case_id, tmp_root)
    up = UPSTREAM[case_id]
    assert tune.upstream_current_sliders().to_dict() == {
        "master_multiplier": up["currentSliders"]["masterMultiplier"],
        "pi_gain": up["currentSliders"]["piGain"],
        "i_gain": up["currentSliders"]["iGain"],
        "d_gain": up["currentSliders"]["dGain"],
        "feedforward_gain": up["currentSliders"]["feedforwardGain"],
        "dterm_filter_multiplier": up["currentSliders"]["dtermFilterMultiplier"],
    }
    compared = 0
    for i, pm in enumerate(PRESETS):
        res = recommend_from_system_id(sid, tune, target_phase_margin_deg=pm, allow_upstream_slider_defaults=True)
        for ax_key, ua in up["axes"].items():
            axr = res.axis(int(ax_key))
            assert axr is not None
            if axr.recommendation is None:
                assert any(r.startswith("system_id:") for r in axr.blocked_reasons), (case_id, ax_key)
                continue
            assert math.isclose(axr.sample_rate_hz, up["sampleRate"], rel_tol=1e-12)
            tf = axr.system_id.transfer_function
            ut = ua["transferFunction"]
            assert np.array_equal(tf.frequencies, arr(ut["frequencies"]))
            expected_h = arr(ut["hReal"]) + 1j * arr(ut["hImag"])
            assert np.max(np.abs(tf.h - expected_h)) <= H_RTOL * np.max(np.abs(expected_h))
            ur = ua["recommendations"][i]
            assert ur["targetPhaseMarginDeg"] == pm
            rec = axr.recommendation
            assert rec.proposed == {k: float(v) for k, v in ur["proposed"].items()}, (case_id, ax_key, pm)
            py = rec.analysis()
            for key, expected in ur["analysis"].items():
                if isinstance(expected, bool):
                    assert py[key] is expected, (case_id, ax_key, pm, key)
                else:
                    assert close(py[key], expected, key), (case_id, ax_key, pm, key, py[key], expected)
            for key, expected in ur["intermediates"]["rawSliders"].items():
                assert rec.sliders[key].rounded == expected["rounded"]
                assert close(rec.sliders[key].raw, expected["raw"], key)
            compared += 1
    expected_blocks = UPSTREAM_RECOMMENDS_GYROCORE_BLOCKS.get(case_id, {})
    system_id_blocked = [ax for ax, reasons in expected_blocks.items() if any(r.startswith("system_id:") for r in reasons)]
    assert compared == len(PRESETS) * (len(up["axes"]) - len(system_id_blocked)), case_id


@needs_decoder
@pytest.mark.parametrize("case_id", sorted(CASES))
def test_gated_result_matches_case_expectation(case_id, tmp_root):
    _, sid, tune = system_id_for(case_id, tmp_root)
    expect = CASES[case_id]["expect"]
    up = UPSTREAM[case_id]
    res = recommend_from_system_id(sid, tune)
    assert res.actionable is False and res.to_dict()["actionable"] is False
    assert res.required_downstream_stages == REQUIRED_DOWNSTREAM_STAGES
    if "status" in expect:
        assert res.status.value == expect["status"], res.to_dict()["warnings"]
        assert sorted(a for a in res.axes) == expect["axes"]
    if expect.get("blocked") is False:
        assert all(not a.blocked for a in res.axes.values()), {a.axis: a.blocked_reasons for a in res.axes.values()}
        assert res.status is not RecommendationStatus.BLOCKED
    if expect.get("blocked") is True:
        assert res.status is RecommendationStatus.BLOCKED
        for axr in res.axes.values():
            assert axr.blocked and axr.proposed_sliders_unvalidated is None and axr.proposed_raw is None
            for reason in expect["reasons"]:
                assert reason in axr.blocked_reasons, axr.blocked_reasons
    if "blocked_axes" in expect:
        assert sorted(a.axis for a in res.axes.values() if a.blocked) == expect["blocked_axes"]
        assert res.status is RecommendationStatus.PROPOSED_WITH_WARNINGS
    for ax, reasons in UPSTREAM_RECOMMENDS_GYROCORE_BLOCKS.get(case_id, {}).items():
        ua = up["axes"][str(ax)]
        assert len(ua["recommendations"]) == len(PRESETS), "upstream must have recommended"
        axr = res.axis(ax)
        assert axr.blocked
        for reason in reasons:
            assert reason in axr.blocked_reasons
    for axr in res.axes.values():
        if not axr.blocked:
            ur = up["axes"][str(axr.axis)]["recommendations"][PRESETS.index(60.0)]
            assert axr.proposed_sliders_unvalidated == {k: int(v) for k, v in ur["proposed"].items()}


@needs_decoder
def test_invalid_sample_rate_upstream_uses_8khz_fallback(tmp_root):
    """With the timing headers absent, upstream ``parseHeader`` keeps its
    ``looptime: 125`` default and ``computeSampleRate`` yields 8 kHz; upstream
    recommends anyway, GyroCore refuses."""
    assert "looptime" not in CASES["invalid_sample_rate"]["headers"]
    up = UPSTREAM["invalid_sample_rate"]
    assert up["sampleRate"] == 8000
    assert up["sysConfig"]["looptime"] == 125
    _, sid, tune = system_id_for("invalid_sample_rate", tmp_root)
    res = recommend_from_system_id(sid, tune)
    assert res.status is RecommendationStatus.BLOCKED
    assert all(a.recommendation is None for a in res.axes.values())


@needs_decoder
def test_bbl_entry_point_and_rate_matrix(tmp_root):
    for case_id, rate in (("nominal_three_axis", 1000.0), ("log_rate_2k", 2000.0), ("log_rate_4k", 4000.0), ("log_rate_below_pid", 1000.0)):
        path, _, _ = system_id_for(case_id, tmp_root)
        res = recommend_autotune_from_bbl(path)
        assert res.status is not RecommendationStatus.BLOCKED, case_id
        for axr in res.axes.values():
            assert axr.sample_rate_hz == pytest.approx(rate, rel=1e-12)
            assert "sample_rate_differs_from_upstream_autotune" not in axr.warnings
            assert axr.sample_rate_hz == pytest.approx(UPSTREAM[case_id]["sampleRate"], rel=1e-12)


@needs_decoder
def test_nominal_three_axis_values(tmp_root):
    """Pinned nominal outcome so a silent shift in system ID or recommendation shows up here."""
    _, sid, tune = system_id_for("nominal_three_axis", tmp_root)
    res = recommend_from_system_id(sid, tune)
    roll, pitch, yaw = (res.axis(a) for a in ("roll", "pitch", "yaw"))
    assert roll.proposed_sliders_unvalidated["slider_pi_gain"] == 109
    assert pitch.proposed_sliders_unvalidated["slider_pi_gain"] == 121
    assert yaw.proposed_sliders_unvalidated["slider_pi_gain"] == 50
    assert "autotune:gain_clamped_per_pass:0.5" in yaw.warnings
    assert "per_axis_proposals_differ_sliders_are_global" in res.warnings
    for axr in (roll, pitch, yaw):
        assert axr.proposed_sliders_unvalidated["slider_d_gain"] == 100  # dScale is always 1
        assert axr.proposed_sliders_unvalidated["slider_master_multiplier"] == 100


@needs_decoder
def test_slider_clamp_cases(tmp_root):
    _, sid, tune = system_id_for("slider_upper_clamp", tmp_root)
    up = recommend_from_system_id(sid, tune).axis(0)
    assert up.proposed_raw["slider_pi_gain"]["raw"] > 250
    assert up.proposed_sliders_unvalidated["slider_pi_gain"] == 250
    assert "autotune:slider_clamped:slider_pi_gain" in up.warnings
    _, sid, tune = system_id_for("slider_lower_clamp", tmp_root)
    lo = recommend_from_system_id(sid, tune).axis(0)
    assert lo.proposed_raw["slider_pi_gain"]["raw"] < 25
    assert lo.proposed_sliders_unvalidated["slider_pi_gain"] == 25
    assert "autotune:slider_clamped:slider_pi_gain" in lo.warnings


@needs_decoder
def test_near_threshold_and_noisy_are_usable(tmp_root):
    for case_id in ("noisy_usable", "near_quality_threshold"):
        _, sid, tune = system_id_for(case_id, tmp_root)
        axr = recommend_from_system_id(sid, tune).axis(0)
        assert not axr.blocked, axr.blocked_reasons
        assert axr.system_id.quality.usable
    mc = UPSTREAM["near_quality_threshold"]["axes"]["0"]["recommendations"][1]["analysis"]["meanCoherence"]
    assert 0.5 < mc < 0.7
