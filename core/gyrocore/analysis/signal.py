# GyroCore WU4: adapted from AeroTuner backend/analysis/signal.py
from typing import Dict, Mapping, Sequence

import numpy as np


def time_us_to_seconds(time_us: Sequence[float]) -> np.ndarray:
    """Convert a time array from microseconds to seconds."""
    return np.asarray(time_us, dtype=float) / 1_000_000.0


def compute_sample_rate(time_seconds: Sequence[float]) -> float:
    """
    Estimate sample rate from a time array in seconds.

    Uses the median positive time step to reduce sensitivity to outliers.
    """
    t = np.asarray(time_seconds, dtype=float)
    if t.size < 2:
        return 0.0

    dt = np.diff(t)
    dt = dt[dt > 0]
    if dt.size == 0:
        return 0.0

    dt_median = float(np.median(dt))
    if dt_median <= 0:
        return 0.0

    return 1.0 / dt_median


def remove_dc_offset(signal: Sequence[float]) -> np.ndarray:
    """Subtract mean value from a signal."""
    x = np.asarray(signal, dtype=float)
    if x.size == 0:
        return x
    return x - np.mean(x)


def fft_gx(
    gx_signal: Sequence[float],
    sample_rate_hz: float,
) -> Dict[str, np.ndarray]:
    """
    Compute one-sided FFT for gx.

    Returns:
        {
            "frequencies": np.ndarray,  # Hz
            "amplitude": np.ndarray,    # linear amplitude
        }
    """
    x = np.asarray(gx_signal, dtype=float)
    n = x.size

    if n == 0 or sample_rate_hz <= 0:
        return {"frequencies": np.array([]), "amplitude": np.array([])}

    # Apply a Hann window to reduce spectral leakage.
    window = np.hanning(n)
    x_windowed = x * window

    spectrum = np.fft.rfft(x_windowed)
    frequencies = np.fft.rfftfreq(n, d=1.0 / sample_rate_hz)
    # Compensate by coherent gain so amplitude scale remains comparable.
    coherent_gain = np.mean(window)
    if coherent_gain <= 0:
        amplitude = (2.0 / n) * np.abs(spectrum)
    else:
        amplitude = (2.0 / (n * coherent_gain)) * np.abs(spectrum)

    return {"frequencies": frequencies, "amplitude": amplitude}


def total_signal_energy(amplitude: Sequence[float]) -> float:
    """Compute total spectral energy from amplitude values."""
    a = np.asarray(amplitude, dtype=float)
    if a.size == 0:
        return 0.0
    return float(np.sum(np.square(a)))


def high_frequency_energy(
    frequencies: Sequence[float],
    amplitude: Sequence[float],
    cutoff_hz: float = 120.0,
) -> float:
    """Compute spectral energy above a cutoff frequency."""
    f = np.asarray(frequencies, dtype=float)
    a = np.asarray(amplitude, dtype=float)
    if f.size == 0 or a.size == 0 or f.size != a.size:
        return 0.0

    mask = f >= cutoff_hz
    if not np.any(mask):
        return 0.0

    return float(np.sum(np.square(a[mask])))


def frequency_band_energy(
    frequencies: Sequence[float],
    amplitude: Sequence[float],
    low_hz: float,
    high_hz: float | None = None,
) -> float:
    """Compute spectral energy in [low_hz, high_hz) or [low_hz, +inf)."""
    f = np.asarray(frequencies, dtype=float)
    a = np.asarray(amplitude, dtype=float)
    if f.size == 0 or a.size == 0 or f.size != a.size:
        return 0.0

    if high_hz is None:
        mask = f >= low_hz
    else:
        mask = (f >= low_hz) & (f < high_hz)

    if not np.any(mask):
        return 0.0

    return float(np.sum(np.square(a[mask])))


def dynamic_band_energies(
    frequencies: Sequence[float],
    amplitude: Sequence[float],
) -> Dict[str, float]:
    """
    Compute spectral energy by dynamic bands:
      - low: 0-100 Hz
      - mid: 100-300 Hz
      - high: 300+ Hz
    """
    low = frequency_band_energy(frequencies, amplitude, low_hz=0.0, high_hz=100.0)
    mid = frequency_band_energy(frequencies, amplitude, low_hz=100.0, high_hz=300.0)
    high = frequency_band_energy(frequencies, amplitude, low_hz=300.0, high_hz=None)

    return {"low": low, "mid": mid, "high": high}


def noise_score_from_energy(total_energy: float, hf_energy: float) -> str:
    """
    Map high-frequency energy ratio to a simple noise grade.

    A: very clean, D: very noisy
    """
    if total_energy <= 0:
        return "A"

    ratio = hf_energy / total_energy
    if ratio < 0.15:
        return "A"
    if ratio < 0.30:
        return "B"
    if ratio < 0.50:
        return "C"
    return "D"


def score_noise_from_fft(
    frequencies: Sequence[float],
    amplitude: Sequence[float],
    cutoff_hz: float = 120.0,
) -> Dict[str, float | str]:
    """Convenience helper that returns total/hf energy and A-D score."""
    total_energy = total_signal_energy(amplitude)
    hf_energy = high_frequency_energy(frequencies, amplitude, cutoff_hz=cutoff_hz)
    return {
        "total_energy": total_energy,
        "high_frequency_energy": hf_energy,
        "noise_score": noise_score_from_energy(total_energy, hf_energy),
    }


def score_noise_with_dynamic_bands(
    frequencies: Sequence[float],
    amplitude: Sequence[float],
    cutoff_hz: float = 120.0,
) -> Dict[str, float | str]:
    """
    Return existing noise scoring plus dynamic band energies.

    Existing score logic remains unchanged (cutoff-based).
    """
    base = score_noise_from_fft(frequencies, amplitude, cutoff_hz=cutoff_hz)
    bands = dynamic_band_energies(frequencies, amplitude)
    return {
        **base,
        "band_energy_low": bands["low"],
        "band_energy_mid": bands["mid"],
        "band_energy_high": bands["high"],
    }


def detect_oscillation_peaks(
    frequencies: Sequence[float],
    amplitude: Sequence[float],
    min_freq_hz: float = 20.0,
    threshold_scale: float = 1.5,
    max_peaks: int = 10,
) -> Dict[str, list[float]]:
    """
    Detect dominant oscillation peaks from an FFT spectrum.

    A peak is a local maximum with amplitude above:
      threshold_scale * mean_amplitude
    """
    f = np.asarray(frequencies, dtype=float)
    a = np.asarray(amplitude, dtype=float)
    if f.size < 3 or a.size < 3 or f.size != a.size:
        return {"peak_frequencies": [], "peak_amplitudes": []}

    mean_amp = float(np.mean(a))
    threshold = threshold_scale * mean_amp

    candidates: list[tuple[float, float]] = []
    for i in range(1, len(a) - 1):
        is_local_max = a[i] > a[i - 1] and a[i] > a[i + 1]
        is_strong = a[i] > threshold
        in_band = f[i] >= min_freq_hz
        if is_local_max and is_strong and in_band:
            candidates.append((float(f[i]), float(a[i])))

    # Sort by peak amplitude descending and keep strongest peaks.
    candidates.sort(key=lambda item: item[1], reverse=True)
    if max_peaks > 0:
        candidates = candidates[:max_peaks]

    peak_frequencies = [item[0] for item in candidates]
    peak_amplitudes = [item[1] for item in candidates]
    return {"peak_frequencies": peak_frequencies, "peak_amplitudes": peak_amplitudes}


def analyze_gx_signal(gyro_rows: Sequence[Mapping[str, float]]) -> Dict[str, np.ndarray]:
    """
    End-to-end basic signal analysis for gx from gyro rows.

    Expects each row to contain:
      - "t" in microseconds
      - "gx"
    """
    if not gyro_rows:
        return {"frequencies": np.array([]), "amplitude": np.array([])}

    time_us = [row["t"] for row in gyro_rows]
    gx = [row["gx"] for row in gyro_rows]

    time_seconds = time_us_to_seconds(time_us)
    sample_rate_hz = compute_sample_rate(time_seconds)
    gx_centered = remove_dc_offset(gx)

    return fft_gx(gx_centered, sample_rate_hz)
