# GyroCore WU4: adapted from AeroTuner backend/analysis/spectral_windows.py
"""Compact spectral reliability helpers for Filter Intelligence.

These helpers provide supporting evidence only. They do not replace the
existing FFT/resonance pipeline and they do not simulate Betaflight filters.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

try:  # SciPy is already a backend dependency; keep a NumPy fallback for safety.
    from scipy import signal as scipy_signal
except Exception:  # pragma: no cover - exercised only when SciPy is unavailable.
    scipy_signal = None


Quality = str
Confidence = str

_DEFAULT_THROTTLE_BANDS: dict[str, tuple[float, float]] = {
    "low": (0.0, 0.35),
    "mid": (0.35, 0.70),
    "high": (0.70, 1.0),
}


def _finite_float_array(values: Any) -> np.ndarray:
    if values is None:
        return np.array([], dtype=float)
    try:
        arr = np.asarray(values, dtype=float).reshape(-1)
    except (TypeError, ValueError):
        return np.array([], dtype=float)
    if arr.size == 0:
        return np.array([], dtype=float)
    return arr[np.isfinite(arr)]


def _quality_from_count(sample_count: int, warnings: list[str], *, decimated: bool = False) -> Quality:
    if sample_count < 128:
        warnings.append("High-frequency spectral confidence is limited by sample count or subsampling.")
        return "low"
    if sample_count < 512:
        warnings.append("Spectral confidence is limited by short sample windows.")
        return "medium"
    if decimated:
        warnings.append("High-frequency spectral confidence is limited by decimated spectral evidence.")
        return "medium"
    return "high"


def _confidence_from_relative_power(relative_power: float, quality: Quality) -> Confidence:
    if quality == "low":
        return "low"
    if relative_power >= 0.5 and quality == "high":
        return "high"
    if relative_power >= 0.18:
        return "medium"
    return "low"


def _dedupe_warnings(warnings: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(w) for w in warnings if isinstance(w, str) and w.strip()))


def _decimate_with_antialias(signal: np.ndarray, factor: int) -> np.ndarray:
    if factor <= 1 or signal.size == 0:
        return signal
    if scipy_signal is not None:
        try:
            return np.asarray(scipy_signal.decimate(signal, factor, zero_phase=True), dtype=float)
        except (TypeError, ValueError, np.linalg.LinAlgError):
            pass

    tap_count = min(101, max(15, factor * 16 + 1))
    if tap_count % 2 == 0:
        tap_count += 1
    if signal.size < tap_count:
        tap_count = int(signal.size) if int(signal.size) % 2 == 1 else int(signal.size) - 1
    if tap_count < 3:
        return signal[::factor]

    n = np.arange(tap_count, dtype=float) - float(tap_count - 1) / 2.0
    cutoff = 0.4 / float(factor)
    taps = 2.0 * cutoff * np.sinc(2.0 * cutoff * n)
    taps *= np.hamming(tap_count)
    tap_sum = float(np.sum(taps))
    if abs(tap_sum) <= 1e-12:
        return signal[::factor]
    filtered = np.convolve(signal, taps / tap_sum, mode="same")
    return np.asarray(filtered[::factor], dtype=float)


def prepare_fft_signal(
    axis_data: Any,
    sample_rate_hz: float,
    target_rate_hz: float | None = None,
) -> dict[str, Any]:
    """Normalize one numeric axis for spectral analysis with explicit quality metadata."""
    warnings: list[str] = []
    try:
        fs = float(sample_rate_hz)
    except (TypeError, ValueError):
        fs = 0.0
    if not math.isfinite(fs) or fs <= 0:
        fs = 0.0
        warnings.append("Invalid sample rate; spectral evidence is limited.")

    try:
        arr_raw = np.asarray(axis_data if axis_data is not None else [], dtype=float).reshape(-1)
    except (TypeError, ValueError):
        arr_raw = np.array([], dtype=float)
        warnings.append("Axis data was not numeric; spectral evidence is limited.")
    finite_mask = np.isfinite(arr_raw)
    removed = int(arr_raw.size - int(np.count_nonzero(finite_mask)))
    arr = arr_raw[finite_mask]
    if removed > 0:
        warnings.append("NaN or infinite samples were removed before spectral analysis.")

    if arr.size:
        arr = arr - float(np.mean(arr))
        if arr.size >= 2:
            x = np.arange(arr.size, dtype=float)
            try:
                slope, intercept = np.polyfit(x, arr, 1)
                arr = arr - (slope * x + intercept)
            except (TypeError, ValueError, np.linalg.LinAlgError):
                warnings.append("Simple detrend failed; DC offset removal was still applied.")

    method = "finite_detrend"
    decimated = False
    if target_rate_hz is not None and fs > 0:
        try:
            target = float(target_rate_hz)
        except (TypeError, ValueError):
            target = 0.0
        if math.isfinite(target) and target > 0 and target < fs and arr.size:
            factor = max(1, int(math.floor(fs / target)))
            if factor > 1:
                arr = _decimate_with_antialias(arr, factor)
                fs = fs / factor
                decimated = True
                method = f"finite_detrend_decimate_{factor}"

    quality = _quality_from_count(int(arr.size), warnings, decimated=decimated)
    return {
        "signal": np.asarray(arr, dtype=float),
        "sample_rate_hz": float(fs) if fs > 0 else 0.0,
        "sample_count": int(arr.size),
        "quality": quality,
        "warnings": _dedupe_warnings(warnings),
        "method": method,
    }


def _welch_numpy(signal: np.ndarray, sample_rate_hz: float, nperseg: int, noverlap: int) -> tuple[np.ndarray, np.ndarray]:
    if signal.size < 2 or sample_rate_hz <= 0:
        return np.array([], dtype=float), np.array([], dtype=float)
    step = max(1, nperseg - noverlap)
    if signal.size < nperseg:
        nperseg = int(signal.size)
        noverlap = 0
        step = nperseg
    windows: list[np.ndarray] = []
    for start in range(0, signal.size - nperseg + 1, step):
        windows.append(signal[start : start + nperseg])
    if not windows:
        windows = [signal[:nperseg]]
    hann = np.hanning(nperseg)
    scale = float(sample_rate_hz * np.sum(hann * hann))
    freqs = np.fft.rfftfreq(nperseg, d=1.0 / sample_rate_hz)
    powers = []
    for chunk in windows:
        fft = np.fft.rfft(chunk * hann)
        powers.append((np.abs(fft) ** 2) / max(scale, 1e-12))
    return freqs, np.mean(np.vstack(powers), axis=0)


def _dominant_peaks(
    freqs: np.ndarray,
    power: np.ndarray,
    quality: Quality,
    *,
    max_peaks: int,
) -> list[dict[str, Any]]:
    if freqs.size == 0 or power.size == 0:
        return []
    finite = np.isfinite(freqs) & np.isfinite(power)
    freqs = freqs[finite]
    power = power[finite]
    if freqs.size < 3 or power.size < 3:
        return []
    power = np.maximum(power, 0.0)
    max_power = float(np.max(power)) if power.size else 0.0
    if max_power <= 0:
        return []

    candidates: list[tuple[float, float]] = []
    for idx in range(1, power.size - 1):
        hz = float(freqs[idx])
        if hz <= 0:
            continue
        if power[idx] >= power[idx - 1] and power[idx] >= power[idx + 1]:
            candidates.append((hz, float(power[idx])))
    if not candidates:
        max_idx = int(np.argmax(power))
        candidates.append((float(freqs[max_idx]), float(power[max_idx])))
    candidates.sort(key=lambda item: item[1], reverse=True)

    peaks: list[dict[str, Any]] = []
    for hz, pwr in candidates:
        if any(abs(hz - existing["hz"]) <= max(3.0, existing["hz"] * 0.03) for existing in peaks):
            continue
        relative = float(pwr / max_power)
        peaks.append(
            {
                "hz": round(hz, 3),
                "power": float(pwr),
                "relative_power": round(relative, 6),
                "confidence": _confidence_from_relative_power(relative, quality),
            }
        )
        if len(peaks) >= max_peaks:
            break
    return peaks


def compute_welch_psd(
    axis_data: Any,
    sample_rate_hz: float,
    window_seconds: float = 0.5,
    overlap: float = 0.5,
    max_peaks: int = 5,
) -> dict[str, Any]:
    """Compute a compact Welch PSD summary, keeping arrays internal to callers."""
    prepared = prepare_fft_signal(axis_data, sample_rate_hz)
    signal = np.asarray(prepared["signal"], dtype=float)
    fs = float(prepared["sample_rate_hz"])
    warnings = list(prepared["warnings"])
    if signal.size < 2 or fs <= 0:
        warnings.append("Insufficient valid samples for Welch PSD.")
        return {
            "method": "scipy_welch" if scipy_signal is not None else "numpy_welch_fallback",
            "sample_rate_hz": fs if fs > 0 else 0.0,
            "sample_count": int(signal.size),
            "quality": "low",
            "warnings": _dedupe_warnings(warnings),
            "dominant_peaks": [],
            "frequencies": np.array([], dtype=float),
            "power": np.array([], dtype=float),
        }

    try:
        window_s = max(0.05, float(window_seconds))
    except (TypeError, ValueError):
        window_s = 0.5
    nperseg = min(int(signal.size), max(16, int(round(fs * window_s))))
    try:
        overlap_f = min(0.9, max(0.0, float(overlap)))
    except (TypeError, ValueError):
        overlap_f = 0.5
    noverlap = int(round(nperseg * overlap_f))
    noverlap = max(0, min(nperseg - 1, noverlap))

    if scipy_signal is not None:
        freqs, power = scipy_signal.welch(
            signal,
            fs=fs,
            window="hann",
            nperseg=nperseg,
            noverlap=noverlap,
            detrend=False,
            scaling="density",
        )
        method = "scipy_welch"
    else:
        freqs, power = _welch_numpy(signal, fs, nperseg, noverlap)
        method = "numpy_welch_fallback"

    quality = str(prepared["quality"])
    peaks = _dominant_peaks(
        np.asarray(freqs, dtype=float),
        np.asarray(power, dtype=float),
        quality,
        max_peaks=max(1, min(10, int(max_peaks))),
    )
    return {
        "method": method,
        "sample_rate_hz": fs,
        "sample_count": int(signal.size),
        "quality": quality,
        "warnings": _dedupe_warnings(warnings),
        "dominant_peaks": peaks,
        "frequencies": np.asarray(freqs, dtype=float),
        "power": np.asarray(power, dtype=float),
    }


def _gyro_value_from_sample(sample: Mapping[str, Any]) -> float | None:
    keys = ("gx", "gy", "gz")
    if all(key in sample for key in keys):
        vals = []
        for key in keys:
            try:
                vals.append(float(sample.get(key, 0.0)))
            except (TypeError, ValueError):
                vals.append(0.0)
        return float(math.sqrt(sum(v * v for v in vals) / 3.0))
    alt_keys = ("gyro_x", "gyro_y", "gyro_z")
    if all(key in sample for key in alt_keys):
        vals = []
        for key in alt_keys:
            try:
                vals.append(float(sample.get(key, 0.0)))
            except (TypeError, ValueError):
                vals.append(0.0)
        return float(math.sqrt(sum(v * v for v in vals) / 3.0))
    for key in ("gyro", "gyroX"):
        if key in sample:
            try:
                return float(sample[key])
            except (TypeError, ValueError):
                return None
    return None


def _normalized_throttle_values(samples: Sequence[Mapping[str, Any]]) -> list[float | None]:
    raw_values: list[float | None] = []
    finite: list[float] = []
    for sample in samples:
        raw = sample.get("throttle")
        try:
            val = float(raw)
        except (TypeError, ValueError):
            raw_values.append(None)
            continue
        if not math.isfinite(val):
            raw_values.append(None)
            continue
        raw_values.append(val)
        finite.append(val)
    if not finite:
        return [None for _ in raw_values]
    max_raw = max(finite)
    min_raw = min(finite)
    out: list[float | None] = []
    for val in raw_values:
        if val is None:
            out.append(None)
        elif max_raw <= 1.5 and min_raw >= -0.05:
            out.append(float(np.clip(val, 0.0, 1.0)))
        elif 900.0 <= min_raw <= 1100.0 and max_raw <= 2100.0:
            out.append(float(np.clip((val - 1000.0) / 1000.0, 0.0, 1.0)))
        elif 0.0 <= min_raw and max_raw <= 1000.0:
            out.append(float(np.clip(val / 1000.0, 0.0, 1.0)))
        else:
            out.append(float(np.clip(val, 0.0, 1.0)))
    return out


def compute_throttle_band_psd(
    samples: Sequence[Mapping[str, Any]],
    sample_rate_hz: float,
    throttle_bands: Mapping[str, tuple[float, float]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Compute compact Welch peak summaries for low/mid/high throttle bands."""
    bands = dict(throttle_bands or _DEFAULT_THROTTLE_BANDS)
    rows = [sample for sample in samples if isinstance(sample, Mapping)]
    throttle = _normalized_throttle_values(rows)
    gyro_values = [_gyro_value_from_sample(sample) for sample in rows]
    out: dict[str, dict[str, Any]] = {}
    for name, bounds in bands.items():
        lo, hi = float(bounds[0]), float(bounds[1])
        values = [
            gyro
            for gyro, thr in zip(gyro_values, throttle, strict=False)
            if gyro is not None and thr is not None and lo <= thr <= hi
        ]
        if values:
            psd = compute_welch_psd(values, sample_rate_hz, max_peaks=3)
            peaks = [
                {
                    "hz": peak["hz"],
                    "relative_power": peak["relative_power"],
                    "confidence": peak["confidence"],
                }
                for peak in psd["dominant_peaks"][:3]
            ]
            warnings = psd["warnings"]
            quality = psd["quality"]
        else:
            peaks = []
            warnings = ["No valid samples in throttle band."]
            quality = "low"
        out[str(name)] = {
            "range": [round(lo, 3), round(hi, 3)],
            "sample_count": len(values),
            "quality": quality,
            "warnings": _dedupe_warnings(warnings),
            "peaks": peaks,
        }
    return out


def detect_resonance_persistence(psd_windows: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Identify compact evidence for peaks repeated across throttle bands/windows."""
    rows: list[tuple[str, float, float, Confidence]] = []
    if isinstance(psd_windows, Mapping):
        iterable = psd_windows.items()
    else:
        iterable = ((f"window_{idx}", item) for idx, item in enumerate(psd_windows))
    for band, block in iterable:
        if not isinstance(block, Mapping):
            continue
        peaks = block.get("peaks") or block.get("dominant_peaks")
        if not isinstance(peaks, list):
            continue
        for peak in peaks[:5]:
            if not isinstance(peak, Mapping):
                continue
            try:
                hz = float(peak.get("hz"))
                rel = float(peak.get("relative_power", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if math.isfinite(hz) and hz > 0:
                conf = str(peak.get("confidence") or "low")
                rows.append((str(band), hz, rel, conf if conf in {"high", "medium", "low"} else "low"))
    if not rows:
        return []

    clusters: list[dict[str, Any]] = []
    for band, hz, rel, conf in sorted(rows, key=lambda item: item[1]):
        match = None
        for cluster in clusters:
            center = float(cluster["hz_sum"]) / max(1, int(cluster["count"]))
            if abs(hz - center) <= max(5.0, center * 0.05):
                match = cluster
                break
        if match is None:
            match = {"hz_sum": 0.0, "count": 0, "bands": set(), "rel_sum": 0.0, "conf": []}
            clusters.append(match)
        match["hz_sum"] += hz
        match["count"] += 1
        match["bands"].add(band)
        match["rel_sum"] += max(0.0, min(1.0, rel))
        match["conf"].append(conf)

    out: list[dict[str, Any]] = []
    possible_bands = max(1, len({band for band, *_ in rows}))
    for cluster in clusters:
        bands_seen = sorted(cluster["bands"])
        persistence = min(1.0, len(bands_seen) / possible_bands)
        avg_rel = float(cluster["rel_sum"]) / max(1, int(cluster["count"]))
        score = round(min(1.0, persistence * 0.7 + avg_rel * 0.3), 4)
        if len(bands_seen) >= 2:
            likely_type = "persistent_frame_resonance"
        elif bands_seen and bands_seen[0] in {"mid", "high"}:
            likely_type = "throttle_dependent"
        else:
            likely_type = "unknown"
        confidence = "high" if score >= 0.72 and len(bands_seen) >= 2 else "medium" if score >= 0.4 else "low"
        out.append(
            {
                "hz": round(float(cluster["hz_sum"]) / max(1, int(cluster["count"])), 3),
                "bands_seen": bands_seen,
                "persistence_score": score,
                "likely_type": likely_type,
                "confidence": confidence,
            }
        )
    out.sort(key=lambda item: (item["persistence_score"], len(item["bands_seen"])), reverse=True)
    return out[:5]


def build_spectral_evidence_from_samples(
    samples: Sequence[Mapping[str, Any]],
    sample_rate_hz: float | None,
    *,
    original_sample_count: int | None = None,
    original_sample_rate_hz: float | None = None,
    samples_were_capped: bool | None = None,
    samples_were_subsampled: bool | None = None,
) -> dict[str, Any]:
    """Build compact API-facing spectral evidence from normalized analyze samples."""
    warnings: list[str] = ["Welch PSD preview is supporting evidence, not a full Betaflight filter simulation."]
    rows = [sample for sample in samples if isinstance(sample, Mapping)]
    gyro = [_gyro_value_from_sample(sample) for sample in rows]
    axis = [value for value in gyro if value is not None]
    try:
        fs = float(sample_rate_hz) if sample_rate_hz is not None else 0.0
    except (TypeError, ValueError):
        fs = 0.0
    try:
        original_fs = float(original_sample_rate_hz) if original_sample_rate_hz is not None else 0.0
    except (TypeError, ValueError):
        original_fs = 0.0
    if not math.isfinite(original_fs) or original_fs <= 0:
        original_fs = 0.0
    original_count = None
    if isinstance(original_sample_count, (int, float)) and not isinstance(original_sample_count, bool):
        try:
            original_count = int(original_sample_count)
        except (TypeError, ValueError, OverflowError):
            original_count = None
    analyzed_count = len(rows)
    capped = (
        bool(samples_were_capped)
        if isinstance(samples_were_capped, bool)
        else bool(original_count is not None and original_count > analyzed_count)
    )
    subsampled = (
        bool(samples_were_subsampled)
        if isinstance(samples_were_subsampled, bool)
        else capped
    )
    psd = compute_welch_psd(axis, fs, max_peaks=5)
    warnings.extend(psd["warnings"])
    if capped or subsampled:
        warnings.append("Large log was analyzed from a capped sample window; high-frequency evidence may be less precise.")
    throttle_bands = compute_throttle_band_psd(rows, fs) if rows and fs > 0 else {}
    persistence = detect_resonance_persistence(throttle_bands)
    dominant_peaks = [
        {
            "hz": peak["hz"],
            "relative_power": peak["relative_power"],
            "confidence": peak["confidence"],
        }
        for peak in psd["dominant_peaks"][:5]
    ]
    quality = str(psd["quality"])
    if (capped or subsampled) and quality == "high":
        quality = "medium"
    return {
        "version": 1,
        "method": "welch_psd_preview",
        "quality": quality if quality in {"high", "medium", "low"} else "low",
        "sample_rate_hz": round(fs, 3) if fs > 0 else None,
        "effective_sample_rate_hz": round(fs, 3) if fs > 0 else None,
        "original_sample_rate_hz": round(original_fs, 3) if original_fs > 0 else None,
        "sample_count": int(psd["sample_count"]) if isinstance(psd.get("sample_count"), int) else len(axis),
        "analyzed_sample_count": analyzed_count,
        "used_sample_count": analyzed_count,
        "original_sample_count": original_count,
        "samples_were_capped": capped,
        "samples_were_subsampled": subsampled,
        "warnings": _dedupe_warnings(warnings),
        "dominant_peaks": dominant_peaks,
        "throttle_bands": {
            name: {
                "range": block["range"],
                "sample_count": block["sample_count"],
                "peaks": block["peaks"][:3],
            }
            for name, block in throttle_bands.items()
            if isinstance(block, Mapping)
        },
        "persistence": persistence[:5],
    }
