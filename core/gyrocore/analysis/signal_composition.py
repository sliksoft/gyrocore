# GyroCore WU16: adapted from AeroTuner backend/routes/analyze.py
"""
Signal-analysis composition that feeds ``build_metrics``.

Wires existing GyroCore primitives (multi_axis_fft, noise_model, resonance_v2,
signal, sample_rate_metadata) the way the donor ``_build_response`` route does,
so metrics.noise / metrics.propwash / metrics.resonance come from computed
spectra instead of metrics_engine fallbacks.

Adapted donor functions: ``_gyro_spectral_bundle_raw``, ``_compute_spectral_bundle``,
``_build_fft_from_bundle``, ``_aggregate_noise_model_from_axes``,
``_merged_peaks_from_axis_blocks``, ``_build_analysis`` (signal fields consumed by
metrics), ``_apply_sample_rate_gates_to_analysis``, ``detect_propwash`` /
``_detect_propwash_level`` (dict rows only), ``compute_unified_propwash`` and the
spectral ``source_kind`` selection. Route-only concerns (logging, phase-2
diagnostics, pre-cap rescue, UI spectrum views) are not ported.
"""

from __future__ import annotations

import copy
import math
from typing import Any, Mapping, Sequence

import numpy as np

from gyrocore.analysis.multi_axis_fft import merge_axes_fft, per_axis_smoothed_spectra
from gyrocore.analysis.noise_model import compute_noise_score
from gyrocore.analysis.resonance_v2 import (
    annotate_peaks_with_erpm,
    classify_resonance,
    detect_resonance_peaks,
)
from gyrocore.analysis.sample_rate_metadata import (
    SPECTRAL_SOURCE_CAPPED_20K,
    SPECTRAL_SOURCE_DOWNSAMPLED,
    SPECTRAL_SOURCE_RAW_FULL_RATE,
    frequency_assessability,
    hf_noise_assessability,
)
from gyrocore.analysis.signal import compute_sample_rate, dynamic_band_energies, time_us_to_seconds

_AXES = ("roll", "pitch", "yaw")
_TIME_PROPWASH_WEIGHT = 0.6
_FREQ_PROPWASH_WEIGHT = 0.4


def spectral_source_kind(parsed_sample_count: int, raw_sample_count: Any = None) -> str:
    """Donor rule: capped when the original log had more rows than the parser kept."""
    if isinstance(raw_sample_count, (int, float)) and int(raw_sample_count) > int(parsed_sample_count):
        return SPECTRAL_SOURCE_CAPPED_20K
    return SPECTRAL_SOURCE_RAW_FULL_RATE


def _spectral_bundle_raw(samples: list[dict], *, remove_dc: bool) -> dict[str, Any] | None:
    if not samples:
        return None
    gx = np.asarray([float(s.get("gx", 0.0)) for s in samples], dtype=float)
    gy = np.asarray([float(s.get("gy", 0.0)) for s in samples], dtype=float)
    gz = np.asarray([float(s.get("gz", 0.0)) for s in samples], dtype=float)
    fs = float(compute_sample_rate(time_us_to_seconds([float(s.get("t", 0.0)) for s in samples])))
    if fs <= 0 or not np.isfinite(fs):
        fs = 1000.0
    freqs_m, spec_m = merge_axes_fft(gx, gy, gz, fs=fs, remove_dc=remove_dc)
    return {
        "fs": fs,
        "gx": gx,
        "gy": gy,
        "gz": gz,
        "merged_freqs": freqs_m,
        "merged_spectrum": spec_m,
        "axes": per_axis_smoothed_spectra(gx, gy, gz, fs=fs, remove_dc=remove_dc),
    }


def compute_spectral_bundle(samples: list[dict]) -> dict[str, Any] | None:
    """Merged + per-axis gyro spectra; retries with DC removal when the spectrum is all zero."""
    bundle = _spectral_bundle_raw(samples, remove_dc=False)
    if bundle is None:
        return None
    spec = np.asarray(bundle["merged_spectrum"], dtype=float)
    if spec.size == 0 or not np.any(spec):
        bundle = _spectral_bundle_raw(samples, remove_dc=True)
    return bundle


def _empty_axis_block() -> dict[str, Any]:
    z = np.array([], dtype=float)
    return {"noise": compute_noise_score(z, z), "peaks": []}


def build_axis_blocks(bundle: dict[str, Any] | None, erpm: dict | None) -> dict[str, dict[str, Any]]:
    """Per-axis noise score and resonance peaks (donor ``_build_fft_from_bundle``)."""
    out: dict[str, dict[str, Any]] = {}
    for name in _AXES:
        if bundle is None:
            out[name] = _empty_axis_block()
            continue
        fr, sp = bundle["axes"][name]
        if np.asarray(fr).size == 0:
            out[name] = _empty_axis_block()
            continue
        fq = np.asarray(fr, dtype=float)
        spn = np.asarray(sp, dtype=float)
        peaks = annotate_peaks_with_erpm(detect_resonance_peaks(fq, spn), erpm)
        out[name] = {"noise": compute_noise_score(fq, spn), "peaks": peaks}
    return out


def aggregate_noise_model(axes: Mapping[str, Any]) -> dict[str, Any]:
    """Unified noise_model: the noisiest axis (max HF ratio)."""
    candidates = [
        axes[name]["noise"]
        for name in _AXES
        if isinstance(axes.get(name), dict) and isinstance(axes[name].get("noise"), dict)
    ]
    if not candidates:
        z = np.array([], dtype=float)
        return compute_noise_score(z, z)
    return dict(max(candidates, key=lambda nm: float(nm.get("ratio") or 0.0)))


def merged_axis_peaks(axes: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Strongest per-axis peaks in 30–500 Hz, deduplicated within 5 Hz, at most 6."""
    raw = [
        dict(p)
        for name in _AXES
        if isinstance(axes.get(name), dict)
        for p in (axes[name].get("peaks") or [])
        if isinstance(p, dict)
    ]
    raw.sort(key=lambda x: float(x.get("amplitude", 0) or 0), reverse=True)
    deduped: list[dict[str, Any]] = []
    for p in raw:
        f = float(p.get("freq", 0) or 0)
        if not (30.0 < f < 500.0):
            continue
        if any(abs(f - float(x.get("freq", 0) or 0)) < 5.0 for x in deduped):
            continue
        deduped.append(p)
        if len(deduped) >= 6:
            break
    return deduped


def build_signal_analysis(
    bundle: dict[str, Any] | None,
    resonance: Mapping[str, Any] | None,
    erpm: dict | None,
    sample_rate_metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Signal fields consumed by ``build_metrics``: noise_model, fft_peaks,
    resonance_v2_hz and the HF-share ``propwash_level``, after sample-rate gating.

    ``resonance`` is the ``analyze_resonance`` result computed on this bundle's
    merged spectrum (single source of truth for the resonance module).
    """
    axes = build_axis_blocks(bundle, erpm)
    empty = {
        "noise_model": aggregate_noise_model(axes),
        "fft_peaks": [],
        "resonance_v2_hz": None,
        "propwash_level": 0.5,
        "axes": axes,
    }
    if bundle is None or np.asarray(bundle["merged_freqs"]).size == 0:
        return _apply_sample_rate_gates(empty, sample_rate_metadata, erpm)

    freqs = np.asarray(bundle["merged_freqs"], dtype=float)
    spectrum = np.asarray(bundle["merged_spectrum"], dtype=float)

    peaks_v2 = merged_axis_peaks(axes)
    res_freq = classify_resonance(peaks_v2, erpm)
    if res_freq is not None and res_freq < 30:
        res_freq = None
    if not peaks_v2 and np.any(spectrum):
        for mult in (2.0, 1.5, 1.25):
            peaks_v2 = detect_resonance_peaks(freqs, spectrum, threshold_multiplier=mult)
            if peaks_v2:
                peaks_v2 = annotate_peaks_with_erpm(peaks_v2, erpm)
                res_freq = classify_resonance(peaks_v2, erpm)
                if res_freq is not None and res_freq < 30:
                    res_freq = None
                break

    fft_peaks: list[dict[str, Any]] = []
    if peaks_v2:
        fft_peaks = list(peaks_v2)
    else:
        peaks_view = resonance.get("peaks") if isinstance(resonance, Mapping) else []
        for p in peaks_view or []:
            if not isinstance(p, dict):
                continue
            f = float(p.get("freq", 0.0) or 0.0)
            a = float(p.get("amplitude", 0.0) or 0.0)
            bw = float(p.get("bandwidth", 0.0) or 0.0)
            if f > 0 and bw <= 0:
                bw = f * 0.2
            fft_peaks.append({"freq": f, "amplitude": a, "bandwidth_hz": float(bw) if bw > 0 else None})
        fft_peaks = annotate_peaks_with_erpm(fft_peaks, erpm)

    bands = dynamic_band_energies(freqs, spectrum)
    band_low = float(bands.get("low", 0.0) or 0.0)
    band_mid = float(bands.get("mid", 0.0) or 0.0)
    band_high = float(bands.get("high", 0.0) or 0.0)
    band_total = band_low + band_mid + band_high

    out = {
        "noise_model": empty["noise_model"],
        "fft_peaks": fft_peaks,
        "resonance_v2_hz": res_freq,
        # HF band / total FFT energy (0–1); feeds unified propwash frequency score only.
        "propwash_level": (band_high / band_total) if band_total > 0 else 0.5,
        "axes": axes,
    }
    return _apply_sample_rate_gates(out, sample_rate_metadata, erpm, resonance)


def _apply_sample_rate_gates(
    analysis: dict[str, Any],
    sample_rate_metadata: Mapping[str, Any] | None,
    erpm: dict | None,
    resonance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Limit HF-noise / propwash / resonance claims the sample rate cannot support."""
    meta = sample_rate_metadata if isinstance(sample_rate_metadata, Mapping) else {}
    if not meta:
        return analysis
    erpm_hz = None
    if isinstance(erpm, dict):
        try:
            erpm_hz = float(erpm.get("dominant_frequency") or 0.0)
        except (TypeError, ValueError):
            erpm_hz = None
    motor_assess = frequency_assessability(meta, erpm_hz)
    analysis["gyro_motor_peak_assessment"] = {
        "status": "assessable" if motor_assess.get("assessable") else motor_assess.get("reason") or "not_assessable",
        **motor_assess,
    }
    hf_assess = hf_noise_assessability(meta)
    analysis["hf_noise_assessment"] = {
        "status": "assessable" if hf_assess.get("assessable") else hf_assess.get("reason"),
        **hf_assess,
    }
    if not hf_assess.get("assessable"):
        limit_reason = str(hf_assess.get("reason") or "hf_band_not_assessable")
        noise = analysis.get("noise_model")
        if isinstance(noise, dict):
            noise["assessable"] = False
            noise["confidence"] = "limited"
            noise["limited_by"] = limit_reason
            noise["limit_reasons"] = list(dict.fromkeys([*(noise.get("limit_reasons") or []), limit_reason]))
            noise["sample_rate_metadata"] = copy.deepcopy(dict(meta))
        analysis["propwash_frequency_assessable"] = False
        analysis["propwash_frequency_limit_reasons"] = [limit_reason]
        try:
            analysis["propwash_level"] = max(float(analysis.get("propwash_level") or 0.0), 0.5)
        except (TypeError, ValueError):
            analysis["propwash_level"] = 0.5
    if meta.get("source_kind") in {SPECTRAL_SOURCE_CAPPED_20K, SPECTRAL_SOURCE_DOWNSAMPLED} and isinstance(
        resonance, dict
    ):
        resonance["confidence"] = "limited"
        resonance["sample_rate_limited"] = True
        resonance["aliasing_possible"] = True
        resonance["limit_reasons"] = list(
            dict.fromkeys([*(resonance.get("limit_reasons") or []), "spectral_source_downsampled_aliasing_possible"])
        )
    return analysis


def _timestamp_us(sample: Mapping[str, Any], fallback_index: int) -> int:
    for key in ("t", "time_us", "us", "time"):
        raw = sample.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            return int(value)
    return int(fallback_index * 1000)


def detect_propwash(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Time-domain propwash: gyro activity in the window after throttle drops."""
    unknown = {"level": "unknown", "reason": "insufficient throttle data", "events": 0, "scores": [], "drops": 0}
    rows = [s for s in samples if s.get("throttle") is not None]
    if len(rows) < 300:
        return unknown
    throttle_raw: list[float | None] = []
    for s in rows:
        try:
            throttle_raw.append(float(s["throttle"]))
        except (TypeError, ValueError):
            throttle_raw.append(None)
    valid = [v for v in throttle_raw if v is not None]
    if not valid:
        return unknown
    raw_max = max(valid)
    throttle = [
        None if v is None else max(0.0, min(1.0, (v - 1000.0) / 1000.0 if raw_max > 1.5 else v))
        for v in throttle_raw
    ]
    times = [_timestamp_us(s, i) for i, s in enumerate(rows)]
    dts = sorted(d for d in (b - a for a, b in zip(times, times[1:])) if d > 0)
    window_size = max(20, int(round(200_000.0 / max(1.0, float(dts[len(dts) // 2]))))) if dts else 50

    drops = [
        i
        for i in range(1, len(rows))
        if throttle[i - 1] is not None
        and throttle[i] is not None
        and throttle[i - 1] > 0.4
        and throttle[i - 1] - throttle[i] > 0.2
    ]
    scores: list[float] = []
    event_ts: list[int] = []
    for i in drops:
        window = rows[i : min(len(rows), i + window_size)]
        if len(window) < 3:
            continue
        activity: list[float] = []
        for s in window:
            try:
                activity.append(max(abs(float(s.get(k, 0.0))) for k in ("gx", "gy", "gz")))
            except (TypeError, ValueError):
                continue
        if activity and max(activity) - min(activity) > 150:
            scores.append(float(max(activity)))
            event_ts.append(times[i])

    if not drops:
        level, reason = "none", "no throttle drops detected"
    elif not scores:
        level, reason = "none", "no oscillation after throttle drops"
    else:
        avg = sum(scores) / len(scores)
        level = "low" if avg < 150 else "medium" if avg < 300 else "high"
        reason = "oscillation detected after throttle drops"
    return {
        "level": level,
        "reason": reason,
        "events": len(scores),
        "scores": scores,
        "drops": len(drops),
        "event_timestamps_us": event_ts,
    }


def compute_unified_propwash(time_details: Mapping[str, Any], hf_ratio: Any) -> dict[str, Any]:
    """Weighted time-domain (0.6) + HF-share (0.4) propwash score and level."""
    lvl = str(time_details.get("level") or "unknown").lower()
    ts = {"low": 0.3, "medium": 0.55, "high": 0.85}.get(lvl, 0.0)
    try:
        fs = float(hf_ratio)
    except (TypeError, ValueError):
        fs = 0.0
    fs = 0.0 if not math.isfinite(fs) else max(0.0, min(1.0, fs))
    unified = max(0.0, min(1.0, _TIME_PROPWASH_WEIGHT * ts + _FREQ_PROPWASH_WEIGHT * fs))
    level = "none" if unified < 0.2 else "mild" if unified < 0.4 else "moderate" if unified < 0.7 else "severe"
    return {
        "level": level,
        "score": round(float(unified), 4),
        "time_score": round(float(ts), 4),
        "frequency_score": round(float(fs), 4),
    }
