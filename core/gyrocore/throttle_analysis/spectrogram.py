"""Throttle-indexed spectrogram — contiguous runs only (FPVPIDlab policy)."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from gyrocore.filter_evidence.constants import FFT_WINDOW_SIZE as FE_FFT_WINDOW
from gyrocore.filter_evidence.noise import analyze_axis_noise
from gyrocore.filter_evidence.segments import normalize_throttle

from .constants import DEFAULT_NUM_BANDS, MIN_CONTIGUOUS_RUN, MIN_SAMPLES_PER_BAND
from .models import ThrottleBandSpectrum, ThrottleSpectrogramResult


def bin_by_throttle(throttle_values: Sequence[float] | np.ndarray, num_bands: int) -> list[list[int]]:
    thr = normalize_throttle(throttle_values)
    bins: list[list[int]] = [[] for _ in range(num_bands)]
    for i, t in enumerate(thr):
        band = int(np.floor(float(t) * num_bands))
        if band >= num_bands:
            band = num_bands - 1
        if band < 0:
            band = 0
        bins[band].append(i)
    return bins


def find_contiguous_runs(indices: Sequence[int], min_length: int) -> list[tuple[int, int]]:
    """Return [start, end) ranges in original sample space, longest first."""
    if not indices:
        return []
    runs: list[tuple[int, int]] = []
    run_start = 0
    for i in range(1, len(indices) + 1):
        if i == len(indices) or indices[i] != indices[i - 1] + 1:
            if i - run_start >= min_length:
                runs.append((indices[run_start], indices[i - 1] + 1))
            run_start = i
    runs.sort(key=lambda r: r[1] - r[0], reverse=True)
    return runs


def _prev_power_of_2(n: int) -> int:
    if n < 1:
        return 1
    p = 1
    while p * 2 <= n:
        p <<= 1
    return p


def compute_throttle_spectrogram(
    throttle: Sequence[float] | np.ndarray,
    gyro_axes: Sequence[Sequence[float] | np.ndarray],
    sample_rate_hz: float,
    *,
    num_bands: int = DEFAULT_NUM_BANDS,
) -> ThrottleSpectrogramResult:
    warnings: list[str] = []
    thr = normalize_throttle(throttle)
    if thr.size == 0 or sample_rate_hz <= 0:
        return ThrottleSpectrogramResult([], num_bands, MIN_SAMPLES_PER_BAND, 0, warnings=["no_throttle"])

    axes = [np.asarray(a, dtype=float).reshape(-1) for a in gyro_axes[:3]]
    while len(axes) < 3:
        axes.append(np.zeros_like(thr))
    n = int(min(thr.size, *(a.size for a in axes)))
    thr = thr[:n]
    axes = [a[:n] for a in axes]

    index_bins = bin_by_throttle(thr, num_bands)
    bands: list[ThrottleBandSpectrum] = []
    bands_with_data = 0
    band_width = 1.0 / num_bands

    for b in range(num_bands):
        tmin = round(b * band_width, 2)
        tmax = round((b + 1) * band_width, 2)
        indices = index_bins[b]
        band = ThrottleBandSpectrum(
            throttle_min=tmin,
            throttle_max=tmax,
            sample_count=len(indices),
            usable=False,
        )
        runs = (
            find_contiguous_runs(indices, MIN_CONTIGUOUS_RUN)
            if len(indices) >= MIN_SAMPLES_PER_BAND
            else []
        )
        if not runs and len(indices) >= MIN_SAMPLES_PER_BAND:
            warnings.append(f"band_{b}_discontinuous_runs")
        if runs:
            longest = runs[0][1] - runs[0][0]
            window_size = min(FE_FFT_WINDOW, _prev_power_of_2(longest))
            noise_floors: list[float | None] = []
            peaks: list[dict] = []
            roll_spectrum: dict = {}
            for axis_i, series in enumerate(axes):
                # Weighted average of per-run spectra via noise floors / peaks on longest runs
                floors = []
                for start, end in runs:
                    sl = series[start:end]
                    if sl.size < window_size:
                        continue
                    ar = analyze_axis_noise(sl, sample_rate_hz)
                    if ar["noise_floor_db"] is not None:
                        floors.append(ar["noise_floor_db"])
                    if axis_i == 0 and ar["frequencies_hz"].size:
                        roll_spectrum = {
                            "frequencies_hz": ar["frequencies_hz"].tolist()[::4],
                            "magnitudes_db": ar["magnitudes_db"].tolist()[::4],
                        }
                        peaks = [
                            {
                                "frequency_hz": p.frequency_hz,
                                "magnitude_db": p.magnitude_db,
                                "type": p.peak_type,
                            }
                            for p in ar["peaks"][:5]
                        ]
                noise_floors.append(float(np.mean(floors)) if floors else None)
            band.noise_floor_db = noise_floors
            band.peaks = peaks
            band.spectrum = roll_spectrum
            band.usable = any(f is not None for f in noise_floors)
            if band.usable:
                bands_with_data += 1
        bands.append(band)

    return ThrottleSpectrogramResult(
        bands=bands,
        num_bands=num_bands,
        min_samples_per_band=MIN_SAMPLES_PER_BAND,
        bands_with_data=bands_with_data,
        warnings=list(dict.fromkeys(warnings)),
    )


def band_noise_for_filter_evidence(spec: ThrottleSpectrogramResult) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    for band in spec.bands:
        if not band.usable or len(band.noise_floor_db) < 2:
            continue
        r, p = band.noise_floor_db[0], band.noise_floor_db[1]
        if r is None or p is None:
            continue
        out.append(
            {
                "throttle_mid": (band.throttle_min + band.throttle_max) / 2.0,
                "noise_floor_db": (r + p) / 2.0,
            }
        )
    return out
