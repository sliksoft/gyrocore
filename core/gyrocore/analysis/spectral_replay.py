# GyroCore WU4: adapted from AeroTuner backend/analysis/spectral_replay.py
"""Golden/replay comparison helpers for compact spectral evidence.

These helpers are intentionally separate from production parsing and analysis.
They quantify how the current even-subsampling sample cap can affect compact
Welch PSD evidence before parser caps or model-backed analysis are changed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from gyrocore.analysis.spectral_windows import build_spectral_evidence_from_samples


Quality = str


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out):
        return None
    return out


def _dedupe_warnings(warnings: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(w) for w in warnings if isinstance(w, str) and w.strip()))


def _quality_from_score(score: float) -> Quality:
    if score >= 0.8:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def _peak_hz(peak: Mapping[str, Any]) -> float | None:
    hz = _safe_float(peak.get("hz"))
    if hz is None:
        hz = _safe_float(peak.get("freq"))
    if hz is None or hz <= 0:
        return None
    return hz


def _compact_peak(peak: Mapping[str, Any]) -> dict[str, Any]:
    hz = _peak_hz(peak)
    return {
        "hz": round(hz, 3) if hz is not None else None,
        "confidence": peak.get("confidence") if isinstance(peak.get("confidence"), str) else None,
    }


def _normalized_peaks(peaks: Any) -> list[dict[str, Any]]:
    if not isinstance(peaks, Sequence) or isinstance(peaks, (str, bytes, bytearray)):
        return []
    out: list[dict[str, Any]] = []
    for peak in peaks:
        if not isinstance(peak, Mapping):
            continue
        hz = _peak_hz(peak)
        if hz is None:
            continue
        out.append(
            {
                "hz": hz,
                "confidence": peak.get("confidence") if isinstance(peak.get("confidence"), str) else None,
            }
        )
    meaningful = [peak for peak in out if peak.get("confidence") in {"high", "medium"}]
    selected = meaningful or out
    selected.sort(key=lambda item: float(item["hz"]))
    return selected


def compare_peak_sets(
    reference_peaks: Any,
    candidate_peaks: Any,
    tolerance_pct: float = 0.05,
) -> dict[str, Any]:
    """Compare compact dominant peak lists and score frequency stability."""
    tolerance = _safe_float(tolerance_pct)
    if tolerance is None or tolerance <= 0:
        tolerance = 0.05

    reference = _normalized_peaks(reference_peaks)
    candidate = _normalized_peaks(candidate_peaks)
    used_candidate: set[int] = set()
    matched: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []

    for ref in reference:
        ref_hz = float(ref["hz"])
        best_idx: int | None = None
        best_error: float | None = None
        for idx, cand in enumerate(candidate):
            if idx in used_candidate:
                continue
            cand_hz = float(cand["hz"])
            error = abs(cand_hz - ref_hz) / ref_hz
            if error <= tolerance and (best_error is None or error < best_error):
                best_idx = idx
                best_error = error
        if best_idx is None or best_error is None:
            missing.append(_compact_peak(ref))
            continue
        used_candidate.add(best_idx)
        cand = candidate[best_idx]
        matched.append(
            {
                "reference_hz": round(ref_hz, 3),
                "candidate_hz": round(float(cand["hz"]), 3),
                "error_percent": round(best_error * 100.0, 4),
                "reference_confidence": ref.get("confidence"),
                "candidate_confidence": cand.get("confidence"),
            }
        )

    extra = [_compact_peak(peak) for idx, peak in enumerate(candidate) if idx not in used_candidate]
    errors = [float(item["error_percent"]) for item in matched]
    average_error = round(sum(errors) / len(errors), 4) if errors else None
    worst_error = round(max(errors), 4) if errors else None

    if not reference and not candidate:
        stability = 1.0
    else:
        denominator = max(1, len(reference) + len(extra))
        match_ratio = len(matched) / denominator
        error_penalty = 0.0
        if average_error is not None:
            error_penalty = min(1.0, (average_error / 100.0) / tolerance)
        stability = max(0.0, min(1.0, match_ratio * (1.0 - error_penalty * 0.5)))
    stability = round(stability, 4)

    warnings: list[str] = []
    if missing:
        warnings.append("Candidate spectral evidence is missing reference peaks.")
    if extra:
        warnings.append("Candidate spectral evidence contains extra unmatched peaks.")
    if worst_error is not None and worst_error > tolerance * 100.0 * 0.75:
        warnings.append("Matched spectral peak drift is close to the replay tolerance.")

    return {
        "matched": matched,
        "missing_reference_peaks": missing,
        "extra_candidate_peaks": extra,
        "average_error_percent": average_error,
        "worst_error_percent": worst_error,
        "stability_score": stability,
        "quality": _quality_from_score(stability),
        "warnings": _dedupe_warnings(warnings),
    }


def _band_peaks(evidence: Mapping[str, Any], band: str) -> Any:
    throttle_bands = evidence.get("throttle_bands")
    if not isinstance(throttle_bands, Mapping):
        return []
    block = throttle_bands.get(band)
    if not isinstance(block, Mapping):
        return []
    return block.get("peaks") or []


def compare_spectral_evidence(
    reference: Any,
    candidate: Any,
    tolerance_pct: float = 0.05,
) -> dict[str, Any]:
    """Compare two compact ``spectral_evidence`` payloads."""
    ref = reference if isinstance(reference, Mapping) else {}
    cand = candidate if isinstance(candidate, Mapping) else {}
    warnings: list[str] = []

    dominant = compare_peak_sets(ref.get("dominant_peaks"), cand.get("dominant_peaks"), tolerance_pct)
    warnings.extend(f"dominant_peaks: {warning}" for warning in dominant["warnings"])

    throttle: dict[str, dict[str, Any]] = {}
    for band in ("low", "mid", "high"):
        comparison = compare_peak_sets(_band_peaks(ref, band), _band_peaks(cand, band), tolerance_pct)
        throttle[band] = comparison
        warnings.extend(f"throttle_{band}: {warning}" for warning in comparison["warnings"])

    persistence = compare_peak_sets(ref.get("persistence"), cand.get("persistence"), tolerance_pct)
    warnings.extend(f"persistence: {warning}" for warning in persistence["warnings"])

    scores = [float(dominant["stability_score"]), float(persistence["stability_score"])]
    scores.extend(float(block["stability_score"]) for block in throttle.values())
    overall = round(sum(scores) / max(1, len(scores)), 4)

    ref_quality = ref.get("quality")
    cand_quality = cand.get("quality")
    if ref_quality == "high" and cand_quality in {"medium", "low"}:
        warnings.append("Candidate spectral quality is lower than the reference.")
    if cand.get("sample_count") is not None and ref.get("sample_count") is not None:
        ref_count = _safe_float(ref.get("sample_count"))
        cand_count = _safe_float(cand.get("sample_count"))
        if ref_count is not None and cand_count is not None and cand_count < ref_count:
            warnings.append("Candidate spectral evidence uses fewer samples than the reference.")

    return {
        "dominant_peak_stability": dominant,
        "throttle_band_stability": throttle,
        "persistence_stability": persistence,
        "overall_stability_score": overall,
        "quality": _quality_from_score(overall),
        "warnings": _dedupe_warnings(warnings),
    }


def downsample_evenly_for_replay(samples: Sequence[Mapping[str, Any]], max_samples: int) -> list[Mapping[str, Any]]:
    """Mirror parser even subsampling for replay-only comparisons."""
    rows = [sample for sample in samples if isinstance(sample, Mapping)]
    if max_samples < 1:
        return []
    n = len(rows)
    if n <= max_samples:
        return rows
    if max_samples == 1:
        return [rows[0]]
    denom = max_samples - 1
    indices = [(k * (n - 1)) // denom for k in range(max_samples)]
    return [rows[i] for i in indices]


def _effective_replay_sample_rate(reference_count: int, candidate_count: int, sample_rate_hz: float) -> float:
    if reference_count < 2 or candidate_count < 2 or sample_rate_hz <= 0:
        return sample_rate_hz
    duration_s = (reference_count - 1) / sample_rate_hz
    if duration_s <= 0:
        return sample_rate_hz
    return (candidate_count - 1) / duration_s


def build_replay_spectral_comparison(
    samples: Sequence[Mapping[str, Any]],
    sample_rate_hz: float,
    max_samples: int = 20000,
) -> dict[str, Any]:
    """Build full-vs-evenly-capped replay evidence and compare compact summaries."""
    rows = [sample for sample in samples if isinstance(sample, Mapping)]
    fs = _safe_float(sample_rate_hz) or 0.0
    reference = build_spectral_evidence_from_samples(rows, fs)
    candidate_samples = downsample_evenly_for_replay(rows, max_samples)
    candidate_fs = _effective_replay_sample_rate(len(rows), len(candidate_samples), fs)
    candidate = build_spectral_evidence_from_samples(
        candidate_samples,
        candidate_fs,
        original_sample_count=len(rows),
    )
    comparison = compare_spectral_evidence(reference, candidate)
    warnings = list(comparison["warnings"])
    if len(candidate_samples) < len(rows):
        warnings.append("Replay candidate simulates parser even subsampling and sample-cap effects.")

    return {
        "version": 1,
        "method": "spectral_replay_even_subsample",
        "reference_sample_count": len(rows),
        "candidate_sample_count": len(candidate_samples),
        "reference_sample_rate_hz": round(fs, 3) if fs > 0 else None,
        "candidate_sample_rate_hz": round(candidate_fs, 3) if candidate_fs > 0 else None,
        "comparison": {
            **comparison,
            "warnings": _dedupe_warnings(warnings),
        },
    }
