"""WU9 firmware numerical/validity parity: Python vs compiled simplified_tuning.c."""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import sys
from pathlib import Path

import pytest

from gyrocore.betaflight.simplified_tuning import (
    DTERM_LPF1_DYN_MAX_HZ_DEFAULT,
    DTERM_LPF1_DYN_MIN_HZ_DEFAULT,
    DTERM_LPF2_HZ_DEFAULT,
    GYRO_LPF1_DYN_MAX_HZ_DEFAULT,
    GYRO_LPF1_DYN_MIN_HZ_DEFAULT,
    GYRO_LPF2_HZ_DEFAULT,
    PID_PITCH_DEFAULT,
    PID_ROLL_DEFAULT,
    PID_SIMPLIFIED_TUNING_OFF,
    PID_SIMPLIFIED_TUNING_RP,
    PID_SIMPLIFIED_TUNING_RPY,
    PID_YAW_DEFAULT,
    AxisPid,
    FilterSet,
    GyroConfigState,
    PidProfileState,
    SimplifiedSliders,
    apply_simplified_tuning_dterm_filters,
    apply_simplified_tuning_gyro_filters,
    apply_simplified_tuning_pids,
    firmware_default_gyro,
    firmware_default_pid_profile,
    validate_simplified_tuning,
)

ROOT = Path(__file__).resolve().parents[3]
BUILD_PY = ROOT / "tools" / "simplified_tuning_reference" / "build.py"
FIRMWARE = ROOT / "third_party" / "betaflight" / "firmware"


def _load_build():
    spec = importlib.util.spec_from_file_location("simplified_tuning_ref_build", BUILD_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    build = _load_build()
    dest = tmp_path_factory.mktemp("st_harness") / "harness"
    return build.build(dest), build


def _pid_line(s: SimplifiedSliders) -> str:
    return (
        f"PID {int(s.pids_mode)} {int(s.master_multiplier)} {int(s.pitch_d_gain)} "
        f"{int(s.i_gain)} {int(s.d_gain)} {int(s.pi_gain)} {int(s.d_max_gain)} "
        f"{int(s.feedforward_gain)} {int(s.pitch_pi_gain)}"
    )


def _py_pid_tuple(profile: PidProfileState) -> tuple[int, ...]:
    out: list[int] = []
    for ax in (profile.roll, profile.pitch, profile.yaw):
        out.extend((ax.p, ax.i, ax.d, ax.f, ax.d_max))
    return tuple(out)


def _parse_pid(line: str) -> tuple[int, ...]:
    return tuple(int(x) for x in line.split())


def _sliders(**kw) -> SimplifiedSliders:
    return SimplifiedSliders(**kw)


def _pid_cases() -> list[SimplifiedSliders]:
    cases = [
        _sliders(),  # all 100, RPY
        _sliders(pids_mode=PID_SIMPLIFIED_TUNING_OFF),
        _sliders(pids_mode=PID_SIMPLIFIED_TUNING_RP),
        _sliders(pids_mode=PID_SIMPLIFIED_TUNING_RPY),
    ]
    bounds = (0, 10, 25, 50, 99, 100, 111, 150, 199, 200, 250)
    fields = (
        "master_multiplier",
        "pi_gain",
        "i_gain",
        "d_gain",
        "d_max_gain",
        "feedforward_gain",
        "pitch_pi_gain",
        "pitch_d_gain",
    )
    for name in fields:
        for v in bounds:
            cases.append(_sliders(**{name: v}))
    # combined lower / upper
    cases.append(
        _sliders(
            master_multiplier=25,
            pi_gain=25,
            i_gain=25,
            d_gain=25,
            d_max_gain=25,
            feedforward_gain=25,
            pitch_pi_gain=25,
            pitch_d_gain=25,
        )
    )
    cases.append(
        _sliders(
            master_multiplier=200,
            pi_gain=200,
            i_gain=200,
            d_gain=200,
            d_max_gain=200,
            feedforward_gain=200,
            pitch_pi_gain=200,
            pitch_d_gain=200,
        )
    )
    cases.append(
        _sliders(
            master_multiplier=250,
            pi_gain=250,
            i_gain=250,
            d_gain=250,
            d_max_gain=250,
            feedforward_gain=250,
            pitch_pi_gain=250,
            pitch_d_gain=250,
        )
    )
    # rounding / clamp neighbourhoods
    for master, pi, d, pitch_pi in itertools.product((111, 133, 187), (100, 111), (100, 147), (100, 113)):
        cases.append(_sliders(master_multiplier=master, pi_gain=pi, d_gain=d, pitch_pi_gain=pitch_pi))
    return cases


def test_harness_stub_defaults_match_vendored_headers():
    pid_h = (FIRMWARE / "src/main/flight/pid.h").read_text()
    gyro_h = (FIRMWARE / "src/main/sensors/gyro.h").read_text()
    assert "PID_ROLL_DEFAULT  { 45, 80, 30, 120, 0 }" in pid_h
    assert PID_ROLL_DEFAULT == (45, 80, 30, 120, 0)
    assert PID_PITCH_DEFAULT == (47, 84, 34, 125, 0)
    assert PID_YAW_DEFAULT == (45, 80, 0, 120, 0)
    assert "DTERM_LPF1_DYN_MIN_HZ_DEFAULT" in pid_h
    assert DTERM_LPF1_DYN_MIN_HZ_DEFAULT == 75
    assert DTERM_LPF1_DYN_MAX_HZ_DEFAULT == 150
    assert DTERM_LPF2_HZ_DEFAULT == 150
    assert GYRO_LPF1_DYN_MIN_HZ_DEFAULT == 250
    assert GYRO_LPF1_DYN_MAX_HZ_DEFAULT == 500
    assert GYRO_LPF2_HZ_DEFAULT == 500
    assert "#define GYRO_LPF2_HZ_DEFAULT" in gyro_h


def test_pid_mapping_matches_c_harness(harness):
    binary, build = harness
    cases = _pid_cases()
    lines = [_pid_line(s) for s in cases]
    out = build.run_batch(lines, binary)
    assert len(out) == len(cases)
    for sliders, cline in zip(cases, out, strict=True):
        py = apply_simplified_tuning_pids(_with_sliders(firmware_default_pid_profile(), sliders))
        assert _py_pid_tuple(py) == _parse_pid(cline), sliders.to_dict()


def _with_sliders(profile: PidProfileState, sliders: SimplifiedSliders) -> PidProfileState:
    from dataclasses import replace

    return replace(profile, sliders=sliders)


def test_all_sliders_100_are_firmware_defaults(harness):
    binary, build = harness
    (cline,) = build.run_batch([_pid_line(_sliders())], binary)
    py = apply_simplified_tuning_pids(_with_sliders(firmware_default_pid_profile(), _sliders()))
    assert _py_pid_tuple(py) == _parse_pid(cline)
    assert py.roll == AxisPid(45, 80, 30, 120, 40)
    assert py.pitch == AxisPid(47, 84, 34, 125, 46)
    assert py.yaw == AxisPid(45, 80, 0, 120, 0)


def test_mode_rp_leaves_yaw_untouched(harness):
    binary, build = harness
    s = _sliders(pids_mode=PID_SIMPLIFIED_TUNING_RP, master_multiplier=200)
    (cline,) = build.run_batch([_pid_line(s)], binary)
    py = apply_simplified_tuning_pids(_with_sliders(firmware_default_pid_profile(), s))
    assert _py_pid_tuple(py) == _parse_pid(cline)
    assert (py.yaw.p, py.yaw.i, py.yaw.d, py.yaw.f, py.yaw.d_max) == (45, 80, 0, 120, 0)
    assert py.roll.p == 90


def test_mode_off_is_identity(harness):
    binary, build = harness
    s = _sliders(pids_mode=PID_SIMPLIFIED_TUNING_OFF, master_multiplier=200)
    (cline,) = build.run_batch([_pid_line(s)], binary)
    py = apply_simplified_tuning_pids(_with_sliders(firmware_default_pid_profile(), s))
    assert _py_pid_tuple(py) == _parse_pid(cline) == (45, 80, 30, 120, 40, 47, 84, 34, 125, 46, 45, 80, 0, 120, 0)


def test_yaw_d_and_dmax_stay_zero(harness):
    binary, build = harness
    s = _sliders(d_gain=200, master_multiplier=200)
    (cline,) = build.run_batch([_pid_line(s)], binary)
    py = apply_simplified_tuning_pids(_with_sliders(firmware_default_pid_profile(), s))
    assert _py_pid_tuple(py) == _parse_pid(cline)
    assert py.yaw.d == 0 and py.yaw.d_max == 0


def test_pid_gain_clamp_250(harness):
    binary, build = harness
    s = _sliders(master_multiplier=200, pi_gain=200, pitch_pi_gain=200)
    (cline,) = build.run_batch([_pid_line(s)], binary)
    py = apply_simplified_tuning_pids(_with_sliders(firmware_default_pid_profile(), s))
    assert _py_pid_tuple(py) == _parse_pid(cline)
    assert py.pitch.p == 250  # 47*2*2*2 = 376 → 250
    assert py.roll.p == 180  # 45*2*2 = 180, unclamped


def test_truncation_toward_zero(harness):
    """45 * 111/100 = 49.95 → 49 (C float→int, not round)."""
    binary, build = harness
    s = _sliders(master_multiplier=111)
    (cline,) = build.run_batch([_pid_line(s)], binary)
    py = apply_simplified_tuning_pids(_with_sliders(firmware_default_pid_profile(), s))
    assert py.roll.p == 49
    assert _py_pid_tuple(py) == _parse_pid(cline)


def _filter_matrix():
    multipliers = (10, 25, 50, 75, 99, 100, 111, 150, 200, 250)
    currents = [
        (75, 150, 75, 150),
        (0, 0, 0, 0),
        (75, 150, 0, 150),
        (0, 0, 75, 0),
        (75, 150, 75, 0),
    ]
    ons = (0, 1)
    return list(itertools.product(ons, multipliers, currents))


def test_dterm_filter_mapping_matches_c(harness):
    binary, build = harness
    matrix = _filter_matrix()
    lines = [f"DTERM {on} {m} {a} {b} {c} {d}" for on, m, (a, b, c, d) in matrix]
    out = build.run_batch(lines, binary)
    assert len(out) == len(matrix)
    from dataclasses import replace

    for (on, m, cur), cline in zip(matrix, out, strict=True):
        profile = replace(
            firmware_default_pid_profile(),
            dterm=FilterSet(*cur),
            sliders=SimplifiedSliders(dterm_filter=on, dterm_filter_multiplier=m),
        )
        py = apply_simplified_tuning_dterm_filters(profile).dterm
        got = tuple(int(x) for x in cline.split())
        assert (py.lpf1_dyn_min_hz, py.lpf1_dyn_max_hz, py.lpf1_static_hz, py.lpf2_static_hz) == got, (on, m, cur)


def test_gyro_filter_mapping_matches_c(harness):
    binary, build = harness
    gyro_currents = [
        (250, 500, 250, 500),
        (0, 0, 0, 0),
        (250, 500, 0, 500),
        (0, 0, 250, 0),
    ]
    matrix = list(itertools.product((0, 1), (10, 50, 100, 200, 250), gyro_currents))
    lines = [f"GYRO {on} {m} {a} {b} {c} {d}" for on, m, (a, b, c, d) in matrix]
    out = build.run_batch(lines, binary)
    from dataclasses import replace

    for (on, m, cur), cline in zip(matrix, out, strict=True):
        gyro = replace(
            firmware_default_gyro(),
            filters=FilterSet(*cur),
            sliders=SimplifiedSliders(gyro_filter=on, gyro_filter_multiplier=m),
        )
        py = apply_simplified_tuning_gyro_filters(gyro).filters
        got = tuple(int(x) for x in cline.split())
        assert (py.lpf1_dyn_min_hz, py.lpf1_dyn_max_hz, py.lpf1_static_hz, py.lpf2_static_hz) == got


def test_validate_pids_consistent_and_inconsistent(harness):
    binary, build = harness
    s = _sliders()
    applied = apply_simplified_tuning_pids(_with_sliders(firmware_default_pid_profile(), s))
    consistent = (
        f"VALIDATE_PIDS 2 100 100 100 100 100 100 100 100 "
        f"{applied.roll.p} {applied.roll.i} {applied.roll.d} {applied.roll.f} {applied.roll.d_max} "
        f"{applied.pitch.p} {applied.pitch.i} {applied.pitch.d} {applied.pitch.f} {applied.pitch.d_max} "
        f"{applied.yaw.p} {applied.yaw.i} {applied.yaw.d} {applied.yaw.f} {applied.yaw.d_max}"
    )
    inconsistent = consistent.replace(f"{applied.roll.p} {applied.roll.i}", f"{applied.roll.p + 1} {applied.roll.i}", 1)
    out = build.run_batch([consistent, inconsistent], binary)
    assert out == ["1", "0"]
    good = validate_simplified_tuning(applied, firmware_default_gyro())
    assert good.pids_valid and good.dterm_valid and good.gyro_valid
    from dataclasses import replace

    bad = replace(applied, roll=replace(applied.roll, p=applied.roll.p + 1))
    ev = validate_simplified_tuning(bad, firmware_default_gyro())
    assert ev.pids_valid is False
    assert any(m.field == "roll.p" for m in ev.pid_mismatches)


def test_validate_filters_match_c(harness):
    binary, build = harness
    lines = [
        "VALIDATE_DTERM 1 100 75 150 75 150",
        "VALIDATE_DTERM 1 50 75 150 75 150",
        "VALIDATE_DTERM 1 50 37 75 37 75",
        "VALIDATE_DTERM 0 50 75 150 75 150",
        "VALIDATE_GYRO 1 100 250 500 250 500",
        "VALIDATE_GYRO 1 50 250 500 250 500",
        "VALIDATE_GYRO 1 50 125 250 125 250",
    ]
    out = build.run_batch(lines, binary)
    assert out == ["1", "0", "1", "1", "1", "0", "1"]
    from dataclasses import replace

    dterm_ok = replace(
        firmware_default_pid_profile(),
        dterm=FilterSet(75, 150, 75, 150),
        sliders=SimplifiedSliders(dterm_filter=1, dterm_filter_multiplier=100),
    )
    dterm_bad = replace(dterm_ok, sliders=SimplifiedSliders(dterm_filter=1, dterm_filter_multiplier=50))
    gyro_ok = replace(
        firmware_default_gyro(),
        filters=FilterSet(250, 500, 250, 500),
        sliders=SimplifiedSliders(gyro_filter=1, gyro_filter_multiplier=100),
    )
    assert validate_simplified_tuning(dterm_ok, gyro_ok).dterm_valid
    assert not validate_simplified_tuning(dterm_bad, gyro_ok).dterm_valid


def test_vendored_simplified_tuning_c_hash_stable():
    data = (FIRMWARE / "src/main/config/simplified_tuning.c").read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert len(digest) == 64
    assert b"calculateNewPidValues" in data
