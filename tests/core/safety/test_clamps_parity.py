"""Donor vs GyroCore safe-tune clamp parity (WU10)."""

from __future__ import annotations

import copy
import os
import sys
from pathlib import Path

import pytest

from gyrocore.safety.clamps import (
    DEFAULT_MAX_DELTA,
    apply_safety,
    apply_safety_autotune,
    apply_to_baseline,
    scale_max_delta,
)
from gyrocore.safety.thermal import clamp_targets_to_baseline_thermal, classify_thermal_motor_risk

REPO = Path(__file__).resolve().parents[3]


def _aerotuner_root() -> Path:
    return Path(os.environ.get("AEROTUNER_ROOT", REPO.parent / "aerotuner"))


def _import_donor():
    root = _aerotuner_root()
    if not (root / "backend/services/tuning_safe_v2.py").is_file():
        pytest.skip("AeroTuner donor not available")
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from backend.services import tuning_safe_v2 as v2
    from backend.services import tuning_safety_policy as tsp

    return v2, tsp


def _cfg(*, p=45, i=80, d=30, ff=120, d_max=40, gyro=250, dmin=75, dmax=150) -> dict:
    return {
        "pid": {
            "roll": {"p": p, "i": i, "d": d, "ff": ff},
            "pitch": {"p": p + 2, "i": i + 4, "d": d + 4, "ff": ff + 5},
            "yaw": {"p": p, "i": i, "d": 0, "ff": ff},
        },
        "filters": {
            "gyro_lpf1_static_hz": gyro,
            "gyro_lpf1_dyn_min_hz": gyro,
            "gyro_lpf1_dyn_max_hz": 500,
            "gyro_lpf2_static_hz": 500,
            "dterm_lpf1_dyn_min_hz": dmin,
            "dterm_lpf1_dyn_max_hz": dmax,
            "dterm_lpf2_static_hz": 150,
        },
    }


def test_apply_to_baseline_matches_donor_without_d_max():
    v2, _ = _import_donor()
    base = _cfg()
    tgt = _cfg(p=90, i=160, d=80, ff=200, gyro=180, dmin=40, dmax=200)
    donor_delta = copy.deepcopy(v2.DEFAULT_MAX_DELTA)
    gc_delta = copy.deepcopy(DEFAULT_MAX_DELTA)
    for ax in gc_delta["pid"].values():
        ax.pop("d_max", None)
    got = apply_to_baseline(base, tgt, gc_delta)
    exp = v2.apply_to_baseline(base, tgt, donor_delta)
    assert got["pid"]["roll"]["p"] == exp["pid"]["roll"]["p"]
    assert got["pid"]["roll"]["i"] == exp["pid"]["roll"]["i"]
    assert got["pid"]["roll"]["d"] == exp["pid"]["roll"]["d"]
    assert got["pid"]["roll"]["ff"] == exp["pid"]["roll"]["ff"]
    assert got["filters"]["dterm_lpf1_dyn_min_hz"] == exp["filters"]["dterm_lpf1_dyn_min_hz"]
    assert got["filters"]["gyro_lpf1_static_hz"] == exp["filters"]["gyro_lpf1_static_hz"]


def test_p_i_d_ff_filter_step_caps():
    base = _cfg()
    tgt = _cfg(p=90, i=200, d=90, ff=250, gyro=100, dmin=40, dmax=400)
    out = apply_to_baseline(base, tgt, DEFAULT_MAX_DELTA)
    assert out["pid"]["roll"]["p"] == 45 + 4
    assert out["pid"]["roll"]["i"] == 80 + 8
    assert out["pid"]["roll"]["d"] == 30 + 6
    assert out["pid"]["roll"]["ff"] == 120 + 8
    assert out["filters"]["gyro_lpf1_static_hz"] == 250 - 44
    assert out["filters"]["dterm_lpf1_dyn_min_hz"] == 75 - 20


def test_d_max_uses_d_step_gyrocore_bridge():
    base = _cfg()
    base["pid"]["roll"]["d_max"] = 40
    tgt = copy.deepcopy(base)
    tgt["pid"]["roll"]["d_max"] = 80
    out = apply_to_baseline(base, tgt, DEFAULT_MAX_DELTA)
    assert out["pid"]["roll"]["d_max"] == 46


def test_apply_safety_matches_donor():
    v2, _ = _import_donor()
    cfg = _cfg(p=200, d=3, ff=300, gyro=50, dmin=10, dmax=400)
    gc, gc_lim = apply_safety(copy.deepcopy(cfg))
    donor, donor_lim = v2.apply_safety(copy.deepcopy(cfg))
    assert gc["pid"]["roll"]["p"] == donor["pid"]["roll"]["p"] == 100
    assert gc["pid"]["roll"]["d"] == donor["pid"]["roll"]["d"] == 5
    assert gc["pid"]["roll"]["ff"] == donor["pid"]["roll"]["ff"] == 220
    assert gc["filters"]["gyro_lpf1_static_hz"] == donor["filters"]["gyro_lpf1_static_hz"] == 120
    assert gc["filters"]["dterm_lpf1_dyn_min_hz"] == donor["filters"]["dterm_lpf1_dyn_min_hz"] == 70
    for key in donor_lim:
        assert key in gc_lim


def test_apply_safety_confidence_blend_and_weight():
    v2, _ = _import_donor()
    base = _cfg()
    cfg = _cfg(p=90, d=50)
    gc, gc_lim = apply_safety(copy.deepcopy(cfg), hardware={"weight": 900}, confidence=0.2, baseline=base)
    donor, donor_lim = v2.apply_safety(copy.deepcopy(cfg), hardware={"weight": 900}, confidence=0.2, baseline=base)
    assert "confidence_blend_50pct_toward_baseline" in gc_lim
    assert "hardware_weight_d_scaled_90pct" in gc_lim
    assert gc["pid"]["roll"]["d"] == pytest.approx(donor["pid"]["roll"]["d"])
    assert gc["pid"]["roll"]["p"] == pytest.approx(donor["pid"]["roll"]["p"])


def test_zero_hz_filter_not_raised_on_autotune_path():
    cfg = _cfg(gyro=0)
    cfg["filters"]["gyro_lpf1_static_hz"] = 0
    cfg["filters"]["gyro_lpf1_dyn_min_hz"] = 0
    cfg["filters"]["gyro_lpf1_dyn_max_hz"] = 0
    out, limits = apply_safety_autotune(cfg)
    assert out["filters"]["gyro_lpf1_static_hz"] == 0.0
    assert "gyro_lpf1_static_hz_clamped_min_120" not in limits
    donor_out, _ = apply_safety(copy.deepcopy(cfg))
    assert donor_out["filters"]["gyro_lpf1_static_hz"] == 120


def test_thermal_envelope_blocks_d_up_and_filter_opening():
    v2, tsp = _import_donor()
    base = _cfg(d=30, dmax=150, gyro=250)
    tgt = _cfg(d=50, dmax=200, gyro=400)
    analysis = {
        "problems": [{"type": "motor_issue", "severity": "high"}],
        "motor_diagnostics": {"health": 0.4, "has_desync_risk": False},
    }
    assert classify_thermal_motor_risk(analysis)["thermal_risk"] is True
    gc = clamp_targets_to_baseline_thermal(tgt, base, thermal_risk=True, locks=[])
    donor = tsp.clamp_targets_to_baseline_thermal(tgt, base, thermal_risk=True, locks=[])
    assert gc["pid"]["roll"]["d"] == donor["pid"]["roll"]["d"] == 30
    assert gc["filters"]["gyro_lpf1_static_hz"] == donor["filters"]["gyro_lpf1_static_hz"] == 250


def test_mechanical_scale_zero_freezes_baseline():
    base = _cfg()
    tgt = _cfg(p=90, i=160, d=80, ff=200)
    out = apply_to_baseline(base, tgt, scale_max_delta(DEFAULT_MAX_DELTA, 0.0))
    assert out["pid"]["roll"]["p"] == 45
    assert out["pid"]["roll"]["i"] == 80
    assert out["pid"]["roll"]["d"] == 30
    assert out["pid"]["roll"]["ff"] == 120
