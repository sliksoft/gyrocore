"""Betaflight Autotune gain recommendation — port of ``recommendGains``.

Upstream (immutable): ``third_party/betaflight/configurator/src/js/blackbox/
spectral_analysis.ts`` ``recommendGains`` / ``extractMetrics`` /
``computeGainScales`` / ``buildProposedSliders`` and every private helper they
call, plus ``src/composables/useAutotune.ts`` ``buildGains``.

The open loop comes from the WU7 port (:func:`gyrocore.chirp.open_loop_response`);
nothing here re-derives system-ID quantities.

Upstream recommends *simplified-tuning slider* multipliers, not absolute PID
values: "P" is ``piScale`` (``slider_pi_gain``), "I" is ``iScale``
(``slider_i_gain``), "D" is ``dScale`` (``slider_d_gain``, always held at 1),
FF is ``ffScale`` and the D-term filter is ``filterScale``. The firmware turns
sliders into PIDs (``simplified_tuning.c``, not vendored); that conversion is not
performed here.

Numerics follow the TypeScript operation order (sequential sums, the same
``gain += 0.01`` grid accumulation, ``Math.round`` half-up, ``clamp`` =
``Math.min(Math.max(v, lo), hi)``) so only transcendental-function ulps differ.

The returned objects are analysis values, never an actionable tune.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

import numpy as np

from gyrocore.chirp.system_id import (
    CROSSOVER_COHERENCE_MIN,
    OpenLoopResponse,
    TransferFunction,
    open_loop_response,
)

DEFAULT_DTERM_FILTER_HZ = 150.0
GAIN_SCALE_MIN = 0.5
GAIN_SCALE_MAX = 2.0
MAX_SENSITIVITY_PEAK = 2.0
SENSITIVITY_BIND_TOLERANCE = 0.02
GAIN_SCAN_STEP = 0.01
GAIN_SCAN_EPSILON = 1e-9
CROSSOVER_MAGNITUDE_FLOOR = 1e-9
SENSITIVITY_DISTANCE_FLOOR = 1e-9
SLIDER_MIN = 25
SLIDER_MAX = 250
BANDWIDTH_COHERENCE_MIN = 0.3
RESONANCE_COHERENCE_MIN = 0.3
RESONANCE_MAX_HZ = 500.0
LOW_FREQ_ERROR_BAND_HZ = (2.0, 10.0)
LOW_FREQ_ERROR_COHERENCE_MIN = 0.3
NOISE_FLOOR_COHERENCE = 0.5
NOISE_FLOOR_MIN_HZ = 20.0
MEAN_COHERENCE_BAND_HZ = (5.0, 100.0)
LOOP_DELAY_BAND_HZ = (20.0, 140.0)
LOOP_DELAY_MIN_BINS = 5

PHASE_MARGIN_PRESETS: dict[str, float] = {
    "AGGRESSIVE": 50.0,
    "NORMAL": 60.0,
    "CONSERVATIVE": 72.5,
}

SLIDER_KEYS: tuple[tuple[str, str], ...] = (
    ("slider_master_multiplier", "master_multiplier"),
    ("slider_pi_gain", "pi_gain"),
    ("slider_i_gain", "i_gain"),
    ("slider_d_gain", "d_gain"),
    ("slider_feedforward_gain", "feedforward_gain"),
    ("slider_dterm_filter_multiplier", "dterm_filter_multiplier"),
)

NAN = float("nan")


def js_clamp(value: float, lo: float, hi: float) -> float:
    """``utils/common.clamp``: ``Math.min(Math.max(value, lo), hi)`` (NaN propagates)."""
    if math.isnan(value):
        return NAN
    return min(max(value, lo), hi)


def js_math_round(value: float) -> float:
    """``Math.round``: ties toward +infinity; NaN/inf pass through."""
    if not math.isfinite(value):
        return value
    floor = math.floor(value)
    return float(floor + 1 if value - floor >= 0.5 else floor)


def _finite(x: float) -> bool:
    return x is not None and math.isfinite(x)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CurrentSliders:
    """``CurrentSliders`` (decimals, 1.0 = 100). ``None`` behaves like upstream ``undefined`` (``?? 1``)."""

    master_multiplier: float | None = None
    pi_gain: float | None = None
    i_gain: float | None = None
    d_gain: float | None = None
    feedforward_gain: float | None = None
    dterm_filter_multiplier: float | None = None

    def value(self, name: str) -> float:
        v = getattr(self, name)
        return 1.0 if v is None else float(v)

    def to_dict(self) -> dict[str, float | None]:
        return asdict(self)

    @classmethod
    def from_upstream(cls, mapping: Mapping[str, Any]) -> "CurrentSliders":
        """From the upstream camelCase object (``masterMultiplier`` ...)."""
        keys = {
            "masterMultiplier": "master_multiplier",
            "piGain": "pi_gain",
            "iGain": "i_gain",
            "dGain": "d_gain",
            "feedforwardGain": "feedforward_gain",
            "dtermFilterMultiplier": "dterm_filter_multiplier",
        }
        return cls(**{py: (None if mapping.get(js) is None else float(mapping[js])) for js, py in keys.items()})


# ---------------------------------------------------------------------------
# Metrics (extractMetrics and helpers)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Crossover:
    frequency_hz: float
    phase_margin_deg: float
    bin_index: int
    fraction: float


@dataclass(frozen=True)
class TargetCrossover:
    frequency_hz: float
    gain_scale: float
    magnitude_at: float
    bin_index: int
    fraction: float


@dataclass(frozen=True)
class SensitivityScan:
    within_bound: float
    least_bad: float
    held: bool
    gains: tuple[float, ...]
    peaks: tuple[float, ...]


def find_open_loop_crossover(tf: TransferFunction, ol: OpenLoopResponse) -> Crossover | None:
    """``findOpenLoopCrossover``: first downward |L| = 1 crossing between coherent bins."""
    f, coh, mag, ph = tf.frequencies, tf.coherence, ol.magnitude, ol.phase_deg
    for k in range(ol.start_index + 1, f.shape[0]):
        if math.isnan(mag[k]) or math.isnan(mag[k - 1]):
            continue
        if coh[k] < CROSSOVER_COHERENCE_MIN or coh[k - 1] < CROSSOVER_COHERENCE_MIN:
            continue
        if mag[k] <= 1 and mag[k - 1] > 1:
            frac = (1 - mag[k - 1]) / (mag[k] - mag[k - 1])
            return Crossover(
                float(f[k - 1] + frac * (f[k] - f[k - 1])),
                float(180 + ph[k - 1] + frac * (ph[k] - ph[k - 1])),
                k,
                float(frac),
            )
    return None


def find_target_crossover(tf: TransferFunction, ol: OpenLoopResponse, target_phase_margin_deg: float) -> TargetCrossover | None:
    """``findTargetCrossover``: where unwrapped phase first falls through ``-(180 - PM)``."""
    f, coh, mag, ph = tf.frequencies, tf.coherence, ol.magnitude, ol.phase_deg
    wanted = -(180 - target_phase_margin_deg)
    for k in range(ol.start_index + 1, f.shape[0]):
        if math.isnan(ph[k]) or math.isnan(ph[k - 1]):
            continue
        if coh[k] < CROSSOVER_COHERENCE_MIN or coh[k - 1] < CROSSOVER_COHERENCE_MIN:
            continue
        if ph[k] <= wanted and ph[k - 1] > wanted:
            frac = (wanted - ph[k - 1]) / (ph[k] - ph[k - 1])
            magnitude_at = mag[k - 1] + frac * (mag[k] - mag[k - 1])
            if math.isnan(magnitude_at) or magnitude_at <= CROSSOVER_MAGNITUDE_FLOOR:
                return None
            return TargetCrossover(
                float(f[k - 1] + frac * (f[k] - f[k - 1])),
                float(1 / magnitude_at),
                float(magnitude_at),
                k,
                float(frac),
            )
    return None


def _sensitivity_terms(tf: TransferFunction, ol: OpenLoopResponse) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    k0 = ol.start_index
    mag = ol.magnitude[k0:]
    keep = ~np.isnan(mag) & ~(tf.coherence[k0:] < CROSSOVER_COHERENCE_MIN)
    mag = mag[keep]
    phase_rad = (ol.phase_deg[k0:][keep] * math.pi) / 180
    return mag, np.cos(phase_rad), np.sin(phase_rad)


def peak_sensitivity_at_gain(tf: TransferFunction, ol: OpenLoopResponse, gain_scale: float, _terms=None) -> float:
    """``peakSensitivityAtGain``: max ``1/|1 + g L|`` over coherent bins (NaN when none)."""
    mag, cos_p, sin_p = _terms if _terms is not None else _sensitivity_terms(tf, ol)
    gm = gain_scale * mag
    real = 1 + gm * cos_p
    imag = gm * sin_p
    distance = np.hypot(real, imag)
    ok = distance > SENSITIVITY_DISTANCE_FLOOR
    if not ok.any():
        return NAN
    peak = float(np.max(1 / distance[ok]))
    return peak if peak > 0 else NAN


def scan_sensitivity(
    tf: TransferFunction,
    ol: OpenLoopResponse,
    limit: float,
    max_gain: float = GAIN_SCALE_MAX,
    _terms=None,
) -> SensitivityScan:
    """``scanSensitivity``: walk ``[0.5, max_gain]`` in 0.01 steps (JS float accumulation)."""
    terms = _terms if _terms is not None else _sensitivity_terms(tf, ol)
    within, least, best = NAN, NAN, math.inf
    gains: list[float] = []
    peaks: list[float] = []
    gain = GAIN_SCALE_MIN
    while gain <= max_gain + GAIN_SCAN_EPSILON:
        peak = peak_sensitivity_at_gain(tf, ol, gain, terms)
        gains.append(gain)
        peaks.append(peak)
        if not math.isfinite(peak):
            hold = min(1.0, max_gain)
            return SensitivityScan(hold, hold, True, tuple(gains), tuple(peaks))
        if peak <= limit:
            within = gain
        if peak < best:
            best = peak
            least = gain
        gain += GAIN_SCAN_STEP
    return SensitivityScan(within, least, False, tuple(gains), tuple(peaks))


def find_max_achievable_phase_margin(tf: TransferFunction, ol: OpenLoopResponse) -> float:
    peak = -math.inf
    for k in range(ol.start_index, tf.frequencies.shape[0]):
        p = ol.phase_deg[k]
        if math.isnan(p) or tf.coherence[k] < CROSSOVER_COHERENCE_MIN:
            continue
        if p > peak:
            peak = float(p)
    return 180 + peak if math.isfinite(peak) else NAN


def estimate_loop_delay_ms(
    tf: TransferFunction, ol: OpenLoopResponse, f_lo_hz: float = LOOP_DELAY_BAND_HZ[0], f_hi_hz: float = LOOP_DELAY_BAND_HZ[1]
) -> float:
    """``estimateLoopDelayMs``: least-squares slope of unwrapped phase over 20-140 Hz."""
    n = 0
    sx = sy = sxx = sxy = 0.0
    for k in range(ol.start_index, tf.frequencies.shape[0]):
        f = float(tf.frequencies[k])
        if f < f_lo_hz or f > f_hi_hz:
            continue
        p = float(ol.phase_deg[k])
        if math.isnan(p) or tf.coherence[k] < CROSSOVER_COHERENCE_MIN:
            continue
        n += 1
        sx += f
        sy += p
        sxx += f * f
        sxy += f * p
    if n < LOOP_DELAY_MIN_BINS:
        return NAN
    denom = n * sxx - sx * sx
    if abs(denom) < 1e-12:
        return NAN
    slope = (n * sxy - sx * sy) / denom
    return (-slope / 360) * 1000


def find_bandwidth(tf: TransferFunction) -> float:
    f, m, c = tf.frequencies, tf.magnitude_db, tf.coherence
    for k in range(1, f.shape[0]):
        if c[k - 1] < BANDWIDTH_COHERENCE_MIN or c[k] < BANDWIDTH_COHERENCE_MIN:
            continue
        if m[k] <= -3 and m[k - 1] > -3:
            frac = (-3 - m[k - 1]) / (m[k] - m[k - 1])
            return float(f[k - 1] + frac * (f[k] - f[k - 1]))
    return NAN


def find_resonant_peak(tf: TransferFunction) -> tuple[float, float]:
    f, m, c = tf.frequencies, tf.magnitude_db, tf.coherence
    peak_db, peak_hz = -math.inf, 0.0
    for k in range(1, f.shape[0]):
        if c[k] < RESONANCE_COHERENCE_MIN:
            continue
        if 0 < f[k] < RESONANCE_MAX_HZ and m[k] > peak_db:
            peak_db, peak_hz = float(m[k]), float(f[k])
    return peak_db, peak_hz


def compute_low_freq_error(tf: TransferFunction) -> float:
    total, count = 0.0, 0
    lo, hi = LOW_FREQ_ERROR_BAND_HZ
    for k in range(tf.frequencies.shape[0]):
        f = tf.frequencies[k]
        if lo <= f <= hi and tf.coherence[k] > LOW_FREQ_ERROR_COHERENCE_MIN:
            total += float(tf.magnitude_db[k])
            count += 1
    return total / count if count > 0 else 0.0


def find_noise_floor(tf: TransferFunction) -> float:
    f, c = tf.frequencies, tf.coherence
    ever = False
    for k in range(1, f.shape[0]):
        if c[k] >= NOISE_FLOOR_COHERENCE:
            ever = True
        elif ever and f[k] > NOISE_FLOOR_MIN_HZ:
            return float(f[k])
    return float(f[-1]) if ever and f.shape[0] else NAN


def compute_mean_coherence(tf: TransferFunction) -> float:
    total, count = 0.0, 0
    lo, hi = MEAN_COHERENCE_BAND_HZ
    for k in range(tf.frequencies.shape[0]):
        if lo <= tf.frequencies[k] <= hi:
            total += float(tf.coherence[k])
            count += 1
    return total / count if count > 0 else 0.0


@dataclass(frozen=True)
class GainMetrics:
    """``extractMetrics`` output (NaN where upstream yields ``Number.NaN``)."""

    bandwidth_hz: float
    resonant_peak_db: float
    resonant_freq_hz: float
    max_achievable_phase_margin_deg: float
    sensitivity_limited_gain: float
    open_loop_crossover_hz: float
    phase_margin_deg: float
    target_crossover_hz: float
    gain_to_target: float
    low_freq_error_db: float
    noise_floor_hz: float
    mean_coherence: float
    loop_delay_ms: float
    target_phase_margin_deg: float
    crossover: Crossover | None = field(default=None, compare=False)
    target: TargetCrossover | None = field(default=None, compare=False)
    sensitivity_scan: SensitivityScan | None = field(default=None, compare=False, repr=False)


def extract_metrics(tf: TransferFunction, ol: OpenLoopResponse, target_phase_margin_deg: float, _terms=None) -> GainMetrics:
    peak_db, peak_hz = find_resonant_peak(tf)
    crossover = find_open_loop_crossover(tf, ol)
    target = find_target_crossover(tf, ol, target_phase_margin_deg)
    scan = scan_sensitivity(tf, ol, MAX_SENSITIVITY_PEAK, _terms=_terms)
    return GainMetrics(
        bandwidth_hz=find_bandwidth(tf),
        resonant_peak_db=peak_db,
        resonant_freq_hz=peak_hz,
        max_achievable_phase_margin_deg=find_max_achievable_phase_margin(tf, ol),
        sensitivity_limited_gain=scan.within_bound,
        open_loop_crossover_hz=crossover.frequency_hz if crossover else NAN,
        phase_margin_deg=crossover.phase_margin_deg if crossover else NAN,
        target_crossover_hz=target.frequency_hz if target else NAN,
        gain_to_target=target.gain_scale if target else NAN,
        low_freq_error_db=compute_low_freq_error(tf),
        noise_floor_hz=find_noise_floor(tf),
        mean_coherence=compute_mean_coherence(tf),
        loop_delay_ms=estimate_loop_delay_ms(tf, ol),
        target_phase_margin_deg=float(target_phase_margin_deg),
        crossover=crossover,
        target=target,
        sensitivity_scan=scan,
    )


# ---------------------------------------------------------------------------
# Gain scales (computeGainScales and helpers)
# ---------------------------------------------------------------------------


def resonance_backoffs(resonant_peak_db: float) -> tuple[float, float]:
    """``resonanceBackoffs`` -> ``(resonanceBackoff, ffResonanceBackoff)``."""
    if resonant_peak_db > 6:
        return 0.75, 0.8
    if resonant_peak_db > 3:
        return 0.9, 1.0
    return 1.0, 1.0


def gain_clamp_limit_of(gain_clamped: bool, requested_gain: float) -> float:
    if not gain_clamped:
        return NAN
    return GAIN_SCALE_MAX if requested_gain > GAIN_SCALE_MAX else GAIN_SCALE_MIN


@dataclass(frozen=True)
class RobustGain:
    pi_scale: float
    sensitivity_unreachable: bool
    peak_at_admissible_max: float
    scan: SensitivityScan | None


def robust_gain(tf: TransferFunction, ol: OpenLoopResponse, admissible_max: float, _terms=None) -> RobustGain:
    peak = peak_sensitivity_at_gain(tf, ol, admissible_max, _terms)
    if math.isnan(peak) or peak <= MAX_SENSITIVITY_PEAK:
        return RobustGain(admissible_max, False, peak, None)
    scan = scan_sensitivity(tf, ol, MAX_SENSITIVITY_PEAK, admissible_max, _terms)
    if math.isfinite(scan.within_bound):
        return RobustGain(scan.within_bound, False, peak, scan)
    return RobustGain(scan.least_bad if math.isfinite(scan.least_bad) else admissible_max, True, peak, scan)


def integral_scale(low_freq_error_db: float) -> float:
    if low_freq_error_db < -1:
        return 1 + abs(low_freq_error_db) * 0.1
    if low_freq_error_db > 2:
        return 1 - low_freq_error_db * 0.05
    return 1.0


@dataclass(frozen=True)
class GainScales:
    """``computeGainScales`` output plus the pre-clamp / shaping terms it uses internally."""

    pi_scale: float
    requested_gain: float
    i_scale: float
    d_scale: float
    ff_scale: float
    filter_scale: float
    sensitivity_binds: bool
    gain_clamped: bool
    gain_clamp_limit: float
    sensitivity_unreachable: bool
    predicted_sensitivity_peak_db: float
    # internal terms (not in upstream's return value, same expressions)
    gain_for_margin: float
    resonance_backoff: float
    ff_resonance_backoff: float
    admissible_max: float
    robust_pi_scale: float
    robustness_factor: float
    raw_i_scale: float
    raw_ff_scale: float
    raw_filter_scale: float
    robust: RobustGain | None = field(default=None, compare=False, repr=False)


def compute_gain_scales(metrics: GainMetrics, tf: TransferFunction, ol: OpenLoopResponse, _terms=None) -> GainScales:
    gain_to_target = metrics.gain_to_target
    gain_for_margin = gain_to_target if math.isfinite(gain_to_target) else 1.0
    backoff, ff_backoff = resonance_backoffs(metrics.resonant_peak_db)
    requested = gain_for_margin * backoff
    admissible_max = js_clamp(requested, GAIN_SCALE_MIN, GAIN_SCALE_MAX)
    gain_clamped = math.isfinite(gain_to_target) and (requested > GAIN_SCALE_MAX or requested < GAIN_SCALE_MIN)
    clamp_limit = gain_clamp_limit_of(gain_clamped, requested)
    robust = robust_gain(tf, ol, admissible_max, _terms)
    pi_scale = robust.pi_scale
    binds = pi_scale < admissible_max * (1 - SENSITIVITY_BIND_TOLERANCE)
    d_scale = 1.0
    raw_i = integral_scale(metrics.low_freq_error_db)
    robustness_factor = pi_scale / admissible_max
    raw_ff = gain_for_margin * ff_backoff * robustness_factor
    raw_filter = metrics.noise_floor_hz / DEFAULT_DTERM_FILTER_HZ if math.isfinite(metrics.noise_floor_hz) else 1.0
    final_pi = js_clamp(pi_scale, GAIN_SCALE_MIN, GAIN_SCALE_MAX)
    predicted = peak_sensitivity_at_gain(tf, ol, final_pi, _terms)
    return GainScales(
        pi_scale=final_pi,
        requested_gain=requested,
        i_scale=js_clamp(raw_i, GAIN_SCALE_MIN, GAIN_SCALE_MAX),
        d_scale=d_scale,
        ff_scale=js_clamp(raw_ff, GAIN_SCALE_MIN, GAIN_SCALE_MAX),
        filter_scale=js_clamp(raw_filter, GAIN_SCALE_MIN, 1.0),
        sensitivity_binds=bool(binds),
        gain_clamped=bool(gain_clamped),
        gain_clamp_limit=clamp_limit,
        sensitivity_unreachable=robust.sensitivity_unreachable,
        predicted_sensitivity_peak_db=20 * math.log10(predicted) if predicted > 0 else NAN,
        gain_for_margin=gain_for_margin,
        resonance_backoff=backoff,
        ff_resonance_backoff=ff_backoff,
        admissible_max=admissible_max,
        robust_pi_scale=pi_scale,
        robustness_factor=robustness_factor,
        raw_i_scale=raw_i,
        raw_ff_scale=raw_ff,
        raw_filter_scale=raw_filter,
        robust=robust,
    )


# ---------------------------------------------------------------------------
# Sliders (buildProposedSliders)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SliderProposal:
    """One slider: ``current * scale * 100`` -> clamp [25, 250] -> ``Math.round``."""

    key: str
    current: float
    scale: float
    raw: float
    clamped: float
    rounded: float
    clamped_by_slider_limit: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_proposed_sliders(current: CurrentSliders, scales: GainScales) -> dict[str, SliderProposal]:
    scale_for = {
        "master_multiplier": 1.0,
        "pi_gain": scales.pi_scale,
        "i_gain": scales.i_scale,
        "d_gain": scales.d_scale,
        "feedforward_gain": scales.ff_scale,
        "dterm_filter_multiplier": scales.filter_scale,
    }
    out: dict[str, SliderProposal] = {}
    for key, name in SLIDER_KEYS:
        cur = current.value(name)
        scale = scale_for[name]
        # upstream: master is (cur * 100); the others (cur * scale * 100), left to right
        raw = cur * 100 if name == "master_multiplier" else cur * scale * 100
        clamped = js_clamp(raw, SLIDER_MIN, SLIDER_MAX)
        out[key] = SliderProposal(key, cur, scale, raw, clamped, js_math_round(clamped), bool(raw < SLIDER_MIN or raw > SLIDER_MAX))
    return out


# ---------------------------------------------------------------------------
# recommendGains
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GainRecommendation:
    """``recommendGains`` result: ``proposed`` sliders and merged ``analysis``. Not actionable."""

    open_loop: OpenLoopResponse
    metrics: GainMetrics
    scales: GainScales
    sliders: dict[str, SliderProposal]
    current_sliders: CurrentSliders
    target_phase_margin_deg: float

    @property
    def proposed(self) -> dict[str, float]:
        """Upstream ``proposed`` object (slider integers x100)."""
        return {k: s.rounded for k, s in self.sliders.items()}

    def analysis(self) -> dict[str, Any]:
        """Upstream ``analysis`` = ``{...metrics, ...scales}`` with upstream key names."""
        m, s = self.metrics, self.scales
        return {
            "bandwidthHz": m.bandwidth_hz,
            "resonantPeakDb": m.resonant_peak_db,
            "resonantFreqHz": m.resonant_freq_hz,
            "maxAchievablePhaseMarginDeg": m.max_achievable_phase_margin_deg,
            "sensitivityLimitedGain": m.sensitivity_limited_gain,
            "openLoopCrossoverHz": m.open_loop_crossover_hz,
            "phaseMarginDeg": m.phase_margin_deg,
            "targetCrossoverHz": m.target_crossover_hz,
            "gainToTarget": m.gain_to_target,
            "lowFreqErrorDb": m.low_freq_error_db,
            "noiseFloorHz": m.noise_floor_hz,
            "meanCoherence": m.mean_coherence,
            "loopDelayMs": m.loop_delay_ms,
            "targetPhaseMarginDeg": m.target_phase_margin_deg,
            "piScale": s.pi_scale,
            "requestedGain": s.requested_gain,
            "iScale": s.i_scale,
            "dScale": s.d_scale,
            "ffScale": s.ff_scale,
            "filterScale": s.filter_scale,
            "sensitivityBinds": s.sensitivity_binds,
            "gainClamped": s.gain_clamped,
            "gainClampLimit": s.gain_clamp_limit,
            "sensitivityUnreachable": s.sensitivity_unreachable,
            "predictedSensitivityPeakDb": s.predicted_sensitivity_peak_db,
        }

    def shaping_terms(self) -> dict[str, float]:
        s = self.scales
        return {
            "gainForMargin": s.gain_for_margin,
            "resonanceBackoff": s.resonance_backoff,
            "ffResonanceBackoff": s.ff_resonance_backoff,
            "admissibleMax": s.admissible_max,
            "robustPiScale": s.robust_pi_scale,
            "robustnessFactor": s.robustness_factor,
            "rawIScale": s.raw_i_scale,
            "rawFfScale": s.raw_ff_scale,
            "rawFilterScale": s.raw_filter_scale,
        }


def recommend_gains(
    tf: TransferFunction,
    current_sliders: CurrentSliders,
    target_phase_margin_deg: float = PHASE_MARGIN_PRESETS["NORMAL"],
    *,
    open_loop: OpenLoopResponse | None = None,
) -> GainRecommendation:
    """Port of ``recommendGains(tf, currentSliders, targetPhaseMarginDeg)``."""
    ol = open_loop if open_loop is not None else open_loop_response(tf)
    terms = _sensitivity_terms(tf, ol)
    metrics = extract_metrics(tf, ol, target_phase_margin_deg, terms)
    scales = compute_gain_scales(metrics, tf, ol, terms)
    sliders = build_proposed_sliders(current_sliders, scales)
    return GainRecommendation(ol, metrics, scales, sliders, current_sliders, float(target_phase_margin_deg))


def build_gains(rec: GainRecommendation, sensitivity_peak_db: float, step: Any) -> dict[str, Any]:
    """``useAutotune.ts`` ``buildGains``: the per-axis summary the Autotune UI displays."""
    a = rec.analysis()
    return {
        "proposed": rec.proposed,
        "bandwidth": a["bandwidthHz"],
        "crossover": a["openLoopCrossoverHz"],
        "phaseMargin": a["phaseMarginDeg"],
        "targetCrossover": a["targetCrossoverHz"],
        "maxPhaseMargin": a["maxAchievablePhaseMarginDeg"],
        "loopDelay": a["loopDelayMs"],
        "resonantPeak": a["resonantPeakDb"],
        "sensitivityPeak": sensitivity_peak_db,
        "predictedSensitivityPeak": a["predictedSensitivityPeakDb"],
        "sensitivityBinds": a["sensitivityBinds"],
        "sensitivityUnreachable": a["sensitivityUnreachable"],
        "gainClamped": a["gainClamped"],
        "gainClampLimit": a["gainClampLimit"],
        "requestedGain": a["requestedGain"],
        "appliedGain": a["piScale"],
        "overshoot": step.overshoot_pct if step is not None else NAN,
        "riseTime": step.rise_time_ms if step is not None else NAN,
        "settlingTime": step.settling_time_ms if step is not None else NAN,
        "coherencePct": a["meanCoherence"] * 100,
    }


__all__ = [
    "CurrentSliders",
    "Crossover",
    "DEFAULT_DTERM_FILTER_HZ",
    "GAIN_SCALE_MAX",
    "GAIN_SCALE_MIN",
    "GAIN_SCAN_STEP",
    "GainMetrics",
    "GainRecommendation",
    "GainScales",
    "MAX_SENSITIVITY_PEAK",
    "PHASE_MARGIN_PRESETS",
    "RobustGain",
    "SENSITIVITY_BIND_TOLERANCE",
    "SLIDER_KEYS",
    "SLIDER_MAX",
    "SLIDER_MIN",
    "SensitivityScan",
    "SliderProposal",
    "TargetCrossover",
    "build_gains",
    "build_proposed_sliders",
    "compute_gain_scales",
    "compute_low_freq_error",
    "compute_mean_coherence",
    "estimate_loop_delay_ms",
    "extract_metrics",
    "find_bandwidth",
    "find_max_achievable_phase_margin",
    "find_noise_floor",
    "find_open_loop_crossover",
    "find_resonant_peak",
    "find_target_crossover",
    "gain_clamp_limit_of",
    "integral_scale",
    "js_clamp",
    "js_math_round",
    "peak_sensitivity_at_gain",
    "recommend_gains",
    "resonance_backoffs",
    "robust_gain",
    "scan_sensitivity",
]
