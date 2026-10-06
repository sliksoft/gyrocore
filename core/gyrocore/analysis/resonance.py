# GyroCore WU4: adapted from AeroTuner backend/analysis/resonance.py
from __future__ import annotations

import logging
import warnings
from typing import Any

import numpy as np
from scipy.signal import butter, find_peaks, peak_widths, sosfiltfilt

MIN_FREQ_HZ = 30.0
MAX_FREQ_HZ = 500.0
GYRO_CONFIRM_WINDOW_HZ = 5.0
MIN_NOISE_MULTIPLIER = 1.2
STD_THRESHOLD_SCALE = 1.8
SHARPNESS_THRESHOLD = 0.12
EPS = 1e-9

logger = logging.getLogger(__name__)


def compute_noise_floor(amplitudes: np.ndarray) -> float:
    """Robust FFT noise floor estimate using median + MAD."""
    a = np.asarray(amplitudes, dtype=float)
    if a.size == 0:
        return 0.0
    median = float(np.median(a))
    mad = float(np.median(np.abs(a - median)))
    return max(EPS, median + (1.4826 * mad))


def find_peaks_custom(
    freqs: np.ndarray,
    amplitudes: np.ndarray,
    min_freq_hz: float = MIN_FREQ_HZ,
    max_freq_hz: float = MAX_FREQ_HZ,
) -> np.ndarray:
    """Find valid local maxima in 30-500 Hz with strong amplitude thresholding."""
    f = np.asarray(freqs, dtype=float)
    a = np.asarray(amplitudes, dtype=float)
    if f.size < 3 or a.size < 3 or f.size != a.size:
        return np.array([], dtype=int)

    in_band = (f >= min_freq_hz) & (f <= max_freq_hz)
    idx = np.where(in_band)[0]
    if idx.size < 3:
        return np.array([], dtype=int)

    sub_a = a[idx]
    amp_threshold = float(np.mean(sub_a) + (STD_THRESHOLD_SCALE * np.std(sub_a)))

    sub_peaks, _ = find_peaks(sub_a)
    if sub_peaks.size == 0:
        return np.array([], dtype=int)

    global_peaks = idx[sub_peaks]
    strong = a[global_peaks] > amp_threshold
    return global_peaks[strong]


def compute_bandwidth(freqs: np.ndarray, amplitudes: np.ndarray, peak_index: int) -> float:
    """Compute width at half-height around a detected peak (Hz)."""
    f = np.asarray(freqs, dtype=float)
    a = np.asarray(amplitudes, dtype=float)
    if f.size < 3 or a.size < 3 or f.size != a.size:
        return 0.0
    if peak_index <= 0 or peak_index >= (a.size - 1):
        return 0.0

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="some peaks have a width of 0")
        widths, _, left_ips, right_ips = peak_widths(a, [peak_index], rel_height=0.5)
    if widths.size == 0:
        return 0.0

    x = np.arange(f.size, dtype=float)
    left_hz = float(np.interp(left_ips[0], x, f))
    right_hz = float(np.interp(right_ips[0], x, f))
    return max(0.0, right_hz - left_hz)


def compute_q_factor(freq_hz: float, bandwidth_hz: float | None = None, center_freq_hz: float | None = None) -> float:
    """
    Compute notch Q factor using q = freq / bandwidth.

    Backward compatible:
      - old call style: compute_q_factor(bandwidth, center_freq_hz=...)
      - new call style: compute_q_factor(freq, bandwidth)
    """
    if bandwidth_hz is None and center_freq_hz is not None:
        bandwidth_hz = float(freq_hz)
        freq_hz = float(center_freq_hz)
    bw = float(bandwidth_hz if bandwidth_hz is not None else 0.0)
    if bw <= 0:
        return 60.0
    q = float(freq_hz) / bw
    return float(np.clip(q, 5.0, 60.0))


def bandpass_filter(
    signal: np.ndarray,
    sample_rate: float,
    low_hz: float,
    high_hz: float,
    order: int = 3,
) -> np.ndarray:
    """Zero-phase Butterworth band-pass filter for gyro confirmation."""
    x = np.asarray(signal, dtype=float)
    if x.size < 16 or sample_rate <= 0:
        return np.zeros_like(x, dtype=float)

    nyquist = 0.5 * float(sample_rate)
    low = max(0.5, float(low_hz))
    high = min(float(high_hz), nyquist * 0.98)
    if low >= high:
        return np.zeros_like(x, dtype=float)

    sos = butter(order, [low, high], btype="bandpass", fs=sample_rate, output="sos")
    return sosfiltfilt(sos, x)


def _build_peak_record(freqs: np.ndarray, amplitudes: np.ndarray, peak_index: int) -> dict[str, Any]:
    peak_freq = float(freqs[peak_index])
    peak_height = float(amplitudes[peak_index])
    bandwidth = compute_bandwidth(freqs, amplitudes, peak_index)
    sharpness = peak_height / max(bandwidth, EPS)
    peak_type = "narrow_resonance" if sharpness > SHARPNESS_THRESHOLD else "broad_noise"
    return {
        "freq": peak_freq,
        "amplitude": peak_height,
        "peak_height": peak_height,
        "bandwidth": bandwidth,
        "sharpness": sharpness,
        "type": peak_type,
        "is_harmonic": False,
    }


def _compute_isolation_hz(peaks: list[dict[str, Any]], peak_pos: int) -> float:
    if len(peaks) <= 1:
        return 1.0
    current = float(peaks[peak_pos]["freq"])
    distances = [abs(current - float(p["freq"])) for i, p in enumerate(peaks) if i != peak_pos]
    if not distances:
        return 1.0
    return max(min(distances), 1.0)


def compute_confidence(
    peak_amp: float | None = None,
    noise_floor: float = 0.0,
    bandwidth: float = 0.0,
    isolation: float | None = None,
    gyro_energy_ratio: float = 0.0,
    peak_freq: float | None = None,
    consistency_score: float | None = None,
    **legacy_kwargs: Any,
) -> float:
    """
    Weighted confidence model (0..1):
      - SNR: 0.35
      - Bandwidth: 0.25
      - Isolation: 0.20
      - Gyro energy ratio: 0.20
    """
    # Backward-compatible kwargs support:
    #   peak_height -> peak_amp
    #   isolation_hz -> isolation
    if "peak_height" in legacy_kwargs and peak_amp is None:
        peak_amp = float(legacy_kwargs["peak_height"])
    if "isolation_hz" in legacy_kwargs and isolation is None:
        isolation = float(legacy_kwargs["isolation_hz"])

    peak_amp = float(0.0 if peak_amp is None else peak_amp)
    noise_floor = max(float(noise_floor), 1e-6)
    bandwidth = max(float(bandwidth), 1e-6)
    isolation = max(float(0.0 if isolation is None else isolation), 0.0)

    if peak_freq is None or peak_freq <= 0:
        peak_freq = max(isolation, 1.0)
    peak_freq = max(float(peak_freq), 1e-6)

    snr = min(1.0, peak_amp / (noise_floor * 5.0))
    bw_score = 1.0 - min(1.0, bandwidth / (peak_freq * 0.25))
    isolation_score = min(1.0, isolation / peak_freq)
    energy_score = min(1.0, max(0.0, float(gyro_energy_ratio)))
    if "cluster_consistency" in legacy_kwargs and consistency_score is None:
        consistency_score = float(legacy_kwargs["cluster_consistency"])
    consistency_score = float(np.clip(0.0 if consistency_score is None else consistency_score, 0.0, 1.0))

    confidence = (snr * 0.35) + (bw_score * 0.25) + (isolation_score * 0.20) + (energy_score * 0.20)
    confidence = (0.9 * confidence) + (0.1 * consistency_score)
    return float(max(0.0, min(1.0, confidence)))


def _compute_confidence(
    peak_height: float,
    noise_floor: float,
    bandwidth: float,
    isolation_hz: float,
    gyro_energy_ratio: float,
) -> float:
    """Backward-compatible internal alias."""
    return compute_confidence(
        peak_amp=peak_height,
        noise_floor=noise_floor,
        bandwidth=bandwidth,
        isolation=isolation_hz,
        gyro_energy_ratio=gyro_energy_ratio,
        peak_freq=max(isolation_hz, 1.0),
    )


def detect_harmonics(peaks: list[dict[str, Any]], tolerance: float = 0.08) -> list[dict[str, Any]]:
    """
    Detect 2nd and 3rd harmonic relations across peaks.

    Returns:
      [{"fundamental": f0, "harmonic": f1, "order": 2|3}, ...]
    """
    if not peaks:
        return []

    sorted_peaks = sorted(peaks, key=lambda p: float(p.get("freq", 0.0)))

    # Keep the best (strongest-amplitude fundamental) assignment per harmonic frequency.
    best_for_harmonic: dict[tuple[float, int], dict[str, Any]] = {}

    for i, base in enumerate(sorted_peaks):
        f0 = float(base.get("freq", 0.0))
        a0 = float(base.get("amplitude", 0.0))
        if f0 <= 0:
            continue
        for candidate in sorted_peaks[i + 1 :]:
            fh = float(candidate.get("freq", 0.0))
            if fh <= f0:
                continue
            ratio = fh / f0
            order: int | None = None
            if abs(ratio - 2.0) < tolerance:
                order = 2
            elif abs(ratio - 3.0) < tolerance:
                order = 3
            if order is None:
                continue

            key = (round(fh, 6), order)
            existing = best_for_harmonic.get(key)
            if existing is None or a0 > float(existing.get("_fund_amp", 0.0)):
                best_for_harmonic[key] = {
                    "fundamental": f0,
                    "harmonic": fh,
                    "order": order,
                    "_fund_amp": a0,
                }

    result = []
    for item in best_for_harmonic.values():
        result.append(
            {
                "fundamental": float(item["fundamental"]),
                "harmonic": float(item["harmonic"]),
                "order": int(item["order"]),
            }
        )
    # Stable output for deterministic behavior.
    result.sort(key=lambda x: (x["fundamental"], x["harmonic"], x["order"]))
    return result


def cluster_peaks(peaks: list[dict[str, Any]], tolerance: float = 3.0) -> list[dict[str, Any]]:
    """
    Group peaks by frequency proximity.

    Peaks within +/- tolerance Hz are merged into one cluster.
    """
    if not peaks:
        return []

    ordered = sorted(peaks, key=lambda p: float(p.get("freq", 0.0)))
    clusters: list[dict[str, Any]] = []

    current_group: list[dict[str, Any]] = [ordered[0]]
    for peak in ordered[1:]:
        prev_freq = float(current_group[-1].get("freq", 0.0))
        freq = float(peak.get("freq", 0.0))
        adaptive_tolerance = max(float(tolerance), 2.0, min(prev_freq, freq) * 0.03)
        if abs(freq - prev_freq) <= adaptive_tolerance:
            current_group.append(peak)
        else:
            center = float(np.mean([float(p.get("freq", 0.0)) for p in current_group]))
            clusters.append({"center": center, "peaks": current_group[:]})
            current_group = [peak]

    if current_group:
        center = float(np.mean([float(p.get("freq", 0.0)) for p in current_group]))
        clusters.append({"center": center, "peaks": current_group[:]})

    return clusters


def score_cluster(cluster: dict[str, Any], noise_floor: float) -> float:
    peaks = cluster.get("peaks", []) if isinstance(cluster, dict) else []
    if not peaks:
        return 0.0
    total_amp = float(sum(float(p.get("amplitude", 0.0)) for p in peaks))
    avg_bw = float(np.mean([max(float(p.get("bandwidth", 0.0)), EPS) for p in peaks]))
    snr = total_amp / (float(noise_floor) + 1e-6)
    sharpness = 1.0 / (avg_bw + 1e-6)
    return (0.7 * snr) + (0.3 * sharpness)


def classify_relationship(c1: dict[str, Any], c2: dict[str, Any]) -> str:
    f1 = float(c1.get("center", 0.0))
    f2 = float(c2.get("center", 0.0))
    if f1 <= 0 or f2 <= 0:
        return "independent"
    ratio = f2 / f1
    if abs(ratio - 2.0) < 0.1:
        return "harmonic_2x"
    delta = abs(f2 - f1)
    if delta < (f1 * 0.08):
        a1 = float(c1.get("total_amplitude", 0.0))
        a2 = float(c2.get("total_amplitude", 0.0))
        amp_ratio = min(a1, a2) / max(max(a1, a2), 1e-6)
        if amp_ratio > 0.5:
            return "split_resonance"
        return "neighbor"
    if delta < 10.0:
        return "neighbor"
    return "independent"


def analyze_resonance(
    freqs: np.ndarray,
    amplitudes: np.ndarray,
    gyro_signal: np.ndarray,
    sample_rate: float,
) -> dict[str, Any]:
    """Detect primary resonance and produce dynamic notch recommendation."""
    f = np.asarray(freqs, dtype=float)
    a = np.asarray(amplitudes, dtype=float)
    g = np.asarray(gyro_signal, dtype=float)

    if f.size < 3 or a.size < 3 or f.size != a.size:
        return {
            "primary": None,
            "secondary": [],
            "notch": None,
            "harmonics": [],
            "peaks": [],
            "meta": {"noise_floor": 0.0, "num_peaks": 0},
        }

    noise_floor = compute_noise_floor(a)
    peak_indices = find_peaks_custom(f, a)

    raw_peaks: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for idx in peak_indices:
        record = _build_peak_record(f, a, int(idx))
        raw_peaks.append(record)
        if record["amplitude"] < (MIN_NOISE_MULTIPLIER * noise_floor):
            continue
        max_bw = max(float(record["freq"]) * 0.25, 1.0)
        if record["bandwidth"] > max_bw:
            continue
        candidates.append(record)
    if len(candidates) == 0 and len(raw_peaks) > 0:
        candidates = raw_peaks[:1]
    valid_peaks = candidates
    logger.debug(
        "resonance peaks raw=%d candidates=%d",
        len(raw_peaks),
        len(valid_peaks),
    )

    if not candidates:
        return {
            "primary": None,
            "secondary": [],
            "notch": None,
            "harmonics": [],
            "peaks": [],
            "meta": {"noise_floor": float(noise_floor), "num_peaks": 0},
        }

    # Enforce realistic minimal measurable bandwidth for stable Q and confidence.
    for candidate in candidates:
        bw = float(candidate.get("bandwidth", 0.0))
        if bw < 1.0:
            candidate["bandwidth"] = 1.0
            candidate["sharpness"] = float(candidate["amplitude"]) / 1.0

    clusters = cluster_peaks(candidates, tolerance=3.0)
    if not clusters:
        clusters = [{"center": float(c["freq"]), "peaks": [c]} for c in candidates]
    assert len(clusters) > 0, "CLUSTERING NOT EXECUTED"
    logger.debug(
        "resonance clusters=%d centers=%s",
        len(clusters),
        [float(c["center"]) for c in clusters],
    )

    # Cluster scoring helpers.
    for cluster in clusters:
        cluster["total_amplitude"] = float(sum(float(p.get("amplitude", 0.0)) for p in cluster["peaks"]))
        cluster["score"] = score_cluster(cluster, noise_floor)

    primary_peak = max(candidates, key=lambda p: float(p.get("amplitude", 0.0)))
    primary_cluster = next(
        (c for c in clusters if any(p is primary_peak for p in c["peaks"])),
        None,
    )
    if primary_cluster is None:
        primary_cluster = min(
            clusters,
            key=lambda c: abs(float(c["center"]) - float(primary_peak["freq"])),
        )

    primary_score = float(score_cluster(primary_cluster, noise_floor))
    secondary_threshold = max(primary_score * 0.2, 0.1)
    secondary_clusters = [
        c for c in clusters if c is not primary_cluster and float(score_cluster(c, noise_floor)) > secondary_threshold
    ]
    ordered_clusters = [primary_cluster, *sorted(secondary_clusters, key=lambda c: float(c.get("score", 0.0)), reverse=True)]
    excluded_clusters = [c for c in clusters if c is not primary_cluster and c not in secondary_clusters]
    ordered_clusters.extend(sorted(excluded_clusters, key=lambda c: float(c.get("score", 0.0)), reverse=True))

    # Harmoncs are detected from cluster centers.
    harmonic_input = [{"freq": float(c["center"]), "amplitude": float(c.get("total_amplitude", 0.0))} for c in ordered_clusters]
    harmonics = detect_harmonics(harmonic_input)
    harmonic_centers = {float(h["harmonic"]) for h in harmonics}
    for cluster in ordered_clusters:
        center = float(cluster["center"])
        cluster_is_harmonic = any(abs(center - hc) <= 1e-6 for hc in harmonic_centers)
        for peak in cluster["peaks"]:
            peak["is_harmonic"] = cluster_is_harmonic

    primary = primary_peak

    center = float(primary["freq"])
    band_signal = bandpass_filter(
        signal=g,
        sample_rate=sample_rate,
        low_hz=center - GYRO_CONFIRM_WINDOW_HZ,
        high_hz=center + GYRO_CONFIRM_WINDOW_HZ,
    )
    total_energy = float(np.mean(np.square(g))) if g.size else 0.0
    band_energy = float(np.mean(np.square(band_signal))) if band_signal.size else 0.0
    gyro_energy_ratio = band_energy / max(total_energy, EPS)

    primary_idx = candidates.index(primary)
    isolation_hz = _compute_isolation_hz(candidates, primary_idx)
    confidence = compute_confidence(
        peak_amp=float(primary["peak_height"]),
        noise_floor=float(noise_floor),
        bandwidth=float(primary["bandwidth"]),
        isolation=float(isolation_hz),
        gyro_energy_ratio=float(gyro_energy_ratio),
        peak_freq=float(primary["freq"]),
        consistency_score=min(1.0, len(primary_cluster["peaks"]) / 5.0),
    )
    other_scores = [float(score_cluster(c, noise_floor)) for c in clusters if c is not primary_cluster]
    dominance = primary_score / (sum(other_scores) + 1e-6)
    dominance_score = min(1.0, dominance / 3.0)
    confidence = float(np.clip((0.9 * confidence) + (0.1 * dominance_score), 0.0, 1.0))

    primary_payload = {
        "freq": float(primary["freq"]),
        "amplitude": float(primary["amplitude"]),
        "bandwidth": float(primary["bandwidth"]),
        "confidence": confidence,
        "type": "resonance" if primary["type"] == "narrow_resonance" else "noise",
        "sharpness": float(primary["sharpness"]),
        "is_harmonic": bool(primary["is_harmonic"]),
    }

    secondary_payload: list[dict[str, Any]] = []
    for cluster in secondary_clusters:
        rep = max(cluster["peaks"], key=lambda p: float(p.get("amplitude", 0.0)))
        secondary_payload.append(
            {
                "freq": float(rep["freq"]),
                "amplitude": float(rep["amplitude"]),
                "bandwidth": float(rep["bandwidth"]),
                "type": str(rep["type"]),
                "sharpness": float(rep["sharpness"]),
                "is_harmonic": bool(rep["is_harmonic"]),
            }
        )

    notch_strength = float(np.clip(float(primary["amplitude"]) / max(float(noise_floor) * 5.0, EPS), 0.0, 1.0))
    notch_freq = float(primary["freq"])
    cluster_freqs = [float(p.get("freq", notch_freq)) for p in primary_cluster.get("peaks", [])]
    cluster_bw = (max(cluster_freqs) - min(cluster_freqs)) if len(cluster_freqs) > 1 else 0.0
    avg_peak_bandwidth = float(
        np.mean([max(float(p.get("bandwidth", 0.0)), 1.0) for p in primary_cluster.get("peaks", [])])
    )
    notch_bandwidth = max(cluster_bw, avg_peak_bandwidth, 1.0)
    notch = {
        "freq": notch_freq,
        "q": compute_q_factor(notch_freq, notch_bandwidth),
        "width_hz": notch_bandwidth,
        "type": "dynamic_notch",
        "strength": notch_strength,
    }

    peaks_payload = [
        {
            "freq": float(candidate["freq"]),
            "amplitude": float(candidate["amplitude"]),
            "bandwidth": float(candidate["bandwidth"]),
            "sharpness": float(candidate["sharpness"]),
            "is_harmonic": bool(candidate["is_harmonic"]),
        }
        for candidate in candidates
    ]
    spread = (
        0.0
        if len(ordered_clusters) <= 1
        else float(max(c["center"] for c in ordered_clusters) - min(c["center"] for c in ordered_clusters))
    )
    spread_penalty = min(1.0, spread / 50.0)
    confidence = float(np.clip(confidence * (1.0 - 0.3 * spread_penalty), 0.0, 1.0))
    primary_payload["confidence"] = confidence
    relationships: list[dict[str, Any]] = []
    secondary_needed = False
    for cluster in secondary_clusters:
        rel_type = classify_relationship(primary_cluster, cluster)
        s_score = float(score_cluster(cluster, noise_floor))
        relationships.append(
            {
                "from": float(primary["freq"]),
                "to": float(cluster["center"]),
                "type": rel_type,
            }
        )
        if rel_type == "independent" and s_score > 0.6:
            if dominance < 2.5:
                secondary_needed = True

    has_split_resonance = any(r.get("type") == "split_resonance" for r in relationships)
    if has_split_resonance:
        notch_bandwidth *= 1.5
        notch_bandwidth = max(notch_bandwidth, 1.0)
        notch["width_hz"] = notch_bandwidth
        notch["q"] = compute_q_factor(notch_freq, notch_bandwidth)

    notch_freq = float(np.clip(notch_freq, 30.0, 500.0))
    notch["freq"] = notch_freq

    if secondary_needed:
        reason = "multiple_independent_resonances"
    elif has_split_resonance:
        reason = "split_resonance_single_filter"
    else:
        reason = "single_clean_resonance"

    filter_strategy = {
        "primary_only": not secondary_needed,
        "secondary": secondary_needed,
        "reason": reason,
    }

    return {
        "primary": primary_payload,
        "secondary": secondary_payload,
        "notch": notch,
        "harmonics": harmonics,
        "peaks": peaks_payload,
        "clusters": ordered_clusters,
        "spread": spread,
        "relationships": relationships,
        "filter_strategy": filter_strategy,
        "meta": {
            "noise_floor": float(noise_floor),
            "num_peaks": len(candidates),
            "gyro_band_energy": band_energy,
            "gyro_total_energy": total_energy,
            "gyro_energy_ratio": gyro_energy_ratio,
        },
    }


def classify_issue(resonance_result: dict[str, Any], gyro_signal: np.ndarray) -> str:
    """Classify overall state as resonance, noise, or clean."""
    primary = resonance_result.get("primary") if isinstance(resonance_result, dict) else None
    if not primary:
        return "clean"

    confidence = float(primary.get("confidence", 0.0) or 0.0)
    meta = resonance_result.get("meta") if isinstance(resonance_result.get("meta"), dict) else {}
    noise_floor = float(meta.get("noise_floor", 0.0) or 0.0)

    # Optional enhancement: noisy logs with meaningful resonance confidence.
    noise_threshold = 1.0
    if noise_floor > noise_threshold and confidence > 0.4:
        return "resonance_with_noise"

    if confidence > 0.75:
        return "strong_resonance"
    elif confidence > 0.4:
        return "moderate_resonance"
    elif confidence > 0.2:
        return "weak_resonance"
    else:
        return "noise"
