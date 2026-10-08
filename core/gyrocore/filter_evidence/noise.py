"""Noise floor / peak detection — FPVPIDlab NoiseAnalyzer logic on GyroCore Welch PSD."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from gyrocore.analysis.spectral_windows import prepare_fft_signal

from .constants import (
    DB_SENTINEL,
    ELECTRICAL_NOISE_MIN_HZ,
    FFT_OVERLAP,
    FFT_WINDOW_SIZE,
    FRAME_RESONANCE_MAX_HZ,
    FRAME_RESONANCE_MIN_HZ,
    FREQUENCY_MAX_HZ,
    FREQUENCY_MIN_HZ,
    NOISE_FLOOR_PERCENTILE,
    NOISE_LEVEL_HIGH_DB,
    NOISE_LEVEL_MEDIUM_DB,
    PEAK_LOCAL_WINDOW_BINS,
    PEAK_MIN_SPACING_HZ,
    PEAK_PROMINENCE_DB,
    POWER_FLOOR,
)
from .models import SpectralPeak

try:
    from scipy import signal as scipy_signal
except Exception:  # pragma: no cover
    scipy_signal = None


def compute_power_spectrum_db(
    values: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
    *,
    window_size: int = FFT_WINDOW_SIZE,
) -> tuple[np.ndarray, np.ndarray]:
    """One-sided Welch PSD in dB using GyroCore prepare_fft_signal + SciPy/NumPy Welch."""
    prepared = prepare_fft_signal(values, sample_rate_hz)
    sig = prepared["signal"]
    fs = float(prepared["sample_rate_hz"] or 0.0)
    if sig.size < 8 or fs <= 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    nperseg = int(min(window_size, sig.size))
    if nperseg < 8:
        return np.array([], dtype=float), np.array([], dtype=float)
    noverlap = int(nperseg * FFT_OVERLAP)
    if scipy_signal is not None:
        freqs, power = scipy_signal.welch(
            sig, fs=fs, nperseg=nperseg, noverlap=noverlap, window="hann", scaling="spectrum"
        )
    else:
        # Same NumPy Welch path as spectral_windows._welch_numpy
        step = max(1, nperseg - noverlap)
        hann = np.hanning(nperseg)
        scale = float(fs * np.sum(hann * hann))
        freqs = np.fft.rfftfreq(nperseg, d=1.0 / fs)
        powers = []
        for start in range(0, sig.size - nperseg + 1, step):
            chunk = sig[start : start + nperseg]
            fft = np.fft.rfft(chunk * hann)
            powers.append((np.abs(fft) ** 2) / max(scale, 1e-12))
        power = np.mean(np.vstack(powers), axis=0)
    with np.errstate(divide="ignore"):
        mag = np.where(power > POWER_FLOOR, 10.0 * np.log10(np.maximum(power, POWER_FLOOR)), DB_SENTINEL)
    mask = (freqs >= FREQUENCY_MIN_HZ) & (freqs <= FREQUENCY_MAX_HZ)
    return np.asarray(freqs[mask], dtype=float), np.asarray(mag[mask], dtype=float)


def estimate_noise_floor(magnitudes_db: np.ndarray) -> float:
    if magnitudes_db.size == 0:
        return DB_SENTINEL
    valid = magnitudes_db[magnitudes_db > DB_SENTINEL]
    if valid.size == 0:
        return DB_SENTINEL
    valid = np.sort(valid)
    idx = int(np.floor(valid.size * NOISE_FLOOR_PERCENTILE))
    return float(valid[max(0, min(idx, valid.size - 1))])


def _local_noise_floor(magnitudes: np.ndarray, bin_index: int, window_bins: int = PEAK_LOCAL_WINDOW_BINS) -> float:
    start = max(0, bin_index - window_bins)
    end = min(int(magnitudes.size), bin_index + window_bins + 1)
    values = [float(magnitudes[i]) for i in range(start, end) if abs(i - bin_index) > 3]
    if not values:
        return float(magnitudes[bin_index])
    values.sort()
    return values[len(values) // 2]


def detect_peaks(
    freqs: np.ndarray,
    magnitudes_db: np.ndarray,
    *,
    prominence_db: float = PEAK_PROMINENCE_DB,
    min_spacing_hz: float = PEAK_MIN_SPACING_HZ,
) -> list[SpectralPeak]:
    if freqs.size < 3:
        return []
    candidates: list[tuple[int, float, float]] = []
    for i in range(1, int(freqs.size) - 1):
        m = float(magnitudes_db[i])
        if m <= DB_SENTINEL:
            continue
        if m < float(magnitudes_db[i - 1]) or m < float(magnitudes_db[i + 1]):
            continue
        local = _local_noise_floor(magnitudes_db, i)
        prom = m - local
        if prom >= prominence_db:
            candidates.append((i, m, prom))
    candidates.sort(key=lambda c: c[1], reverse=True)
    kept: list[tuple[int, float, float]] = []
    for cand in candidates:
        f = float(freqs[cand[0]])
        if any(abs(f - float(freqs[k[0]])) < min_spacing_hz for k in kept):
            continue
        kept.append(cand)
    peaks: list[SpectralPeak] = []
    for idx, mag, prom in kept:
        f = float(freqs[idx])
        if FRAME_RESONANCE_MIN_HZ <= f <= FRAME_RESONANCE_MAX_HZ:
            ptype = "frame_resonance"
        elif f >= ELECTRICAL_NOISE_MIN_HZ:
            ptype = "electrical"
        else:
            ptype = "unknown"
        peaks.append(
            SpectralPeak(
                frequency_hz=round(f, 3),
                magnitude_db=round(mag, 3),
                prominence_db=round(prom, 3),
                peak_type=ptype,
            )
        )
    return peaks


def classify_noise_level(noise_floor_db: float) -> str:
    if noise_floor_db <= DB_SENTINEL + 1:
        return "unknown"
    if noise_floor_db >= NOISE_LEVEL_HIGH_DB:
        return "high"
    if noise_floor_db >= NOISE_LEVEL_MEDIUM_DB:
        return "medium"
    return "low"


def analyze_axis_noise(
    values: Sequence[float] | np.ndarray,
    sample_rate_hz: float,
) -> dict:
    freqs, mag = compute_power_spectrum_db(values, sample_rate_hz)
    floor = estimate_noise_floor(mag)
    peaks = detect_peaks(freqs, mag)
    return {
        "noise_floor_db": round(floor, 3) if floor > DB_SENTINEL else None,
        "level": classify_noise_level(floor),
        "peaks": peaks,
        "frequencies_hz": freqs,
        "magnitudes_db": mag,
    }
