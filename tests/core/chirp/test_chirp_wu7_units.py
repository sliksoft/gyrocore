"""WU7 unit tests: header parsing, flag decoding, spacing, extraction state machine, gates."""

from __future__ import annotations

import numpy as np
import pytest

from gyrocore.chirp import (
    ChirpFrames,
    ChirpFramesError,
    analyze_timestamp_spacing,
    chirp_frames_from_parsed_samples,
    extract_chirp,
    identify_chirp_system,
    parse_chirp_sysconfig,
    read_bbl_header_text,
    read_chirp_frames_from_csv,
)
from gyrocore.chirp.frames import decode_flight_mode_flags
from gyrocore.chirp.sysconfig import find_log_boundaries, js_parse_int
from gyrocore.parse.blackbox_csv import parse_blackbox_csv

CHIRP = 1 << 6


def h_text(**overrides) -> str:
    base = {
        "Data version": "2",
        "I interval": "32",
        "P interval": "1/1",
        "looptime": "250",
        "pid_process_denom": "4",
        "debug_mode": "96",
        "blackbox_high_resolution": "0",
        "chirp_frequency_start_deci_hz": "20",
        "chirp_frequency_end_deci_hz": "2000",
    }
    base.update(overrides)
    lines = ["H Product:Blackbox flight data recorder by Nicholas Sherlock"]
    lines += [f"H {k}:{v}" for k, v in base.items() if v is not None]
    return "\n".join(lines)


# --- sysconfig ---------------------------------------------------------------


def test_js_parse_int_semantics():
    assert js_parse_int(" 250") == 250
    assert js_parse_int("250abc") == 250
    assert js_parse_int("abc") is None
    assert js_parse_int("-1") == -1
    assert js_parse_int("1/2") == 1


@pytest.mark.parametrize(
    "value,num,den",
    [("1/4", 1, 4), ("2", 1, 2), ("2/3", 2, 3), ("1/1", 1, 1)],
)
def test_p_interval_forms(value, num, den):
    sc = parse_chirp_sysconfig(h_text(**{"P interval": value}))
    assert (sc.p_interval_num, sc.p_interval_denom) == (num, den)
    assert sc.p_interval_seen


def test_p_ratio_only_when_p_interval_absent():
    sc = parse_chirp_sysconfig(h_text(**{"P interval": None, "P ratio": "8"}))
    assert (sc.p_interval_num, sc.p_interval_denom) == (1, 8)
    text = h_text(**{"P interval": "1/2"}) + "\nH P ratio:8"
    sc = parse_chirp_sysconfig(text)
    assert sc.p_interval_denom == 2


def test_missing_headers_stay_none_but_upstream_defaults_available():
    sc = parse_chirp_sysconfig(h_text(looptime=None, pid_process_denom=None, **{"P interval": None}))
    assert sc.looptime is None and sc.pid_process_denom is None and not sc.p_interval_seen
    assert sc.upstream_value("looptime") == 125
    assert sc.upstream_value("pid_process_denom") == 1
    assert sc.sample_rate_inputs() == {
        "looptime_us": None,
        "pid_process_denom": None,
        "frame_interval_p_num": None,
        "frame_interval_p_denom": None,
    }


def test_sysconfig_from_field_value_csv_and_mapping():
    csv_text = 'fieldname, fieldvalue\nlooptime,"125"\npid_process_denom,"2"\nP interval,"1/4"\ndebug_mode,"96"\n'
    sc = parse_chirp_sysconfig(csv_text)
    assert (sc.looptime, sc.pid_process_denom, sc.p_interval_num, sc.p_interval_denom, sc.debug_mode) == (125, 2, 1, 4, 96)
    sc2 = parse_chirp_sysconfig({"looptime": 125, "pid_process_denom": 2, "frameIntervalPNum": 1, "frameIntervalPDenom": 4})
    assert (sc2.p_interval_num, sc2.p_interval_denom) == (1, 4)


def test_high_resolution_scale():
    assert parse_chirp_sysconfig(h_text(blackbox_high_resolution="1")).high_resolution_scale == 0.1
    assert parse_chirp_sysconfig(h_text()).high_resolution_scale == 1.0


def test_bbl_header_and_boundaries():
    log = (h_text() + "\n").encode() + b"I\x00\x01"
    data = log + (h_text(looptime="125") + "\n").encode() + b"I\x02"
    assert len(find_log_boundaries(data)) == 2
    assert "looptime:125" in read_bbl_header_text(data, 1)
    assert parse_chirp_sysconfig(data, log_index=1).looptime == 125
    with pytest.raises(ValueError):
        read_bbl_header_text(data, 2)


# --- frames ------------------------------------------------------------------


def test_flight_mode_flag_decoding():
    assert decode_flight_mode_flags("HEADFREE") == CHIRP
    assert decode_flight_mode_flags("ANGLE_MODE|HEADFREE") == CHIRP | 1
    assert decode_flight_mode_flags("0") == 0
    assert decode_flight_mode_flags("64") == CHIRP
    unknown: set[str] = set()
    assert decode_flight_mode_flags("FOO|HEADFREE", unknown) == CHIRP and unknown == {"FOO"}


HEADER = (
    "loopIteration, time (us), setpoint[0], setpoint[1], setpoint[2], gyroADC[0], gyroADC[1], gyroADC[2], "
    "gyroUnfilt[0], gyroUnfilt[1], gyroUnfilt[2], debug[0], debug[1], debug[2], debug[3], flightModeFlags (flags)"
)


def csv_rows(rows) -> str:
    lines = [HEADER]
    for i, (sp, gy, axis, flags) in enumerate(rows):
        lines.append(f"{i}, {1000 + 1000 * i}, {sp}, 0, 0, {gy}, 0, 0, 999, 999, 999, 0, {axis}, 0, 0, {flags}")
    return "\n".join(lines) + "\n"


def test_frames_use_gyroadc_not_unfiltered_gyro():
    frames = read_chirp_frames_from_csv(csv_rows([(10, 7, 0, "HEADFREE")] * 4))
    assert frames.gyro_columns == ("gyroADC[0]", "gyroADC[1]", "gyroADC[2]")
    assert frames.gyro_adc[0, 0] == 7.0
    assert frames.flight_mode_flags.tolist() == [CHIRP] * 4


def test_frames_missing_field():
    text = csv_rows([(1, 1, 0, "0")]).replace("debug[3], ", "").replace(", 0, 0, 0\n", ", 0, 0\n")
    with pytest.raises(ChirpFramesError) as exc:
        read_chirp_frames_from_csv(text)
    assert exc.value.code == "missing_required_field"


def test_parsed_samples_adapter_refuses_subsampled_and_warns():
    parsed = parse_blackbox_csv(csv_rows([(i, i, 0, "HEADFREE") for i in range(10)]))
    frames = chirp_frames_from_parsed_samples(parsed)
    assert "gyro_column_not_gyroadc" in frames.warnings  # general parser picked gyroUnfilt[]
    assert frames.flight_mode_flags is None
    with pytest.raises(ChirpFramesError) as exc:
        chirp_frames_from_parsed_samples({**parsed, "original_sample_count": 50000})
    assert exc.value.code == "subsampled_input"


# --- extraction state machine (mirrors chirp_bbl_parser.ts) ------------------


def make_frames(axis, flags, *, sp=None):
    n = len(axis)
    sp = np.arange(n, dtype=float) if sp is None else np.asarray(sp, dtype=float)
    z = np.zeros(n)
    return ChirpFrames(
        loop_iteration=np.arange(n, dtype=float),
        time_us=np.arange(n, dtype=float) * 1000.0,
        setpoint=np.vstack([sp, z, z]),
        gyro_adc=np.vstack([sp, z, z]),
        debug=np.vstack([z, np.asarray(axis, dtype=float), z, z]),
        flight_mode_flags=None if flags is None else np.asarray(flags, dtype=np.int64),
        source="test",
        gyro_columns=("gyroADC[0]", "gyroADC[1]", "gyroADC[2]"),
    )


SC = parse_chirp_sysconfig(h_text())


def test_segments_follow_axis_changes_and_flag_edges():
    axis = [-1, 0, 0, 0, -1, 1, 1, 2, 2, 0, 0]
    flags = [0, CHIRP, CHIRP, CHIRP, CHIRP, CHIRP, CHIRP, CHIRP, CHIRP, CHIRP, 0]
    ex = extract_chirp(make_frames(axis, flags), SC)
    # row 0 inactive; rows 1..9 collected; row 10 chirp-off closes the last segment
    assert ex.sample_count == 9
    assert [(s.axis, s.start_idx, s.end_idx) for s in ex.segments] == [(0, 0, 2), (1, 4, 5), (2, 6, 7), (0, 8, 8)]
    assert ex.selected_by_axis == {0: 3, 1: 1, 2: 2}
    assert "repeated_axis_segments_last_selected" in ex.warnings


def test_out_of_range_axis_frames_are_dropped():
    axis = [0, 0, 5, 0, -3, 0]
    ex = extract_chirp(make_frames(axis, [CHIRP] * 6), SC)
    assert ex.dropped_axis_frames == 2
    assert ex.sample_count == 4
    assert [(s.axis, s.start_idx, s.end_idx) for s in ex.segments] == [(0, 0, 3)]
    assert ex.frame_rows.tolist() == [0, 1, 3, 5]


def test_chirp_reactivation_starts_new_segment_even_on_same_axis():
    axis = [0, 0, 0, 0, 0]
    flags = [CHIRP, CHIRP, 0, CHIRP, CHIRP]
    ex = extract_chirp(make_frames(axis, flags), SC)
    assert [(s.axis, s.start_idx, s.end_idx) for s in ex.segments] == [(0, 0, 1), (0, 2, 3)]


def test_debug_axis_only_mode_when_flags_missing():
    ex = extract_chirp(make_frames([-1, 0, 0, -1], None), SC)
    assert ex.flag_gating == "debug_axis_only"
    assert "chirp_mode_flag_unavailable_debug_axis_only" in ex.warnings
    assert [(s.axis, s.start_idx, s.end_idx) for s in ex.segments] == [(0, 1, 2)]
    strict = extract_chirp(make_frames([-1, 0, 0, -1], None), SC, require_flight_mode_flags=True)
    assert strict.errors == ("flight_mode_flags_unavailable",)


def test_high_resolution_float32_scaling():
    sc = parse_chirp_sysconfig(h_text(blackbox_high_resolution="1"))
    ex = extract_chirp(make_frames([0, 0], [CHIRP, CHIRP], sp=[1234, -7]), sc)
    assert ex.setpoint.dtype == np.float32
    assert ex.setpoint[0].tolist() == [np.float32(1234 * 0.1), np.float32(-7 * 0.1)]


@pytest.mark.parametrize("debug_mode,api,error", [("6", None, "not_chirp_debug_mode"), ("97", None, "not_chirp_debug_mode"), ("97", "1.47.0", None), ("96", "1.46.0", "chirp_debug_mode_unsupported_api")])
def test_debug_mode_validation(debug_mode, api, error):
    sc = parse_chirp_sysconfig(h_text(debug_mode=debug_mode))
    ex = extract_chirp(make_frames([0, 0], [CHIRP, CHIRP]), sc, api_version=api)
    assert (ex.errors[0] if ex.errors else None) == error


# --- spacing ------------------------------------------------------------------


def test_spacing_uniform_gaps_and_alternating():
    t = np.arange(1000) * 1000.0
    s = analyze_timestamp_spacing(t)
    assert s.uniform and s.gap_count == 0 and s.missing_fraction == 0.0
    gapped = np.delete(t, np.arange(100, 120))
    s = analyze_timestamp_spacing(gapped)
    assert s.gap_count == 1 and s.missing_samples_estimate == 20 and s.max_gap_samples == 20
    alt = np.cumsum(np.tile([500.0, 1000.0], 500))
    assert not analyze_timestamp_spacing(alt).uniform
    assert not analyze_timestamp_spacing([0.0, 1000.0, 1000.0, 2000.0]).uniform


# --- pipeline on CSV text (no decoder needed) ---------------------------------


def chirp_csv(n=2000, fs=1000.0, gain=0.8, amp=200.0):
    t = np.arange(n) / fs
    k = (200.0 / 2.0) ** (1.0 / (n / fs))
    x = amp * np.sin(2 * np.pi * 2.0 * (np.power(k, t) - 1.0) / np.log(k))
    rows = [(0, 0, -1, "0")] * 20
    rows += [(int(round(v)), int(round(gain * v)), 0, "HEADFREE") for v in x]
    rows += [(0, 0, -1, "0")] * 20
    return csv_rows(rows)


def test_identify_from_csv_text():
    result = identify_chirp_system(csv_text=chirp_csv(), headers=h_text())
    assert result.status == "ok", result.to_dict(include_arrays=False)
    roll = result.axis("roll")
    assert roll.effective_rate_hz == pytest.approx(1000.0)
    assert roll.segment_size == 512
    assert roll.quality.usable_range_hz is not None
    f = roll.transfer_function.frequencies
    band = roll.quality.usable_mask & (f > 5) & (f < 100)
    assert np.allclose(np.abs(roll.transfer_function.h[band]), 0.8, rtol=0.02)


def test_identify_requires_exactly_one_source():
    with pytest.raises(ValueError):
        identify_chirp_system(headers=h_text())


def test_no_chirp_segments_is_unusable():
    result = identify_chirp_system(csv_text=csv_rows([(0, 0, -1, "0")] * 50), headers=h_text())
    assert result.status == "unusable" and result.errors == ("no_chirp_segments",)


def test_invalid_rate_and_weak_excitation_gates():
    result = identify_chirp_system(csv_text=chirp_csv(amp=2.0), headers=h_text())
    assert "roll:insufficient_excitation" in result.errors

    frames = read_chirp_frames_from_csv(chirp_csv())
    frozen = ChirpFrames(**{**frames.__dict__, "time_us": np.zeros_like(frames.time_us)})
    no_rate = identify_chirp_system(
        frames=frozen,
        headers=h_text(looptime=None, pid_process_denom=None, **{"P interval": None}),
    )
    assert not no_rate.usable
    assert "roll:invalid_sample_rate" in no_rate.errors
    assert no_rate.axes[0].transfer_function is None
