"""Generate deterministic CHIRP parity fixtures (WU7).

Writes, under ``tests/fixtures/chirp/wu7/``:

- ``bbl/<case>.bbl.gz``  synthetic Blackbox logs (see ``bbl_writer``)
- ``cases.json``         case manifest (parameters, parity classification)
- ``math_inputs.json``   small numeric inputs for FFT / Welch / spectrogram vectors

Expected values are NOT produced here: ``reference_harness.mjs`` runs the
vendored Betaflight TypeScript over these inputs and writes the upstream
reference JSON. Re-run both after changing a case::

    python tools/chirp_reference/make_cases.py
    node --experimental-strip-types tools/chirp_reference/reference_harness.mjs
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bbl_writer import BblLog, chirp_main_fields  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "tests" / "fixtures" / "chirp" / "wu7"

BOXCHIRP_FLAG = 1 << 6
I_INTERVAL = 32
CHIRP_DEBUG_MODE_API_1_49 = 96

EXACT = "exact_upstream_parity"
MATH = "mathematical_equivalence"
HARDENING = "intentional_gyrocore_hardening"


@dataclass
class AxisChirp:
    axis: int
    gain: float = 1.0
    delay_samples: int = 0
    amplitude: float = 200.0
    noise_std: float = 0.0
    samples: int = 2000
    drop_bursts: list[tuple[int, int]] = field(default_factory=list)
    corrupt_axis_at: list[int] = field(default_factory=list)


@dataclass
class Case:
    case_id: str
    description: str
    classification: list[str]
    axes: list[AxisChirp]
    looptime: int = 250
    pid_process_denom: int = 4
    p_interval: str = "1/1"
    omit_headers: tuple[str, ...] = ()
    debug_mode: int = CHIRP_DEBUG_MODE_API_1_49
    high_resolution: int = 0
    include_debug3: bool = True
    chirp_start_deci_hz: int = 20
    chirp_end_deci_hz: int = 2000
    pre_idle: int = 200
    post_idle: int = 100
    inter_axis_idle: int = 50
    chirp_off_at_end: bool = True
    seed: int = 1
    expect: dict = field(default_factory=dict)


def _should_have_frame(i: int, pnum: int, pden: int) -> bool:
    # blackbox-tools parser.c shouldHaveFrame
    return (i % I_INTERVAL + pnum - 1) % pden < pnum


def _p_interval_parts(text: str | None) -> tuple[int, int]:
    if not text:
        return 1, 1
    if "/" in text:
        a, b = text.split("/", 1)
        return int(a), int(b)
    return 1, int(text)


def _headers(case: Case) -> list[tuple[str, str]]:
    h: list[tuple[str, str]] = [
        ("Data version", "2"),
        ("I interval", str(I_INTERVAL)),
    ]
    h.append(("P interval", case.p_interval))
    h += [
        ("Firmware type", "Cleanflight"),
        ("Firmware revision", "Betaflight 2026.6.0 (synthetic) STM32F7X2"),
        ("Board information", "SYNT SYNTHETIC"),
    ]
    h.append(("looptime", str(case.looptime)))
    h.append(("pid_process_denom", str(case.pid_process_denom)))
    h += [
        ("debug_mode", str(case.debug_mode)),
        ("blackbox_high_resolution", str(case.high_resolution)),
        ("chirp_lag_freq_hz", "3"),
        ("chirp_lead_freq_hz", "30"),
        ("chirp_amplitude_roll", "200"),
        ("chirp_amplitude_pitch", "200"),
        ("chirp_amplitude_yaw", "200"),
        ("chirp_frequency_start_deci_hz", str(case.chirp_start_deci_hz)),
        ("chirp_frequency_end_deci_hz", str(case.chirp_end_deci_hz)),
        ("chirp_time_seconds", "2"),
        ("rollPID", "45,80,30"),
        ("pitchPID", "47,84,34"),
        ("yawPID", "45,80,0"),
    ]
    return [(k, v) for k, v in h if k not in case.omit_headers]


def _chirp_wave(n: int, fs: float, f0: float, f1: float) -> np.ndarray:
    # Exponential sweep (Betaflight chirp.c style): f(t) = f0 * k^t, k = (f1/f0)^(1/T)
    T = n / fs
    t = np.arange(n, dtype=np.float64) / fs
    k = (f1 / f0) ** (1.0 / T)
    phase = 2.0 * math.pi * f0 * (np.power(k, t) - 1.0) / math.log(k)
    return np.sin(phase)


def build_case(case: Case) -> tuple[bytes, dict]:
    rng = np.random.default_rng(case.seed)
    pnum, pden = _p_interval_parts(case.p_interval)
    pid_period_us = case.looptime * case.pid_process_denom
    gen_pnum, gen_pden = pnum, pden
    nominal_log_rate = 1e6 * gen_pnum / (pid_period_us * gen_pden)
    scale = 10 if case.high_resolution else 1

    log = BblLog(_headers(case), chirp_main_fields(include_debug3=case.include_debug3))

    iteration = 0
    t0 = 10_000_000

    def next_iteration() -> int:
        nonlocal iteration
        while not _should_have_frame(iteration, gen_pnum, gen_pden):
            iteration += 1
        it = iteration
        iteration += 1
        return it

    def emit(setpoint: float, gyro: float, axis_slot: int, debug_axis: int, *, drop: bool = False) -> None:
        it = next_iteration()
        if drop:
            return
        sp = [0, 0, 0]
        gy = [int(round(rng.normal(0.0, 0.5) * scale)) for _ in range(3)]
        if axis_slot >= 0:
            sp[axis_slot] = int(round(setpoint * scale))
            gy[axis_slot] = int(round(gyro * scale))
        dbg = [int(round(setpoint)), debug_axis, 0, 0]
        values = [it, t0 + it * pid_period_us, *sp, 1300, *gy]
        values += dbg if case.include_debug3 else dbg[:3]
        values += [1200, 1200, 1200, 1200]
        log.add_i_frame(values)

    log.add_s_frame(0)
    for _ in range(case.pre_idle):
        emit(0.0, 0.0, -1, -1)

    log.add_s_frame(BOXCHIRP_FLAG)
    axis_meta = []
    for idx, ax in enumerate(case.axes):
        if idx > 0:
            for _ in range(case.inter_axis_idle):
                emit(0.0, 0.0, -1, -1)
        f0 = case.chirp_start_deci_hz / 10.0
        f1 = case.chirp_end_deci_hz / 10.0
        sp_wave = ax.amplitude * _chirp_wave(ax.samples, nominal_log_rate, f0, f1)
        delayed = np.zeros_like(sp_wave)
        if ax.delay_samples > 0:
            delayed[ax.delay_samples:] = sp_wave[: -ax.delay_samples]
        else:
            delayed[:] = sp_wave
        gyro_wave = ax.gain * delayed + rng.normal(0.0, ax.noise_std, size=ax.samples) if ax.noise_std else ax.gain * delayed
        drop_mask = np.zeros(ax.samples, dtype=bool)
        for start, length in ax.drop_bursts:
            drop_mask[start : start + length] = True
        corrupt = set(ax.corrupt_axis_at)
        for j in range(ax.samples):
            debug_axis = 7 if j in corrupt else ax.axis
            emit(float(sp_wave[j]), float(gyro_wave[j]), ax.axis, debug_axis, drop=bool(drop_mask[j]))
        axis_meta.append(
            {
                "axis": ax.axis,
                "gain": ax.gain,
                "delay_samples": ax.delay_samples,
                "amplitude": ax.amplitude,
                "noise_std": ax.noise_std,
                "samples_generated": ax.samples,
                "samples_dropped": int(drop_mask.sum()),
                "corrupt_axis_frames": len(corrupt),
            }
        )

    if case.chirp_off_at_end:
        for _ in range(5):
            emit(0.0, 0.0, -1, -1)
        log.add_s_frame(0)
        for _ in range(case.post_idle):
            emit(0.0, 0.0, -1, -1)
    log.add_log_end()

    data = log.to_bytes()
    meta = {
        "case_id": case.case_id,
        "description": case.description,
        "classification": case.classification,
        "bbl": f"bbl/{case.case_id}.bbl.gz",
        "bbl_sha256": hashlib.sha256(data).hexdigest(),
        "seed": case.seed,
        "headers": dict(_headers(case)),
        "nominal_log_rate_hz": nominal_log_rate,
        "axes": axis_meta,
        "expect": case.expect,
    }
    return data, meta


def _cases() -> list[Case]:
    roll = lambda **kw: AxisChirp(axis=0, **kw)  # noqa: E731
    return [
        Case(
            "clean_single_axis",
            "Roll chirp, unity plant, no noise, 1 kHz log (PID 1 kHz, P 1/1).",
            [EXACT],
            [roll()],
            expect={"usable": True, "status": "ok"},
        ),
        Case(
            "known_gain",
            "Roll chirp, plant gain 0.5 (|H| = -6.02 dB), no delay.",
            [EXACT, MATH],
            [roll(gain=0.5)],
            expect={"usable": True, "gain": 0.5, "delay_samples": 0},
        ),
        Case(
            "known_phase_delay",
            "Roll chirp at 2 kHz log, unity gain, 4-sample pure delay (phase = -360 f d / fs).",
            [EXACT, MATH],
            [roll(delay_samples=4, samples=4000)],
            looptime=125,
            pid_process_denom=4,
            p_interval="1/1",
            expect={"usable": True, "gain": 1.0, "delay_samples": 4},
        ),
        Case(
            "low_noise",
            "Roll chirp, gain 0.8, 1-sample delay, gyro noise sigma 1 deg/s.",
            [EXACT],
            [roll(gain=0.8, delay_samples=1, noise_std=1.0)],
            seed=11,
            expect={"usable": True},
        ),
        Case(
            "noisy",
            "Roll chirp, gain 0.8, 1-sample delay, gyro noise sigma 40 deg/s.",
            [EXACT],
            [roll(gain=0.8, delay_samples=1, noise_std=40.0)],
            seed=12,
            expect={"usable": True},
        ),
        Case(
            "weak_excitation",
            "Roll chirp with 2 deg/s amplitude: too little excitation to identify.",
            [EXACT, HARDENING],
            [roll(amplitude=2.0, noise_std=1.0)],
            seed=13,
            expect={"usable": False, "gates": ["insufficient_excitation"]},
        ),
        Case(
            "poor_coherence",
            "Roll chirp, plant gain 0.05 buried in sigma 60 noise: coherence collapses.",
            [EXACT, HARDENING],
            [roll(gain=0.05, noise_std=60.0)],
            seed=14,
            expect={"usable": False, "gates": ["low_coherence"]},
        ),
        Case(
            "dropped_timestamps",
            "Clean roll chirp with 6 bursts of 15 dropped frames (iteration/time gaps).",
            [EXACT, HARDENING],
            [roll(drop_bursts=[(150, 15), (450, 15), (800, 15), (1100, 15), (1400, 15), (1700, 15)])],
            expect={"usable": False, "gates": ["excessive_gaps"]},
        ),
        Case(
            "log_rate_below_pid",
            "PID 4 kHz (looptime 125, pid_process_denom 2) logged at P interval 1/4 = 1 kHz.",
            [EXACT],
            [roll(gain=0.9, delay_samples=1)],
            looptime=125,
            pid_process_denom=2,
            p_interval="1/4",
            expect={"usable": True, "effective_rate_hz": 1000.0},
        ),
        Case(
            "pnum_pdenom",
            "Legacy P interval 2/3 at PID 2 kHz: GyroCore rate 1333.3 Hz, upstream 666.7 Hz, non-uniform spacing.",
            [HARDENING],
            [roll(samples=2000)],
            looptime=125,
            pid_process_denom=4,
            p_interval="2/3",
            expect={"usable": False, "gates": ["non_uniform_sampling"]},
        ),
        Case(
            "chirp_at_log_end",
            "Chirp still active when the log ends (no chirp-off S-frame, segment closed at end of data).",
            [EXACT],
            [roll(gain=0.9)],
            chirp_off_at_end=False,
            expect={"usable": True},
        ),
        Case(
            "chirp_near_nyquist",
            "Chirp sweeps to 490 Hz on a 1 kHz log (close to Nyquist).",
            [EXACT, HARDENING],
            [roll(gain=0.9)],
            chirp_end_deci_hz=4900,
            expect={"usable": True},
        ),
        Case(
            "insufficient_samples",
            "Chirp segment of 300 samples, shorter than the 512-sample Welch segment.",
            [EXACT, HARDENING],
            [roll(samples=300)],
            expect={"usable": False, "gates": ["insufficient_samples"]},
        ),
        Case(
            "malformed_missing_rate_headers",
            "looptime / pid_process_denom / P interval headers missing (upstream silently assumes 8 kHz).",
            [HARDENING],
            [roll()],
            omit_headers=("looptime", "pid_process_denom", "P interval"),
            expect={"usable": True, "rate_source": "timestamp"},
        ),
        Case(
            "malformed_wrong_debug_mode",
            "debug_mode 6 (not CHIRP): upstream rejects the log.",
            [EXACT],
            [roll()],
            debug_mode=6,
            expect={"error": "not_chirp_debug_mode"},
        ),
        Case(
            "malformed_missing_debug_field",
            "Log without debug[3]: upstream rejects missing required field.",
            [EXACT],
            [roll()],
            include_debug3=False,
            expect={"error": "missing_required_field"},
        ),
        Case(
            "three_axis_sequence",
            "Roll, pitch, yaw chirps in sequence with different gains / delays.",
            [EXACT],
            [
                AxisChirp(axis=0, gain=1.0, delay_samples=1, noise_std=0.5),
                AxisChirp(axis=1, gain=0.9, delay_samples=2, noise_std=0.5),
                AxisChirp(axis=2, gain=0.7, delay_samples=3, noise_std=0.5),
            ],
            seed=21,
            expect={"usable": True, "axes": [0, 1, 2]},
        ),
        Case(
            "repeated_axis",
            "Roll chirped twice (gain 0.5 then 1.0): upstream keeps the last segment per axis.",
            [EXACT],
            [roll(gain=0.5), roll(gain=1.0)],
            expect={"usable": True, "selected_gain": 1.0},
        ),
        Case(
            "high_resolution",
            "blackbox_high_resolution = 1: setpoint/gyro stored x10, scaled by 0.1.",
            [EXACT],
            [roll(gain=0.8, delay_samples=1, noise_std=0.5)],
            high_resolution=1,
            seed=31,
            expect={"usable": True},
        ),
        Case(
            "corrupt_axis_frames",
            "Five frames with debug[1] = 7 inside the roll segment: dropped as decode artefacts.",
            [EXACT],
            [roll(corrupt_axis_at=[300, 301, 900, 1500, 1501])],
            expect={"usable": True},
        ),
    ]


def _math_inputs() -> dict:
    rng = np.random.default_rng(20261006)

    def r(n: int, s: float = 1.0) -> list[float]:
        return [round(float(v), 6) for v in rng.normal(0.0, s, size=n)]

    fft = []
    for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 15, 16, 30, 64, 100, 128):
        fft.append({"n": n, "inverse": False, "kind": "real", "input": r(n)})
        fft.append({"n": n, "inverse": False, "kind": "complex", "input": r(2 * n)})
        fft.append({"n": n, "inverse": True, "kind": "complex", "input": r(2 * n)})
    for n in (256, 512, 1000):
        fft.append({"n": n, "inverse": False, "kind": "real", "input": r(n, 300.0)})

    def tone_pair(n: int, fs: float, gain: float, delay: int, noise: float) -> tuple[list[float], list[float]]:
        t = np.arange(n) / fs
        x = np.zeros(n)
        for f in (7.0, 23.0, 61.0, 133.0):
            x += np.sin(2 * math.pi * f * t + f)
        x += rng.normal(0.0, 0.3, size=n)
        y = np.zeros(n)
        y[delay:] = gain * x[: n - delay] if delay else gain * x
        y += rng.normal(0.0, noise, size=n)
        return [round(float(v), 6) for v in x], [round(float(v), 6) for v in y]

    welch = []
    for name, n, fs, seg, ov, gain, delay, noise in (
        ("pow2_half_overlap", 1500, 1000.0, 256, 0.5, 0.7, 2, 0.05),
        ("non_pow2_segment", 1200, 1000.0, 300, 0.5, 1.0, 1, 0.1),
        ("no_overlap", 1024, 500.0, 128, 0.0, 1.3, 0, 0.0),
        ("three_quarter_overlap", 900, 2000.0, 128, 0.75, 0.5, 3, 0.2),
        ("segment_clamped_to_n", 200, 1000.0, 1024, 0.5, 0.9, 1, 0.05),
        ("odd_remainder", 1037, 1000.0, 256, 0.5, 0.9, 1, 0.05),
    ):
        x, y = tone_pair(n, fs, gain, delay, noise)
        welch.append(
            {"name": name, "input": x, "output": y, "sample_rate": fs, "segment_size": seg, "overlap": ov}
        )
    zeros = [0.0] * 300
    welch.append(
        {"name": "zero_input", "input": zeros, "output": r(300), "sample_rate": 1000.0, "segment_size": 128, "overlap": 0.5}
    )

    spectrogram = [
        {"name": "default_window", "signal": r(1200, 50.0), "sample_rate": 1000.0, "window_size": 256, "overlap": 0.75},
        {"name": "short_signal", "signal": r(180, 5.0), "sample_rate": 1000.0, "window_size": 256, "overlap": 0.75},
        {"name": "zeros", "signal": [0.0] * 300, "sample_rate": 1000.0, "window_size": 64, "overlap": 0.5},
    ]
    sample_rate = [
        {"looptime": 125, "pid_process_denom": 1, "frameIntervalPDenom": 1},
        {"looptime": 125, "pid_process_denom": 2, "frameIntervalPDenom": 4},
        {"looptime": 250, "pid_process_denom": 4, "frameIntervalPDenom": 1},
        {"looptime": 125, "pid_process_denom": 4, "frameIntervalPDenom": 3},
        {"looptime": 0, "pid_process_denom": 0, "frameIntervalPDenom": 0},
        {"looptime": 312, "pid_process_denom": 1, "frameIntervalPDenom": 2},
    ]
    segment_rates = [100.0, 500.0, 511.0, 512.0, 1000.0, 1333.3333333333333, 2000.0, 4000.0, 8000.0, 32000.0]
    return {
        "fft": fft,
        "hanning_sizes": [2, 3, 4, 5, 8, 16, 100, 256, 300, 1024],
        "welch": welch,
        "spectrogram": spectrogram,
        "sample_rate_sysconfigs": sample_rate,
        "segment_size_rates": segment_rates,
        "debug_mode_api_versions": [None, "", "0.0.0", "1.44.0", "1.46.0", "1.47.0", "1.47.5", "1.48.0", "1.49.0", "1.50.0", "2.0.0", "garbage"],
    }


def main() -> None:
    (OUT_DIR / "bbl").mkdir(parents=True, exist_ok=True)
    manifest = []
    for case in _cases():
        data, meta = build_case(case)
        with gzip.GzipFile(OUT_DIR / meta["bbl"], "wb", mtime=0) as fh:
            fh.write(data)
        manifest.append(meta)
    (OUT_DIR / "cases.json").write_text(json.dumps({"cases": manifest}, indent=1) + "\n")
    (OUT_DIR / "math_inputs.json").write_text(json.dumps(_math_inputs()) + "\n")
    print(f"wrote {len(manifest)} cases to {OUT_DIR}")


if __name__ == "__main__":
    main()
