"""Analysis evidence entrypoint (WU4) — no tuning recommendations."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from gyrocore.analysis.confidence_unified import compute_unified_confidence
from gyrocore.analysis.d_effectiveness_analysis import analyze_d_effectiveness
from gyrocore.analysis.erpm_analysis import analyze_erpm
from gyrocore.analysis.metrics_engine import (
    build_metrics,
    samples_dict_from_normalized_rows,
    validate_metrics_output,
)
from gyrocore.analysis.motor_diagnostics import compute_per_motor_diagnostics
from gyrocore.analysis.motor_saturation import (
    attach_saturation_evidence_to_response,
    compute_motor_saturation,
)
from gyrocore.analysis.problem_detection_engine import detect_problems
from gyrocore.analysis.quality_engine_v2 import evaluate_quality_v2
from gyrocore.analysis.resonance import analyze_resonance
from gyrocore.analysis.resonance_v2 import detect_resonance_peaks
from gyrocore.analysis.sample_rate_metadata import build_sample_rate_metadata
from gyrocore.analysis.signal_composition import (
    build_signal_analysis,
    compute_spectral_bundle,
    compute_unified_propwash,
    detect_propwash,
    spectral_source_kind,
)
from gyrocore.analysis.segment_engine import detect_segments
from gyrocore.analysis.signal import compute_sample_rate, time_us_to_seconds
from gyrocore.analysis.spectral_windows import build_spectral_evidence_from_samples
from gyrocore.analysis.step_response_analysis import analyze_step_response
from gyrocore.preprocess.flight_selection import select_best_flight_for_analysis
from gyrocore.preprocess.normalize import normalize_raw_samples

logger = logging.getLogger(__name__)


def _extract_motor_data(samples: list[dict]) -> list[list[float]] | None:
    rows: list[list[float]] = []
    for s in samples:
        m = s.get("motors")
        if not isinstance(m, (list, tuple)) or len(m) < 4:
            continue
        chunk = m[:4]
        if any(x is None for x in chunk):
            continue
        try:
            rows.append([float(x) for x in chunk])
        except (TypeError, ValueError):
            continue
    return rows if rows else None


def build_analysis_evidence(
    raw_samples: list[dict] | None,
    *,
    gyro_source_is_raw_adc: bool | None = None,
    requested_flight_index: int | None = None,
    hardware: Mapping[str, Any] | None = None,
    user_inputs: Mapping[str, Any] | None = None,
    raw_sample_count: int | None = None,
) -> dict[str, Any]:
    """
    Deterministic analysis evidence from decoded samples.

    ``raw_sample_count`` is the original log row count when the caller capped the
    samples before analysis; it marks the spectral source as capped.

    Does **not** produce PID/filter targets, tune CLI, or safety verdicts.
    """
    normalized, gyro_meta = normalize_raw_samples(
        raw_samples,
        gyro_source_is_raw_adc=gyro_source_is_raw_adc,
    )
    empty = {
        "ok": False,
        "message": "no_usable_samples",
        "gyro_scale": gyro_meta,
        "selected_flight": None,
        "quality": None,
        "spectral": None,
        "resonance": None,
        "erpm": None,
        "motors": None,
        "step_response": None,
        "d_effectiveness": None,
        "saturation": None,
        "problems": None,
        "metrics": None,
        "confidence": None,
        "sample_rate_metadata": None,
        "signal": None,
    }
    if not normalized:
        return empty

    selected, selection_quality, flight_count, selected_idx = select_best_flight_for_analysis(
        normalized,
        requested_index=requested_flight_index,
    )
    time_seconds = time_us_to_seconds([float(s.get("t", 0.0)) for s in selected])
    sample_rate_hz = float(compute_sample_rate(time_seconds)) if len(time_seconds) >= 2 else 0.0
    sample_rate_meta = build_sample_rate_metadata(
        selected,
        raw_sample_count=raw_sample_count,
        analyzed_sample_count=len(selected),
        display_sample_count=len(selected),
        spectral_sample_count=len(selected),
        source_kind=spectral_source_kind(len(raw_samples or []), raw_sample_count),
    )

    matrices = samples_dict_from_normalized_rows(selected)
    try:
        segments = detect_segments(matrices)
    except Exception as exc:
        logger.warning("detect_segments failed: %s", exc)
        segments = {"segments": [], "summary": {}}

    try:
        quality = evaluate_quality_v2(matrices, selected, {})
    except Exception as exc:
        logger.warning("evaluate_quality_v2 failed: %s", exc)
        quality = selection_quality

    spectral = build_spectral_evidence_from_samples(selected, sample_rate_hz)

    # One spectral bundle feeds the resonance module, per-axis noise and peaks.
    bundle = compute_spectral_bundle(selected)
    gx = bundle["gx"]
    freqs, spectrum = bundle["merged_freqs"], bundle["merged_spectrum"]
    try:
        resonance = analyze_resonance(freqs, spectrum, gx, bundle["fs"])
    except Exception as exc:
        logger.warning("analyze_resonance failed: %s", exc)
        resonance = {"ok": False, "message": str(exc)}
    try:
        resonance_peaks = detect_resonance_peaks(freqs, spectrum)
    except Exception as exc:
        logger.warning("detect_resonance_peaks failed: %s", exc)
        resonance_peaks = []

    erpm = analyze_erpm(selected)
    signal = build_signal_analysis(
        bundle,
        resonance if isinstance(resonance, dict) else None,
        erpm,
        sample_rate_meta,
    )
    signal["propwash"] = compute_unified_propwash(
        detect_propwash(selected), signal.get("propwash_level", 0.5)
    )
    motor_data = _extract_motor_data(selected)
    motor_stats = compute_motor_saturation(motor_data)
    hw: Mapping[str, Any] = hardware if isinstance(hardware, Mapping) else {}
    if not hw and isinstance(user_inputs, Mapping):
        raw_hw = user_inputs.get("hardware")
        hw = raw_hw if isinstance(raw_hw, Mapping) else {}
    motor_diagnostics = compute_per_motor_diagnostics(
        motor_data,
        samples=selected,
        hardware_class=hw.get("hardware_class") if isinstance(hw, Mapping) else None,
    )

    try:
        step = analyze_step_response(matrices, segments)
    except Exception as exc:
        logger.warning("analyze_step_response failed: %s", exc)
        step = analyze_step_response({}, None)

    analysis_for_metrics: dict[str, Any] = {
        "resonance_module": resonance if isinstance(resonance, dict) else {},
        "motor_diagnostics": motor_diagnostics,
        "motor_health": max(
            0.0, min(100.0, 100.0 - float(motor_stats.get("saturation_pct") or 0.0))
        ),
        "sample_rate_hz": sample_rate_hz,
        "noise_model": signal["noise_model"],
        "fft_peaks": signal["fft_peaks"],
        "resonance_v2_hz": signal["resonance_v2_hz"],
        "propwash": signal["propwash"],
    }
    fft_data = {
        "freqs": freqs.tolist() if hasattr(freqs, "tolist") else list(freqs),
        "amps": spectrum.tolist() if hasattr(spectrum, "tolist") else list(spectrum),
    }
    try:
        metrics = build_metrics(matrices, analysis_for_metrics, fft_data)
        validation = validate_metrics_output(metrics)
        if not validation.get("valid", True):
            logger.warning("metrics validation failed: %s", validation.get("issues"))
    except Exception as exc:
        logger.warning("build_metrics failed: %s", exc)
        metrics = {}

    try:
        d_eff = analyze_d_effectiveness(
            matrices,
            analysis_for_metrics,
            response_analysis=step if isinstance(step, dict) else None,
            segments=segments if isinstance(segments, dict) else None,
        )
    except Exception as exc:
        logger.warning("analyze_d_effectiveness failed: %s", exc)
        d_eff = {}

    saturation_evidence: dict[str, Any] = dict(motor_stats) if isinstance(motor_stats, dict) else {}
    if isinstance(metrics, dict) and isinstance(step, dict):
        metrics = dict(metrics)
        metrics["response"] = step
        metrics["d_effectiveness"] = d_eff
        try:
            step_aug, saturation_evidence = attach_saturation_evidence_to_response(
                step, motor_data
            )
            metrics["response"] = step_aug
            step = step_aug
        except Exception as exc:
            logger.warning("attach_saturation_evidence_to_response failed: %s", exc)

    try:
        problems = detect_problems(
            metrics if isinstance(metrics, dict) else {},
            segments if isinstance(segments, dict) else {"segments": [], "summary": {}},
        )
    except Exception as exc:
        logger.warning("detect_problems failed: %s", exc)
        problems = {"problems": [], "error": str(exc)}

    try:
        primary = resonance.get("primary") if isinstance(resonance, dict) else None
        conf = float((primary or {}).get("confidence", 0.5) or 0.5)
    except (TypeError, ValueError):
        conf = 0.5
    if conf != conf:  # NaN
        conf = 0.5
    confidence = compute_unified_confidence(conf, analysis_for_metrics)

    return {
        "ok": True,
        "message": None,
        "gyro_scale": gyro_meta,
        "selected_flight": {
            "index": selected_idx,
            "count": flight_count,
            "sample_count": len(selected),
            "selection_quality": selection_quality,
        },
        "samples": selected,
        "quality": quality,
        "spectral": spectral,
        "resonance": resonance,
        "resonance_peaks": resonance_peaks,
        "erpm": erpm,
        "motors": {
            "saturation": motor_stats,
            "diagnostics": motor_diagnostics,
        },
        "step_response": step,
        "d_effectiveness": d_eff,
        "saturation": saturation_evidence,
        "problems": problems,
        "metrics": metrics,
        "confidence": confidence,
        "sample_rate_hz": sample_rate_hz,
        "sample_rate_metadata": sample_rate_meta,
        "signal": signal,
        "segments": segments,
        "fft": fft_data,
    }
