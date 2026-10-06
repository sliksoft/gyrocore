"""
Minimal CHIRP system-identification math (WU6).

Ports the core transfer-function path from Betaflight Configurator
``spectral_analysis.ts`` sufficiently for numeric parity of:

- Hanning window
- Welch cross-spectral transfer function H = Sxy / Sxx
- magnitude (dB), phase (deg), coherence

Uses ``numpy.fft.rfft`` instead of the vendored ``ComplexFFT`` class.
Absolute spectral densities may differ by a global FFT scale factor; that
factor cancels in H and in coherence, which are the quantities CHIRP uses.

Full Autotune gain recommendation / open-loop shaping remains deferred (WU7).

Upstream sources (immutable under ``third_party/betaflight/configurator/``):

- ``src/js/blackbox/spectral_analysis.ts`` — ``hanningWindow``,
  ``welchTransferFunction``, ``accumulateSpectra``, ``buildTransferFunction``
- ``src/js/blackbox/fft.ts`` — ``ComplexFFT`` (not ported; scale cancels)
- ``src/composables/useAutotune.ts`` — orchestration / sample-rate consumer
- ``src/js/blackbox/chirp_bbl_parser.ts`` — excitation segment extraction
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


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


def hanning_window(size: int) -> np.ndarray:
    """
    Exact upstream ``hanningWindow``::

        w[i] = 0.5 * (1 - cos(2*pi*i / (size - 1)))
    """
    if size < 2:
        raise ValueError("Hanning window size must be >= 2")
    i = np.arange(size, dtype=float)
    return 0.5 * (1.0 - np.cos((2.0 * np.pi * i) / (size - 1)))


def _next_pow2(n: int) -> int:
    if n <= 1:
        return 1
    return 1 << int(np.ceil(np.log2(n)))


def _clamp_segment_size(segment_size: int, n: int) -> int:
    if segment_size <= n:
        return segment_size
    fit = _next_pow2(n)
    if fit > n:
        fit >>= 1
    return max(fit, 4)


def welch_transfer_function(
    input_signal: Sequence[float] | np.ndarray,
    output_signal: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
    segment_size: int = 1024,
    overlap: float = 0.5,
) -> TransferFunction:
    """
    Closed-loop TF via Welch cross-spectra (upstream ``welchTransferFunction``).

    H(f) = Sxy / Sxx with magnitude in dB, phase in degrees, magnitude-squared
    coherence |Sxy|^2 / (Sxx * Syy).
    """
    x = np.asarray(input_signal, dtype=float)
    y = np.asarray(output_signal, dtype=float)
    if x.shape != y.shape:
        raise ValueError("Input and output arrays must be the same length")
    n = int(x.size)
    if n < 4:
        raise ValueError("Need at least 4 samples to compute a transfer function")
    if sample_rate_hz <= 0 or not np.isfinite(sample_rate_hz):
        raise ValueError("sample_rate_hz must be finite and > 0")

    segment_size = _clamp_segment_size(int(segment_size), n)
    hop_size = max(1, int(round(segment_size * (1.0 - overlap))))
    num_segments = max(1, int(np.floor((n - segment_size) / hop_size)) + 1)
    num_bins = segment_size // 2 + 1
    window = hanning_window(segment_size)

    sxx = np.zeros(num_bins, dtype=float)
    syy = np.zeros(num_bins, dtype=float)
    sxy_re = np.zeros(num_bins, dtype=float)
    sxy_im = np.zeros(num_bins, dtype=float)

    for seg in range(num_segments):
        offset = seg * hop_size
        xw = x[offset : offset + segment_size] * window
        yw = y[offset : offset + segment_size] * window
        xk = np.fft.rfft(xw, n=segment_size)
        yk = np.fft.rfft(yw, n=segment_size)
        sxx += (xk.real * xk.real) + (xk.imag * xk.imag)
        syy += (yk.real * yk.real) + (yk.imag * yk.imag)
        # Sxy = conj(X) * Y
        sxy_re += xk.real * yk.real + xk.imag * yk.imag
        sxy_im += -xk.imag * yk.real + xk.real * yk.imag

    freq_bin_width = sample_rate_hz / segment_size
    frequencies = np.arange(num_bins, dtype=float) * freq_bin_width
    magnitude = np.empty(num_bins, dtype=float)
    phase = np.empty(num_bins, dtype=float)
    coherence = np.empty(num_bins, dtype=float)
    h_real = np.empty(num_bins, dtype=float)
    h_imag = np.empty(num_bins, dtype=float)

    for k in range(num_bins):
        if sxx[k] < 1e-20:
            magnitude[k] = float("-inf")
            phase[k] = 0.0
            coherence[k] = 0.0
            h_real[k] = 0.0
            h_imag[k] = 0.0
            continue
        h_re = sxy_re[k] / sxx[k]
        h_im = sxy_im[k] / sxx[k]
        h_real[k] = h_re
        h_imag[k] = h_im
        magnitude[k] = 20.0 * np.log10(np.hypot(h_re, h_im))
        phase[k] = float(np.arctan2(h_im, h_re) * (180.0 / np.pi))
        sxy_mag_sq = sxy_re[k] * sxy_re[k] + sxy_im[k] * sxy_im[k]
        denom = sxx[k] * syy[k]
        coherence[k] = float(sxy_mag_sq / denom) if denom > 1e-30 else 0.0

    return TransferFunction(
        frequencies=frequencies,
        magnitude_db=magnitude,
        phase_deg=phase,
        coherence=coherence,
        h_real=h_real,
        h_imag=h_imag,
        num_segments=num_segments,
        segment_size=segment_size,
        sample_rate_hz=float(sample_rate_hz),
    )


__all__ = [
    "TransferFunction",
    "hanning_window",
    "welch_transfer_function",
]
