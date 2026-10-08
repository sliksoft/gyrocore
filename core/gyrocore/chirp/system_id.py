"""
CHIRP system identification — port of Betaflight Configurator spectral analysis.

Upstream (immutable, ``third_party/betaflight/configurator/``):

- ``src/js/blackbox/spectral_analysis.ts``: ``hanningWindow``,
  ``welchTransferFunction`` / ``clampSegmentSize`` / ``accumulateSpectra`` /
  ``buildTransferFunction``, ``computeSensitivity``, ``computeStepResponse``
  (+ ``stepMetrics``), ``computeSpectrogram``, ``openLoopResponse``
- ``src/js/blackbox/fft.ts``: ``ComplexFFT`` (mixed radix, unnormalized both ways)
- ``src/composables/useAutotune.ts``: ``chooseSegmentSize``, ``computeAxisResult``

Conventions (identical to upstream, locked by
``tests/fixtures/chirp/wu7/upstream_*reference.json``):

- window: symmetric Hann ``0.5 * (1 - cos(2*pi*i / (size - 1)))``
- FFT: ``X[k] = sum x[n] exp(-2j*pi*k*n/N)``; no 1/N, no window-power or
  segment-count normalization; inverse is ``exp(+...)`` and also unnormalized
  (``computeStepResponse`` divides by N itself). ``numpy.fft.rfft`` /
  ``numpy.fft.fft`` / ``numpy.fft.ifft * N`` compute exactly these sums, so the
  absolute scale equals ComplexFFT's (no cancelling factor is relied upon).
- one-sided bins ``k = 0 .. floor(seg/2)`` (DC and Nyquist included), ``f = k*fs/seg``
- ``Sxy = conj(X) * Y`` summed over segments; ``H = Sxy / Sxx``
- magnitude ``20*log10(|H|)`` dB; phase ``atan2(Im H, Re H)`` degrees in (-180, 180]
- coherence ``|Sxy|^2 / (Sxx*Syy)`` (0 when ``Sxx*Syy <= 1e-30``)
- bins with ``Sxx < 1e-20``: H = 0, magnitude -inf, phase 0, coherence 0
- hop ``Math.round(seg*(1-overlap))`` (half-up), segments
  ``max(1, floor((N-seg)/hop) + 1)``; trailing samples not covered are ignored
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

MIN_OPEN_LOOP_HZ = 2.0
CROSSOVER_COHERENCE_MIN = 0.5
SENSITIVITY_COHERENCE_MIN = 0.3
SENSITIVITY_MAX_HZ = 500.0
STEP_RESPONSE_MAX_MS = 100.0
SXX_FLOOR = 1e-20
COHERENCE_DENOM_FLOOR = 1e-30


def js_round(x: float) -> int:
    """JavaScript ``Math.round`` (ties toward +infinity)."""
    return int(math.floor(x + 0.5))


@dataclass(frozen=True)
class WelchSpectra:
    """Raw accumulated (unnormalized) Welch spectra, as ``accumulateSpectra``."""

    sxx: np.ndarray
    syy: np.ndarray
    sxy_re: np.ndarray
    sxy_im: np.ndarray
    num_segments: int
    segment_size: int
    hop_size: int


@dataclass(frozen=True)
class TransferFunction:
    frequencies: np.ndarray
    magnitude_db: np.ndarray
    phase_deg: np.ndarray
    coherence: np.ndarray
    h_real: np.ndarray
    h_imag: np.ndarray
    num_segments: int
    segment_size: int
    sample_rate_hz: float
    spectra: WelchSpectra | None = None

    @property
    def h(self) -> np.ndarray:
        return self.h_real + 1j * self.h_imag

    @property
    def num_bins(self) -> int:
        return int(self.frequencies.shape[0])


@dataclass(frozen=True)
class Sensitivity:
    frequencies: np.ndarray
    magnitude_db: np.ndarray
    phase_deg: np.ndarray
    coherence: np.ndarray
    peak_db: float


@dataclass(frozen=True)
class StepResponse:
    time_ms: np.ndarray
    response: np.ndarray
    overshoot_pct: float
    rise_time_ms: float
    settling_time_ms: float


@dataclass(frozen=True)
class Spectrogram:
    time_ms: np.ndarray
    freq_hz: np.ndarray
    power_db: np.ndarray  # shape (num_segments, num_bins)
    num_segments: int
    num_bins: int


@dataclass(frozen=True)
class OpenLoopResponse:
    magnitude: np.ndarray  # linear |L|, NaN where not computed
    phase_deg: np.ndarray  # unwrapped, NaN where not computed
    start_index: int


# ---------------------------------------------------------------------------
# FFT / window
# ---------------------------------------------------------------------------


def complex_fft(values: Sequence[float] | np.ndarray, *, inverse: bool = False, kind: str = "complex") -> np.ndarray:
    """``ComplexFFT(n, inverse).simple(out, input, kind)`` returning interleaved ``[re0, im0, ...]``.

    ``kind="real"``: ``values`` holds ``n`` real samples. ``kind="complex"``:
    interleaved complex input of length ``2n``. Neither direction is normalized.
    """
    arr = np.asarray(values, dtype=np.float64)
    if kind == "real":
        z = arr.astype(np.complex128)
    else:
        if arr.size % 2:
            raise ValueError("interleaved complex input must have even length")
        z = arr[0::2] + 1j * arr[1::2]
    n = z.size
    if n < 1:
        raise ValueError("FFT size must be positive")
    out_c = np.fft.ifft(z) * n if inverse else np.fft.fft(z)
    out = np.empty(2 * n, dtype=np.float64)
    out[0::2] = out_c.real
    out[1::2] = out_c.imag
    return out


def hanning_window(size: int) -> np.ndarray:
    """Upstream ``hanningWindow``: ``w[i] = 0.5 * (1 - cos(2*pi*i / (size - 1)))``."""
    if size < 2:
        raise ValueError("Hanning window size must be >= 2")
    i = np.arange(size, dtype=float)
    return 0.5 * (1.0 - np.cos((2.0 * np.pi * i) / (size - 1)))


def _next_pow2(n: int) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p


def _clamp_segment_size(segment_size: int, n: int) -> int:
    if segment_size <= n:
        return segment_size
    fit = _next_pow2(n)
    if fit > n:
        fit >>= 1
    return max(fit, 4)


def choose_segment_size(sample_rate_hz: float) -> int:
    """``useAutotune.chooseSegmentSize``: smallest pow2 >= 256 with seg >= rate/2, capped at 4096."""
    seg = 256
    while seg < sample_rate_hz * 0.5:
        seg <<= 1
    return min(seg, 4096)


# ---------------------------------------------------------------------------
# Welch transfer function
# ---------------------------------------------------------------------------


def welch_spectra(
    input_signal: Sequence[float] | np.ndarray,
    output_signal: Sequence[float] | np.ndarray,
    segment_size: int = 1024,
    overlap: float = 0.5,
) -> WelchSpectra:
    """``clampSegmentSize`` + ``accumulateSpectra`` (``Sxy = conj(X) * Y``)."""
    x = np.asarray(input_signal, dtype=np.float64)
    y = np.asarray(output_signal, dtype=np.float64)
    if x.shape != y.shape:
        raise ValueError("Input and output arrays must be the same length")
    n = int(x.size)
    if n < 4:
        raise ValueError("Need at least 4 samples to compute a transfer function")

    segment_size = _clamp_segment_size(int(segment_size), n)
    hop_size = max(1, js_round(segment_size * (1.0 - overlap)))
    num_segments = max(1, (n - segment_size) // hop_size + 1)
    num_bins = segment_size // 2 + 1
    window = hanning_window(segment_size)

    sxx = np.zeros(num_bins)
    syy = np.zeros(num_bins)
    sxy_re = np.zeros(num_bins)
    sxy_im = np.zeros(num_bins)
    for seg in range(num_segments):
        offset = seg * hop_size
        xk = np.fft.rfft(x[offset : offset + segment_size] * window, n=segment_size)
        yk = np.fft.rfft(y[offset : offset + segment_size] * window, n=segment_size)
        xr, xi, yr, yi = xk.real, xk.imag, yk.real, yk.imag
        sxx += xr * xr + xi * xi
        syy += yr * yr + yi * yi
        sxy_re += xr * yr + xi * yi
        sxy_im += -xi * yr + xr * yi
    return WelchSpectra(sxx, syy, sxy_re, sxy_im, num_segments, segment_size, hop_size)


def transfer_function_from_spectra(spectra: WelchSpectra, sample_rate_hz: float) -> TransferFunction:
    """``buildTransferFunction``."""
    if sample_rate_hz <= 0 or not np.isfinite(sample_rate_hz):
        raise ValueError("sample_rate_hz must be finite and > 0")
    sxx, syy, sre, sim = spectra.sxx, spectra.syy, spectra.sxy_re, spectra.sxy_im
    num_bins = sxx.shape[0]
    frequencies = np.arange(num_bins, dtype=float) * (sample_rate_hz / spectra.segment_size)
    valid = sxx >= SXX_FLOOR
    safe = np.where(valid, sxx, 1.0)
    h_real = np.where(valid, sre / safe, 0.0)
    h_imag = np.where(valid, sim / safe, 0.0)
    with np.errstate(divide="ignore"):
        magnitude = np.where(valid, 20.0 * np.log10(np.hypot(h_real, h_imag)), -np.inf)
    phase = np.where(valid, np.arctan2(h_imag, h_real) * (180.0 / np.pi), 0.0)
    denom = sxx * syy
    good = valid & (denom > COHERENCE_DENOM_FLOOR)
    coherence = np.where(good, (sre * sre + sim * sim) / np.where(good, denom, 1.0), 0.0)
    return TransferFunction(
        frequencies=frequencies,
        magnitude_db=magnitude,
        phase_deg=phase,
        coherence=coherence,
        h_real=h_real,
        h_imag=h_imag,
        num_segments=spectra.num_segments,
        segment_size=spectra.segment_size,
        sample_rate_hz=float(sample_rate_hz),
        spectra=spectra,
    )


def welch_transfer_function(
    input_signal: Sequence[float] | np.ndarray,
    output_signal: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
    segment_size: int = 1024,
    overlap: float = 0.5,
) -> TransferFunction:
    """Closed-loop H(f) = Sxy / Sxx via Welch (upstream ``welchTransferFunction``)."""
    if sample_rate_hz <= 0 or not np.isfinite(sample_rate_hz):
        raise ValueError("sample_rate_hz must be finite and > 0")
    spectra = welch_spectra(input_signal, output_signal, segment_size, overlap)
    return transfer_function_from_spectra(spectra, sample_rate_hz)


# ---------------------------------------------------------------------------
# Derived responses (upstream helpers other than recommendGains)
# ---------------------------------------------------------------------------


def compute_sensitivity(tf: TransferFunction) -> Sensitivity:
    """``computeSensitivity``: S = 1 - T; peak over 0 < f < 500 Hz with coherence >= 0.3."""
    s_re = 1.0 - tf.h_real
    s_im = -tf.h_imag
    mag = np.hypot(s_re, s_im)
    with np.errstate(divide="ignore"):
        magnitude = np.where(mag > 1e-20, 20.0 * np.log10(np.where(mag > 0, mag, 1.0)), -np.inf)
    phase = np.arctan2(s_im, s_re) * (180.0 / np.pi)
    f = tf.frequencies
    mask = (f > 0) & (f < SENSITIVITY_MAX_HZ) & (tf.coherence >= SENSITIVITY_COHERENCE_MIN)
    peak = float(np.max(magnitude[mask])) if mask.any() else float("-inf")
    return Sensitivity(f, magnitude, phase, tf.coherence, peak)


def _step_metrics(time_ms: np.ndarray, response: np.ndarray) -> tuple[float, float, float]:
    n = response.shape[0]
    if n < 2:
        return 0.0, 0.0, 0.0
    tail = max(1, int(math.floor(n * 0.9)))
    ss = float(sum(float(v) for v in response[tail:n]) / (n - tail))
    if abs(ss) < 1e-10:
        return 0.0, 0.0, 0.0
    raw = ((float(np.max(response)) - ss) / ss) * 100.0
    overshoot = max(0.0, raw) if math.isfinite(raw) else 0.0

    rise = 0.0
    start = None
    for i in range(n):
        if start is None and response[i] >= 0.1 * ss:
            start = float(time_ms[i])
        if response[i] >= 0.9 * ss:
            rise = 0.0 if start is None else max(0.0, float(time_ms[i]) - start)
            break

    settle = 0.0
    band = 0.02 * abs(ss)
    for i in range(n - 1, -1, -1):
        if abs(response[i] - ss) > band:
            settle = float(time_ms[i + 1]) if i < n - 1 else float(time_ms[i])
            break
    return overshoot, rise, settle


def compute_step_response(tf: TransferFunction, sample_rate_hz: float, segment_size: int) -> StepResponse:
    """``computeStepResponse``: IFFT of Hermitian H, cumulative sum, DC-normalized, first 100 ms."""
    num_bins = tf.h_real.shape[0]
    n = int(segment_size)
    spectrum = np.zeros(n, dtype=np.complex128)
    k_lo = min(num_bins, n)
    spectrum[:k_lo] = tf.h_real[:k_lo] + 1j * tf.h_imag[:k_lo]
    for k in range(num_bins, n):
        mk = n - k
        spectrum[k] = tf.h_real[mk] - 1j * tf.h_imag[mk]
    impulse = np.fft.ifft(spectrum).real  # == ComplexFFT inverse / N
    half = n // 2
    step = np.cumsum(impulse[:half])
    dc_gain = math.hypot(float(tf.h_real[0]), float(tf.h_imag[0]))
    if dc_gain > 1e-10:
        step = step / dc_gain
    dt = 1000.0 / sample_rate_hz
    display = half
    for i in range(half):
        if i * dt > STEP_RESPONSE_MAX_MS:
            display = i
            break
    time_ms = np.arange(display, dtype=float) * dt
    response = step[:display].copy()
    overshoot, rise, settle = _step_metrics(time_ms, response)
    return StepResponse(time_ms, response, overshoot, rise, settle)


def compute_spectrogram(
    signal: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
    window_size: int = 256,
    overlap: float = 0.75,
) -> Spectrogram:
    """``computeSpectrogram``: Hann-windowed STFT power ``10*log10(|X|^2 + 1e-20)`` dB (absolute scale)."""
    x = np.asarray(signal, dtype=np.float64)
    n = int(x.size)
    if n < 4:
        z = np.zeros(0)
        return Spectrogram(z, z, np.zeros((0, 0)), 0, 0)
    window_size = min(int(window_size), n)
    hop = max(1, js_round(window_size * (1.0 - overlap)))
    num_segments = max(1, (n - window_size) // hop + 1)
    num_bins = window_size // 2 + 1
    win = hanning_window(window_size)
    freq = np.arange(num_bins, dtype=float) * (sample_rate_hz / window_size)
    time_ms = np.empty(num_segments)
    power = np.empty((num_segments, num_bins))
    for seg in range(num_segments):
        offset = seg * hop
        time_ms[seg] = ((offset + window_size / 2) / sample_rate_hz) * 1000.0
        xk = np.fft.fft(x[offset : offset + window_size] * win)[:num_bins]
        power[seg] = 10.0 * np.log10(xk.real * xk.real + xk.imag * xk.imag + 1e-20)
    return Spectrogram(time_ms, freq, power, num_segments, num_bins)


def open_loop_response(tf: TransferFunction) -> OpenLoopResponse:
    """``openLoopResponse``: L = T / (1 - T) from the first bin >= 2 Hz, coherence >= 0.5, unwrapped."""
    f = tf.frequencies
    n = f.shape[0]
    magnitude = np.full(n, np.nan)
    phase = np.full(n, np.nan)
    start = 0
    for k in range(1, n):
        if f[k] >= MIN_OPEN_LOOP_HZ:
            start = k
            break
    offset = 0.0
    previous: float | None = None
    for k in range(start, n):
        if tf.coherence[k] < CROSSOVER_COHERENCE_MIN:
            continue
        a = float(tf.h_real[k])
        b = float(tf.h_imag[k])
        denom = (1.0 - a) * (1.0 - a) + b * b
        if math.isnan(denom) or denom <= 1e-12:
            continue
        real = (a - a * a - b * b) / denom
        imag = b / denom
        magnitude[k] = math.hypot(real, imag)
        raw = math.atan2(imag, real) * (180.0 / math.pi)
        if previous is not None:
            delta = raw - previous
            if delta > 180:
                offset -= 360.0
            elif delta < -180:
                offset += 360.0
        phase[k] = raw + offset
        previous = raw
    return OpenLoopResponse(magnitude, phase, start)


def transfer_function_to_dict(tf: TransferFunction) -> dict[str, Any]:
    return {
        "segment_size": tf.segment_size,
        "num_segments": tf.num_segments,
        "sample_rate_hz": tf.sample_rate_hz,
        "frequencies_hz": tf.frequencies.tolist(),
        "h_real": tf.h_real.tolist(),
        "h_imag": tf.h_imag.tolist(),
        "magnitude_db": [None if not np.isfinite(v) else float(v) for v in tf.magnitude_db],
        "phase_deg": tf.phase_deg.tolist(),
        "coherence": tf.coherence.tolist(),
    }


__all__ = [
    "CROSSOVER_COHERENCE_MIN",
    "MIN_OPEN_LOOP_HZ",
    "OpenLoopResponse",
    "Sensitivity",
    "Spectrogram",
    "StepResponse",
    "TransferFunction",
    "WelchSpectra",
    "choose_segment_size",
    "complex_fft",
    "compute_sensitivity",
    "compute_spectrogram",
    "compute_step_response",
    "hanning_window",
    "js_round",
    "open_loop_response",
    "transfer_function_from_spectra",
    "transfer_function_to_dict",
    "welch_spectra",
    "welch_transfer_function",
]
