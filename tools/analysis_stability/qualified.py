from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable

import numpy as np
from numpy.typing import NDArray
from scipy.signal import find_peaks

from tools.analysis_stability.policies import Sample

WINDOW_SAMPLES: Final = 2_048
HOP_SAMPLES: Final = 1_024
CALIBRATION_SAMPLES: Final = 4_096
MAX_GAP_PERIODS: Final = 1.5
MIN_FREQ_HZ: Final = 30.0
MAX_FREQ_HZ: Final = 500.0
FLANK_INNER_BINS: Final = 3
FLANK_OUTER_BINS: Final = 20
MIN_CONTRAST_DB: Final = 6.0


@dataclass(frozen=True, slots=True)
class SpectralPeak:
    frequency_hz: float
    contrast_db: float
    excess_power: float
    supporting_windows: int


@dataclass(frozen=True, slots=True)
class SpectralEvidence:
    nominal_period_us: float
    bin_hz: float
    windows: int
    rejected_windows: int
    observed_seconds: float
    peaks: tuple[SpectralPeak, ...]
    event_peaks: tuple[SpectralPeak, ...]


def nominal_period_us(samples: list[Sample]) -> float:
    times = np.asarray([sample["t"] for sample in samples[:CALIBRATION_SAMPLES]], dtype=float)
    intervals = np.diff(times)
    positive = intervals[intervals > 0]
    if positive.size == 0:
        return 0.0
    period = float(np.median(positive))
    contiguous = positive[positive <= MAX_GAP_PERIODS * period]
    return float(np.median(contiguous)) if contiguous.size else 0.0


def _epochs(samples: list[Sample]) -> Iterable[list[Sample]]:
    current: list[Sample] = []
    last_time: int | None = None
    for sample in samples:
        if last_time is not None and sample["t"] <= last_time:
            if current:
                yield current
            current = []
        current.append(sample)
        last_time = sample["t"]
    if current:
        yield current


def _window_psd(
    times: NDArray[np.float64],
    values: NDArray[np.float64],
    start_us: float,
    period_us: float,
) -> tuple[NDArray[np.float64], NDArray[np.float64]] | None:
    grid = start_us + np.arange(WINDOW_SAMPLES) * period_us
    left = max(0, int(np.searchsorted(times, grid[0], side="right")) - 1)
    right = min(times.size, int(np.searchsorted(times, grid[-1], side="left")) + 1)
    if right - left < 2 or np.any(np.diff(times[left:right]) > MAX_GAP_PERIODS * period_us):
        return None
    axes = np.asarray([np.interp(grid, times[left:right], values[left:right, axis]) for axis in range(3)])
    axes -= np.mean(axes, axis=1, keepdims=True)
    taper = 0.5 - 0.5 * np.cos((2 * np.pi * np.arange(WINDOW_SAMPLES)) / WINDOW_SAMPLES)
    scale = (1e6 / period_us) * float(np.sum(taper * taper))
    transformed = np.fft.rfft(axes * taper, axis=1)
    psd = (np.abs(transformed) ** 2) / scale
    if psd.shape[1] > 2:
        psd[:, 1:-1] *= 2.0
    frequencies = np.fft.rfftfreq(WINDOW_SAMPLES, d=period_us / 1e6)
    return frequencies, psd


def _local_peaks(frequencies: NDArray[np.float64], psd: NDArray[np.float64]) -> tuple[SpectralPeak, ...]:
    combined = np.max(psd, axis=0)
    candidates, _ = find_peaks(combined)
    accepted: list[SpectralPeak] = []
    for index in candidates:
        if not MIN_FREQ_HZ <= frequencies[index] <= MAX_FREQ_HZ:
            continue
        left = combined[max(0, index - FLANK_OUTER_BINS) : max(0, index - FLANK_INNER_BINS)]
        right = combined[index + FLANK_INNER_BINS + 1 : index + FLANK_OUTER_BINS + 1]
        flanks = np.concatenate((left, right))
        if flanks.size < 2:
            continue
        background = float(np.median(flanks))
        peak_power = float(combined[index])
        contrast_db = float(10.0 * np.log10(peak_power / max(background, np.finfo(float).tiny)))
        if contrast_db >= MIN_CONTRAST_DB:
            accepted.append(SpectralPeak(float(frequencies[index]), contrast_db, max(0.0, peak_power - background), 1))
    return tuple(accepted)


def _merge(peaks_by_window: Iterable[tuple[SpectralPeak, ...]], bin_hz: float) -> tuple[SpectralPeak, ...]:
    bins: dict[int, list[SpectralPeak]] = {}
    for peaks in peaks_by_window:
        for peak in peaks:
            key = int(round(peak.frequency_hz / bin_hz))
            bins.setdefault(key, []).append(peak)
    return tuple(
        SpectralPeak(
            frequency_hz=float(np.mean([peak.frequency_hz for peak in group])),
            contrast_db=float(np.mean([peak.contrast_db for peak in group])),
            excess_power=float(np.mean([peak.excess_power for peak in group])),
            supporting_windows=len(group),
        )
        for _, group in sorted(bins.items())
    )


def qualify(samples: list[Sample]) -> SpectralEvidence:
    period_us = nominal_period_us(samples)
    if period_us <= 0:
        return SpectralEvidence(0.0, 0.0, 0, 0, 0.0, (), ())
    means: list[NDArray[np.float64]] = []
    local: list[tuple[SpectralPeak, ...]] = []
    rejected = 0
    observed_seconds = 0.0
    frequencies = np.array([], dtype=float)
    for epoch in _epochs(samples):
        times = np.asarray([row["t"] for row in epoch], dtype=float)
        values = np.asarray([[row["gx"], row["gy"], row["gz"]] for row in epoch], dtype=float)
        epoch_end = epoch[-1]["t"]
        anchor = float(epoch[0]["t"])
        while anchor + (WINDOW_SAMPLES - 1) * period_us <= epoch_end:
            result = _window_psd(times, values, anchor, period_us)
            if result is None:
                rejected += 1
            else:
                frequencies, axes = result
                means.append(np.mean(axes, axis=0))
                local.append(_local_peaks(frequencies, axes))
                observed_seconds += WINDOW_SAMPLES * period_us / 1e6
            anchor += HOP_SAMPLES * period_us
    if not means or frequencies.size < 2:
        return SpectralEvidence(period_us, 0.0, 0, rejected, observed_seconds, (), ())
    bin_hz = float(frequencies[1] - frequencies[0])
    events = _merge(local, bin_hz)
    stationary = tuple(
        SpectralPeak(
            frequency_hz=peak.frequency_hz,
            contrast_db=peak.contrast_db,
            excess_power=peak.excess_power,
            supporting_windows=next(
                (event.supporting_windows for event in events if abs(event.frequency_hz - peak.frequency_hz) <= bin_hz),
                0,
            ),
        )
        for peak in _local_peaks(frequencies, np.asarray([np.mean(means, axis=0)]))
    )
    return SpectralEvidence(period_us, bin_hz, len(means), rejected, observed_seconds, stationary, events)
