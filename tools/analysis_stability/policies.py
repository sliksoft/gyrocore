"""Deterministic experimental policies, preserving source time and identity.

B intentionally interpolates across gaps to expose why resampling alone is
insufficient. D rejects every fixed window touching a gap; it emits normalized
PSD and transient evidence, not a substitute for legacy amplitude thresholds.
"""

from __future__ import annotations

import hashlib
from typing import Final, NotRequired, TypedDict

import numpy as np
from numpy.typing import NDArray
from scipy.signal import find_peaks, periodogram

CAP: Final = 20_000
WINDOW: Final = 2048


class Sample(TypedDict):
    t: int
    gx: float
    gy: float
    gz: float
    throttle: float | None
    motors: list[float | None]
    source_index: NotRequired[int]


class WindowResult(TypedDict):
    available: bool
    windows: int
    rejected_windows: int
    bin_hz: float
    peaks_hz: list[float]
    peaks_psd: list[float]
    transient_peaks_hz: list[float]
    transient_peak_windows: list[int]
    band_power: list[float]
    spectrum_digest: str


def current_indices(n: int) -> list[int]:
    """Exactly reproduce production round-based selection (not replay's floor)."""
    if n <= CAP:
        return list(range(n))
    return [round(i * (n - 1) / (CAP - 1)) for i in range(CAP)]


def cadence_us(samples: list[Sample]) -> float:
    """Estimate native period; retain the Core's median-positive-step convention."""
    dt = np.diff([s["t"] for s in samples])
    return float(np.median(dt[dt > 0]))


def select_current(samples: list[Sample]) -> list[Sample]:
    return [samples[i] for i in current_indices(len(samples))]


def resample_grid(samples: list[Sample]) -> list[Sample]:
    """Native-rate timestamp grid; continuous columns only, no categorical data.

    Diagnostic B deliberately has no missing-data protection or antialias
    stage. It is not a valid CHIRP/PID input representation.
    """
    dt = cadence_us(samples)
    t = np.asarray([s["t"] for s in samples], dtype=float)
    grid = t[0] + np.arange(int((t[-1] - t[0]) // dt) + 1) * dt
    values = {k: np.interp(grid, t, np.asarray([s[k] for s in samples], dtype=float)) for k in ("gx", "gy", "gz", "throttle")}
    motors = [np.interp(grid, t, np.asarray([s["motors"][j] for s in samples], dtype=float)) for j in range(4)]
    nearest = np.clip(np.searchsorted(t, grid), 0, len(samples) - 1)
    return [Sample(**{**samples[int(nearest[i])], "t": int(v), "gx": float(values["gx"][i]), "gy": float(values["gy"][i]),
                   "gz": float(values["gz"][i]), "throttle": float(values["throttle"][i]) if np.isfinite(values["throttle"][i]) else None,
                   "motors": [float(m[i]) if np.isfinite(m[i]) else None for m in motors]}) for i, v in enumerate(grid)]


def contiguous_window(samples: list[Sample]) -> list[Sample]:
    """First contiguous run, at most 20k; restart after missing/reset time."""
    dt = cadence_us(samples)
    t = np.asarray([s["t"] for s in samples], dtype=float)
    steps = np.diff(t)
    breaks = np.flatnonzero((steps <= 0) | (steps > 1.5 * dt)) + 1
    bounds = [0, *breaks.tolist(), len(samples)]
    for start, end in zip(bounds, bounds[1:]):
        if end - start >= WINDOW:
            return samples[start:min(end, start + CAP)]
    return samples[:min(len(samples), CAP)]


def fixed_window_psd(samples: list[Sample]) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], int]:
    """Absolute timestamp-anchored Hann windows, 50% overlap, no gap bridging.

    Windows span 1.024 seconds at native cadence, anchored at the first source
    timestamp. In-window interpolation handles jitter, never missing intervals
    above 1.5 periods or resets. PSD is one-sided (deg/s)^2/Hz, DC removed.
    Empty coverage is unavailable, not a zero spectrum.
    """
    dt = cadence_us(samples)
    window_size = max(32, round(1_024_000 / dt))
    t = np.asarray([s["t"] for s in samples], dtype=float)
    if np.any(np.diff(t) <= 0):
        return np.array([]), np.array([]), np.empty((0, 0)), 1
    xyz = np.asarray([[s["gx"], s["gy"], s["gz"]] for s in samples])
    powers = []
    rejected = 0
    frequencies = np.array([])
    count = int((t[-1] - t[0]) // dt) + 1
    for start in range(0, count - window_size + 1, window_size // 2):
        grid = t[0] + (start + np.arange(window_size)) * dt
        left = max(0, int(np.searchsorted(t, grid[0], side="right")) - 1)
        right = min(len(t), int(np.searchsorted(t, grid[-1], side="left")) + 1)
        if np.any(np.diff(t[left:right]) > 1.5 * dt):
            rejected += 1
            continue
        axes = np.array([np.interp(grid, t[left:right], xyz[left:right, j]) for j in range(3)])
        frequencies, psd = periodogram(axes, fs=1e6 / dt, window="hann", detrend="constant", scaling="density", axis=1)
        powers.append(np.mean(psd, axis=0))
    if not powers:
        return frequencies, np.array([]), np.empty((0, 0)), rejected
    stack = np.asarray(powers)
    return frequencies, np.mean(stack, axis=0), stack, rejected


def window_summary(samples: list[Sample]) -> WindowResult:
    """Diagnostic mean PSD plus per-window peak union so bursts remain visible.

    Peak threshold is the existing mean+1.8 sigma form, on PSD rather than raw
    magnitude. It is an experiment, not a calibrated resonance classifier.
    """
    f, mean, stack, rejected = fixed_window_psd(samples)
    band = (f >= 30) & (f <= 500)
    def peaks(psd: NDArray[np.float64]) -> list[int]:
        if psd.size == 0:
            return []
        selected = np.flatnonzero(band)
        threshold = float(np.mean(psd[band]) + 1.8 * np.std(psd[band]))
        found, _ = find_peaks(psd[selected], height=threshold)
        return selected[found].tolist()
    dominant = peaks(mean)
    bins: dict[int, int] = {}
    for psd in stack:
        for index in peaks(psd):
            bins[index] = bins.get(index, 0) + 1
    widths = float(f[1] - f[0]) if f.size > 1 else 0.0
    return WindowResult(available=bool(len(stack)), windows=len(stack), rejected_windows=rejected, bin_hz=widths,
        peaks_hz=[float(f[i]) for i in dominant], peaks_psd=[float(mean[i]) for i in dominant],
        transient_peaks_hz=[float(f[i]) for i in sorted(bins)],
        transient_peak_windows=[bins[i] for i in sorted(bins)],
        band_power=[float(np.sum(mean[(f >= lo) & (f < hi)]) * widths)
                    for lo, hi in ((0, 100), (100, 300), (300, float("inf")))] if mean.size else [],
        spectrum_digest=hashlib.sha256(mean.tobytes()).hexdigest())


def perturbations(samples: list[Sample]) -> list[tuple[str, list[Sample]]]:
    """Remove rows only; keep every surviving time/value/source identity intact."""
    cases = [("complete", samples)]
    for percent in (0.05, 0.10, 0.50):
        size = max(1, round(len(samples) * percent / 100))
        cases.append((f"tail_remove_{percent:.2f}pct", samples[:-size]))
        # Add restores the same valid tail to its shortened counterpart. Never
        # invent or repeat real flight data to manufacture an "unchanged" tail.
        cases.append((f"tail_add_{percent:.2f}pct", samples))
        for position in (0.2, 0.5, 0.8):
            start = int(len(samples) * position)
            cases.append((f"gap_{position:.1f}_{percent:.2f}pct", samples[:start] + samples[start + size:]))
    return cases


def synthetic_samples(n: int = 100_000, *, burst: bool = False, shifted: bool = False) -> list[Sample]:
    """2kHz stationary physical tones; optional late short 481Hz event."""
    result = []
    for i in range(n):
        time = i / 2000
        value = 10 * np.sin(2 * np.pi * (83.8 if shifted else 73.8) * time) + 2 * np.sin(2 * np.pi * 180 * time)
        if burst and 35 <= time < 35.25:
            value += 20 * np.sin(2 * np.pi * 481 * time)
        result.append(Sample(t=i * 500, gx=float(value), gy=float(value * .7), gz=float(value * .4),
                             throttle=.5, motors=[.5] * 4, source_index=i))
    return result


def noise_samples(n: int = 40_000) -> list[Sample]:
    """Seeded white gyro noise with no injected narrow resonance."""
    values = np.random.default_rng(481).normal(0, 2, (n, 3))
    return [Sample(t=i * 500, gx=float(v[0]), gy=float(v[1]), gz=float(v[2]),
                   throttle=.5, motors=[.5] * 4, source_index=i) for i, v in enumerate(values)]
