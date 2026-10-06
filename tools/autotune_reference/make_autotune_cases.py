"""Generate deterministic Autotune recommendation fixtures (WU8).

Writes, under ``tests/fixtures/autotune/wu8/``:

- ``synthetic_cases.json``  parameters for upstream's own ``makeSyntheticTf``
  (``configurator/test/js/spectral_analysis.test.js``: integrator + delay
  open loop, optional second-order mode) plus slider sets and phase targets.
  The transfer functions themselves are built by the harness with the
  verbatim upstream function, so Python and TypeScript see identical bins.
- ``bbl/<case>.bbl.gz`` + ``bbl_cases.json``  closed-loop CHIRP logs: a
  discrete rate loop (PID on rate error, D on measurement through a PT1,
  PT1 motor lag, integrating airframe, sample delay) driven by an
  exponential sweep. The logged ``gyroADC`` is the fed-back measurement, so
  the setpoint->gyro response is a genuine closed loop and
  ``L = T / (1 - T)`` is well defined. P/I/D come from the ``rollPID`` /
  ``pitchPID`` / ``yawPID`` headers written into the same log.

Expected values are NOT produced here: ``autotune_harness.mjs`` runs the
vendored Betaflight TypeScript and writes ``upstream_autotune_reference.json.gz``::

    python tools/autotune_reference/make_autotune_cases.py
    node --experimental-strip-types tools/autotune_reference/autotune_harness.mjs
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

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "chirp_reference"))

from bbl_writer import BblLog, chirp_main_fields  # noqa: E402

OUT_DIR = ROOT / "tests" / "fixtures" / "autotune" / "wu8"

BOXCHIRP_FLAG = 1 << 6
I_INTERVAL = 32
CHIRP_DEBUG_MODE_API_1_49 = 96
PRESETS = [50.0, 60.0, 72.5]

EXACT = "exact_upstream_parity"
MATH = "mathematical_equivalence"
HARDENING = "intentional_gyrocore_hardening"

DEFAULT_SLIDERS = {
    "simplified_master_multiplier": "100",
    "simplified_pi_gain": "100",
    "simplified_i_gain": "100",
    "simplified_d_gain": "100",
    "simplified_feedforward_gain": "100",
    "simplified_dterm_filter_multiplier": "100",
}
UNIT_SLIDERS = {"masterMultiplier": 1, "piGain": 1, "iGain": 1, "dGain": 1, "feedforwardGain": 1, "dtermFilterMultiplier": 1}

# Plant / controller scaling for the closed-loop simulator (per Betaflight PID unit).
KP_PER_UNIT = 0.008
KI_PER_UNIT = 0.02
KD_PER_UNIT = 0.00005
PLANT_GAIN = {0: 1000.0, 1: 950.0, 2: 450.0}
MOTOR_TAU_S = 0.008
DTERM_LPF_HZ = 100.0


# ---------------------------------------------------------------------------
# Synthetic transfer-function cases (upstream makeSyntheticTf)
# ---------------------------------------------------------------------------


def _synthetic_cases() -> list[dict]:
    def case(case_id, description, tf, *, sliders=None, presets=None, overrides=(), classification=(EXACT,), covers=()):
        return {
            "case_id": case_id,
            "description": description,
            "classification": list(classification),
            "make_synthetic_tf": tf,
            "coherence_overrides": [list(o) for o in overrides],
            "sliders": sliders if sliders is not None else UNIT_SLIDERS,
            "presets": presets if presets is not None else PRESETS,
            "covers": list(covers),
        }

    unusual = {"masterMultiplier": 1.5, "piGain": 2.4, "iGain": 0.3, "dGain": 1.7, "feedforwardGain": 0.25, "dtermFilterMultiplier": 2.4}
    ties = {"masterMultiplier": 2.125, "piGain": 1, "iGain": 1.005, "dGain": 0.625, "feedforwardGain": 1, "dtermFilterMultiplier": 1}
    return [
        case("nominal", "20 Hz crossover, 3 ms delay (upstream test baseline).", {"crossoverHz": 20, "delayMs": 3},
             presets=PRESETS + [95.0], covers=["nominal", "target_unreachable_above_ceiling"]),
        case("delayed_plant", "20 Hz crossover, 8 ms delay.", {"crossoverHz": 20, "delayMs": 8}, covers=["delayed_plant"]),
        case("fast_plant", "20 Hz crossover, 2 ms delay.", {"crossoverHz": 20, "delayMs": 2}),
        case("low_plant_gain", "3 Hz crossover: asks for > 2x, per-pass clamp at 2.", {"crossoverHz": 3, "delayMs": 3},
             covers=["low_plant_gain", "gain_clamped_upper"]),
        case("high_plant_gain", "200 Hz crossover: asks for < 0.5x, per-pass clamp at 0.5.", {"crossoverHz": 200, "delayMs": 3},
             covers=["high_plant_gain", "gain_clamped_lower"]),
        case("phase_never_reaches_target", "0 ms delay, 40 Hz band: phase stays above target, gain held.",
             {"crossoverHz": 20, "delayMs": 0, "maxHz": 40}, covers=["target_unreachable_in_band"]),
        case("fragile_resonance", "70 Hz mode zeta 0.2: sensitivity bound binds.",
             {"crossoverHz": 20, "delayMs": 3, "resonanceHz": 70, "resonanceZeta": 0.2}, covers=["sensitivity_binds"]),
        case("nonmonotonic_sensitivity", "15 Hz crossover, 40 Hz mode zeta 0.05 (Ms not monotonic in gain).",
             {"crossoverHz": 15, "delayMs": 3, "resonanceHz": 40, "resonanceZeta": 0.05}, covers=["nonmonotonic_ms"]),
        case("sharp_resonance_120", "40 Hz crossover, 2 ms, 120 Hz mode zeta 0.05.",
             {"crossoverHz": 40, "delayMs": 2, "resonanceHz": 120, "resonanceZeta": 0.05}),
        case("resonant_peak_backoff", "8 Hz crossover with a 12 Hz zeta 0.08 mode: closed-loop peak > 6 dB.",
             {"crossoverHz": 8, "delayMs": 3, "resonanceHz": 12, "resonanceZeta": 0.08}, covers=["resonance_backoff"]),
        case("incoherent", "Coherence 0.2 everywhere: nothing inferred, every slider held.",
             {"crossoverHz": 20, "delayMs": 3, "coherence": 0.2}, covers=["low_coherence_hold"]),
        case("coherence_at_gate", "Coherence exactly 0.5 (gate is >= 0.5).", {"crossoverHz": 20, "delayMs": 3, "coherence": 0.5},
             covers=["near_quality_threshold"]),
        case("coherence_below_gate", "Coherence 0.4999 (just below the 0.5 gate).",
             {"crossoverHz": 20, "delayMs": 3, "coherence": 0.4999}, covers=["near_quality_threshold"]),
        case("coherent_to_60hz", "Coherent below 60 Hz, 0.1 above: real noise floor tightens D-term filter.",
             {"crossoverHz": 20, "delayMs": 3}, overrides=[(60.0000001, 1e9, 0.1)], covers=["noise_floor_filter"]),
        case("narrow_coherent_band", "Coherent only 2-12 Hz: insufficient usable frequency range.",
             {"crossoverHz": 20, "delayMs": 3}, overrides=[(0, 1.9, 0.1), (12.0000001, 1e9, 0.1)],
             covers=["insufficient_frequency_range"]),
        case("noisy_bin", "One bad bin at 12 Hz (coherence 0.05) kept out of the unwrap.",
             {"crossoverHz": 20, "delayMs": 3, "badBins": [[12, 0.05, 0.2, 0.3]]}, covers=["noisy_usable"]),
        case("coarse_bins", "1 Hz bins to 250 Hz (different resolution).", {"crossoverHz": 25, "delayMs": 4, "binHz": 1, "maxHz": 250}),
        case("unusual_sliders", "Unusual current sliders: slider clamps at 25 / 250.", {"crossoverHz": 3, "delayMs": 3},
             sliders=unusual, covers=["unusual_current_values", "slider_clamp_upper", "slider_clamp_lower"]),
        case("unusual_sliders_backoff", "Unusual sliders with a < 0.5x request.", {"crossoverHz": 200, "delayMs": 3},
             sliders=unusual, covers=["slider_clamp_lower"]),
        case("rounding_ties", "Sliders producing exact .5 products (Math.round half-up).", {"crossoverHz": 20, "delayMs": 3},
             sliders=ties, covers=["rounding_ties"]),
        case("sliders_undefined", "Empty CurrentSliders object: every `?? 1` default applies.", {"crossoverHz": 20, "delayMs": 3},
             sliders={}, covers=["missing_slider_defaults"]),
        case("sliders_zero", "Explicit 0 sliders (not reachable via extractCurrentSliders).", {"crossoverHz": 20, "delayMs": 3},
             sliders={"masterMultiplier": 0, "piGain": 0, "iGain": 0, "dGain": 0, "feedforwardGain": 0, "dtermFilterMultiplier": 0}),
        case("low_freq_error_high", "8 Hz mode (zeta 0.5) lifts the 2-10 Hz closed-loop magnitude above +2 dB, I backs off.",
             {"crossoverHz": 20, "delayMs": 2, "resonanceHz": 8, "resonanceZeta": 0.5}, covers=["integral_decrease"]),
    ]


# ---------------------------------------------------------------------------
# Closed-loop BBL cases
# ---------------------------------------------------------------------------


@dataclass
class AxisLoop:
    axis: int
    pid: tuple[float, float, float]
    plant_scale: float = 1.0
    delay_samples: int = 2
    noise_std: float = 0.5
    amplitude: float = 150.0
    seconds: float = 6.0


@dataclass
class BblCase:
    case_id: str
    description: str
    classification: list[str]
    axes: list[AxisLoop]
    looptime: int = 250
    pid_process_denom: int = 4
    p_interval: str = "1/1"
    sliders: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_SLIDERS))
    pids_mode: str | None = "2"
    dterm_filter: str | None = "1"
    header_pids: dict[int, tuple[int, int, int]] | None = None
    omit_headers: tuple[str, ...] = ()
    chirp_start_deci_hz: int = 20
    chirp_end_deci_hz: int = 2500
    freeze_time: bool = False
    seed: int = 1
    covers: list[str] = field(default_factory=list)
    expect: dict = field(default_factory=dict)


def _should_have_frame(i: int, pnum: int, pden: int) -> bool:
    return (i % I_INTERVAL + pnum - 1) % pden < pnum


def _p_interval_parts(text: str) -> tuple[int, int]:
    if "/" in text:
        a, b = text.split("/", 1)
        return int(a), int(b)
    return 1, int(text)


def _chirp_wave(n: int, fs: float, f0: float, f1: float) -> np.ndarray:
    T = n / fs
    t = np.arange(n, dtype=np.float64) / fs
    k = (f1 / f0) ** (1.0 / T)
    return np.sin(2.0 * math.pi * f0 * (np.power(k, t) - 1.0) / math.log(k))


def simulate_axis(sp: np.ndarray, fs: float, loop: AxisLoop, rng: np.random.Generator) -> np.ndarray:
    """Closed-loop rate response; returns the measured (fed-back) gyro."""
    dt = 1.0 / fs
    kp = loop.pid[0] * KP_PER_UNIT
    ki = loop.pid[1] * KI_PER_UNIT
    kd = loop.pid[2] * KD_PER_UNIT
    b = PLANT_GAIN[loop.axis] * loop.plant_scale
    a_m = dt / (dt + MOTOR_TAU_S)
    a_d = dt / (dt + 1.0 / (2.0 * math.pi * DTERM_LPF_HZ))
    d = loop.delay_samples
    n = sp.shape[0]
    omega = 0.0
    thrust = 0.0
    integ = 0.0
    dfilt = 0.0
    prev_meas = 0.0
    hist = np.zeros(n + d + 1)
    meas_out = np.zeros(n)
    for i in range(n):
        meas = hist[i]
        e = sp[i] - meas
        integ += e * dt
        dfilt += ((meas - prev_meas) / dt - dfilt) * a_d
        prev_meas = meas
        u = kp * e + ki * integ - kd * dfilt
        thrust += (u - thrust) * a_m
        omega += dt * b * thrust
        hist[i + d] = omega
        meas_out[i] = meas
    return meas_out + rng.normal(0.0, loop.noise_std, size=n) if loop.noise_std else meas_out


def _headers(case: BblCase) -> list[tuple[str, str]]:
    pids = case.header_pids or {}
    defaults = {0: (45, 80, 30), 1: (47, 84, 34), 2: (45, 80, 0)}
    for ax in case.axes:
        pids.setdefault(ax.axis, tuple(int(v) for v in ax.pid))
    for ax, v in defaults.items():
        pids.setdefault(ax, v)
    h = [
        ("Data version", "2"),
        ("I interval", str(I_INTERVAL)),
        ("P interval", case.p_interval),
        ("Firmware type", "Cleanflight"),
        ("Firmware revision", "Betaflight 2026.6.0 (synthetic) STM32F7X2"),
        ("Board information", "SYNT SYNTHETIC"),
        ("looptime", str(case.looptime)),
        ("pid_process_denom", str(case.pid_process_denom)),
        ("debug_mode", str(CHIRP_DEBUG_MODE_API_1_49)),
        ("blackbox_high_resolution", "0"),
        ("chirp_lag_freq_hz", "3"),
        ("chirp_lead_freq_hz", "30"),
        ("chirp_amplitude_roll", "150"),
        ("chirp_amplitude_pitch", "150"),
        ("chirp_amplitude_yaw", "150"),
        ("chirp_frequency_start_deci_hz", str(case.chirp_start_deci_hz)),
        ("chirp_frequency_end_deci_hz", str(case.chirp_end_deci_hz)),
        ("chirp_time_seconds", "6"),
        ("rollPID", ",".join(str(v) for v in pids[0])),
        ("pitchPID", ",".join(str(v) for v in pids[1])),
        ("yawPID", ",".join(str(v) for v in pids[2])),
    ]
    if case.pids_mode is not None:
        h.append(("simplified_pids_mode", case.pids_mode))
    h += list(case.sliders.items())
    if case.dterm_filter is not None:
        h.append(("simplified_dterm_filter", case.dterm_filter))
    return [(k, v) for k, v in h if k not in case.omit_headers]


def build_case(case: BblCase) -> tuple[bytes, dict]:
    rng = np.random.default_rng(case.seed)
    pnum, pden = _p_interval_parts(case.p_interval)
    pid_period_us = case.looptime * case.pid_process_denom
    log_rate = 1e6 * pnum / (pid_period_us * pden)
    log = BblLog(_headers(case), chirp_main_fields(include_debug3=True))
    iteration = 0
    t0 = 10_000_000

    def next_iteration() -> int:
        nonlocal iteration
        while not _should_have_frame(iteration, pnum, pden):
            iteration += 1
        it = iteration
        iteration += 1
        return it

    def emit(setpoint: float, gyro: float, axis_slot: int, debug_axis: int) -> None:
        it = next_iteration()
        sp = [0, 0, 0]
        gy = [int(round(rng.normal(0.0, 0.5))) for _ in range(3)]
        if axis_slot >= 0:
            sp[axis_slot] = int(round(setpoint))
            gy[axis_slot] = int(round(gyro))
        t = t0 if case.freeze_time else t0 + it * pid_period_us
        log.add_i_frame([it, t, *sp, 1300, *gy, int(round(setpoint)), debug_axis, 0, 0, 1200, 1200, 1200, 1200])

    log.add_s_frame(0)
    for _ in range(200):
        emit(0.0, 0.0, -1, -1)
    log.add_s_frame(BOXCHIRP_FLAG)
    meta_axes = []
    for idx, ax in enumerate(case.axes):
        if idx > 0:
            for _ in range(50):
                emit(0.0, 0.0, -1, -1)
        n = int(round(ax.seconds * log_rate))
        sp_wave = ax.amplitude * _chirp_wave(n, log_rate, case.chirp_start_deci_hz / 10.0, case.chirp_end_deci_hz / 10.0)
        sp_q = np.round(sp_wave)
        gyro = simulate_axis(sp_q, log_rate, ax, rng)
        for j in range(n):
            emit(float(sp_q[j]), float(gyro[j]), ax.axis, ax.axis)
        meta_axes.append({"axis": ax.axis, "pid": list(ax.pid), "plant_scale": ax.plant_scale, "delay_samples": ax.delay_samples,
                          "noise_std": ax.noise_std, "amplitude": ax.amplitude, "samples": n})
    for _ in range(5):
        emit(0.0, 0.0, -1, -1)
    log.add_s_frame(0)
    for _ in range(100):
        emit(0.0, 0.0, -1, -1)
    log.add_log_end()
    data = log.to_bytes()
    return data, {
        "case_id": case.case_id,
        "description": case.description,
        "classification": case.classification,
        "bbl": f"bbl/{case.case_id}.bbl.gz",
        "bbl_sha256": hashlib.sha256(data).hexdigest(),
        "seed": case.seed,
        "headers": dict(_headers(case)),
        "nominal_log_rate_hz": log_rate,
        "axes": meta_axes,
        "covers": case.covers,
        "expect": case.expect,
    }


def _bbl_cases() -> list[BblCase]:
    roll = lambda **kw: AxisLoop(axis=0, pid=(45, 80, 30), **kw)  # noqa: E731
    nominal3 = [
        AxisLoop(axis=0, pid=(45, 80, 30)),
        AxisLoop(axis=1, pid=(47, 84, 34)),
        AxisLoop(axis=2, pid=(45, 80, 0)),
    ]
    low_sliders = {**DEFAULT_SLIDERS, "simplified_pi_gain": "30", "simplified_i_gain": "30", "simplified_feedforward_gain": "30"}
    high_sliders = {**DEFAULT_SLIDERS, "simplified_pi_gain": "240", "simplified_i_gain": "245", "simplified_feedforward_gain": "245"}
    return [
        BblCase("nominal_three_axis", "Roll, pitch, yaw closed loops at 1 kHz; default sliders, RPY mode.", [EXACT], nominal3,
                seed=101, covers=["nominal_roll", "nominal_pitch", "nominal_yaw"], expect={"status": "proposed_with_warnings", "axes": [0, 1, 2]}),
        BblCase("low_plant_gain", "Roll airframe gain x0.2: low crossover, asks for more gain.", [EXACT],
                [roll(plant_scale=0.2)], seed=102, covers=["low_plant_gain"], expect={"blocked": False}),
        BblCase("high_plant_gain", "Roll airframe gain x2: high crossover, sensitivity bound holds the gain back.", [EXACT],
                [roll(plant_scale=2.0)], seed=103, covers=["high_plant_gain"], expect={"blocked": False}),
        BblCase("delayed_plant", "Roll with 4-sample measurement delay.", [EXACT], [roll(delay_samples=4)], seed=104,
                covers=["delayed_plant"], expect={"blocked": False}),
        BblCase("noisy_usable", "Roll with gyro noise sigma 12 deg/s (usable).", [EXACT], [roll(noise_std=12.0)], seed=105,
                covers=["noisy_usable"], expect={"blocked": False}),
        BblCase("near_quality_threshold", "Roll noise tuned so mean 5-100 Hz coherence sits just above 0.6.", [EXACT, HARDENING],
                [roll(noise_std=25.0, amplitude=60.0)], seed=106, covers=["near_quality_threshold"], expect={"blocked": False}),
        BblCase("low_coherence", "Roll buried in sigma 400 noise: WU7 low_coherence gate blocks.", [EXACT, HARDENING],
                [roll(noise_std=400.0, amplitude=40.0)], seed=107, covers=["low_coherence"],
                expect={"blocked": True, "reasons": ["system_id:low_coherence"]}),
        BblCase("insufficient_frequency_range", "Sweep 0.2-3 Hz only: no usable band.", [EXACT, HARDENING], [roll()],
                chirp_start_deci_hz=2, chirp_end_deci_hz=30, seed=108, covers=["insufficient_frequency_range"],
                expect={"blocked": True, "reasons": ["system_id:unusable_frequency_range"]}),
        BblCase("invalid_sample_rate", "No rate headers and frozen timestamps: no defensible rate (upstream assumes 8 kHz).",
                [HARDENING], [roll()], omit_headers=("looptime", "pid_process_denom", "P interval"), freeze_time=True, seed=109,
                covers=["invalid_sample_rate"], expect={"blocked": True, "reasons": ["system_id:invalid_sample_rate"]}),
        BblCase("slider_upper_clamp", "Sliders near 250 on a low-gain airframe: proposals clamp at 250.", [EXACT],
                [roll(plant_scale=0.2)], sliders=high_sliders, seed=110, covers=["slider_clamp_upper"], expect={"blocked": False}),
        BblCase("slider_lower_clamp", "Sliders near 25 on a high-gain airframe: proposals clamp at 25.", [EXACT],
                [roll(plant_scale=3.0)], sliders=low_sliders, seed=111, covers=["slider_clamp_lower"], expect={"blocked": False}),
        BblCase("unusual_pids", "Unusual roll PIDs 120/20/80 (simulated loop uses them).", [EXACT],
                [AxisLoop(axis=0, pid=(120, 20, 80))], seed=112, covers=["unusual_current_pids"], expect={"blocked": False}),
        BblCase("missing_tune_headers", "No simplified_* / PID headers: upstream defaults to 100, GyroCore blocks.",
                [EXACT, HARDENING], [roll()], omit_headers=tuple(DEFAULT_SLIDERS) + ("rollPID", "pitchPID", "yawPID",
                "simplified_pids_mode", "simplified_dterm_filter"), seed=113, covers=["missing_current_tune"],
                expect={"blocked": True, "reasons": ["current_tune_missing:pi_gain"]}),
        BblCase("zero_slider", "simplified_feedforward_gain 0: upstream reads it as 100, GyroCore blocks.", [EXACT, HARDENING],
                [roll()], sliders={**DEFAULT_SLIDERS, "simplified_feedforward_gain": "0"}, seed=114, covers=["zero_slider"],
                expect={"blocked": True, "reasons": ["current_tune_zero:feedforward_gain"]}),
        BblCase("pids_mode_off", "simplified_pids_mode 0: sliders do not drive PIDs.", [EXACT, HARDENING], [roll()],
                pids_mode="0", seed=115, covers=["pids_mode_off"], expect={"blocked": True, "reasons": ["simplified_pids_mode_off"]}),
        BblCase("pids_mode_rp_yaw", "simplified_pids_mode RP with three axes: yaw is not slider-controlled.", [EXACT, HARDENING],
                nominal3, pids_mode="1", seed=116, covers=["pids_mode_rp"], expect={"blocked_axes": [2]}),
        BblCase("log_rate_2k", "PID 2 kHz logged 1/1 (2 kHz).", [EXACT], [roll()], looptime=125, pid_process_denom=4, seed=117,
                covers=["logging_rate_2k"], expect={"blocked": False}),
        BblCase("log_rate_4k", "PID 8 kHz logged at P interval 1/2 (4 kHz).", [EXACT], [roll()], looptime=125, pid_process_denom=1,
                p_interval="1/2", seed=118, covers=["logging_rate_4k"], expect={"blocked": False}),
        BblCase("log_rate_below_pid", "PID 4 kHz logged at P interval 1/4 (1 kHz).", [EXACT], [roll()], looptime=125,
                pid_process_denom=2, p_interval="1/4", seed=119, covers=["logging_rate_below_pid"], expect={"blocked": False}),
    ]


def main(argv: list[str]) -> None:
    (OUT_DIR / "bbl").mkdir(parents=True, exist_ok=True)
    manifest = []
    for case in _bbl_cases():
        data, meta = build_case(case)
        with gzip.GzipFile(OUT_DIR / meta["bbl"], "wb", mtime=0) as fh:
            fh.write(data)
        manifest.append(meta)
    (OUT_DIR / "bbl_cases.json").write_text(json.dumps({"presets": PRESETS, "cases": manifest}, indent=1) + "\n")
    (OUT_DIR / "synthetic_cases.json").write_text(json.dumps({"cases": _synthetic_cases()}, indent=1) + "\n")
    print(f"wrote {len(manifest)} BBL cases and {len(_synthetic_cases())} synthetic cases to {OUT_DIR}")


if __name__ == "__main__":
    main(sys.argv[1:])
