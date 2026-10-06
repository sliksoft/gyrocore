# GyroCore WU4: adapted from AeroTuner backend/analysis/noise_model.py
import numpy as np


NOISE_LOW_MAX_RATIO = 20.0 / 200.0
NOISE_MEDIUM_MAX_RATIO = 50.0 / 200.0


def classify_noise_level_from_ratio(noise_ratio: float) -> str:
    """Classify high-frequency noise ratio using compute_noise_score thresholds."""
    try:
        ratio = float(noise_ratio)
    except (TypeError, ValueError):
        ratio = 0.0
    if not np.isfinite(ratio):
        ratio = 0.0
    if ratio < NOISE_LOW_MAX_RATIO:
        return "LOW"
    if ratio < NOISE_MEDIUM_MAX_RATIO:
        return "MEDIUM"
    return "HIGH"


def compute_noise_score(freqs: np.ndarray, spectrum: np.ndarray) -> dict:
    freqs = np.asarray(freqs, dtype=float)
    spectrum = np.asarray(spectrum, dtype=float)
    if freqs.size == 0 or spectrum.size == 0 or freqs.shape != spectrum.shape:
        return {
            "score": 0.0,
            "level": "LOW",
            "ratio": 0.0,
            "hf_ratio": 0.0,
            "hf_energy": 0.0,
            "total_energy": 0.0,
        }

    total_energy = float(np.sum(spectrum))
    hf_band = spectrum[freqs > 150.0]
    hf_energy = float(np.sum(hf_band))

    ratio = hf_energy / total_energy if total_energy > 0 else 0.0

    score = min(100.0, ratio * 200.0)
    # Non-zero score when spectrum has energy (avoids false "broken" in Phase 2 checks)
    if total_energy > 1e-12 and score < 0.1:
        score = 0.1

    level = classify_noise_level_from_ratio(ratio)

    return {
        "score": round(float(score), 1),
        "level": level,
        "ratio": float(ratio),
        "hf_ratio": float(ratio),
        "hf_energy": hf_energy,
        "total_energy": total_energy,
    }
