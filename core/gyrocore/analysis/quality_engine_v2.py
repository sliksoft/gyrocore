# GyroCore WU4: adapted from AeroTuner backend/analysis/quality_engine_v2.py
"""
Unified flight log quality (v2): time-domain, spectral noise, propwash, segments.

Replaces dual use of ``quality_engine.evaluate_quality`` and penalty-based
``_evaluate_log_quality`` in the analyze route. Does not remove ``evaluate_quality``.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from gyrocore.analysis import quality_engine as qe


def _grade_from_score_v2(score: float) -> str:
    if score >= 85.0:
        return "A"
    if score >= 70.0:
        return "B"
    if score >= 55.0:
        return "C"
    return "D"


def _status_from_score_v2(score: float) -> str:
    if score >= 65.0:
        return "ok"
    if score >= 50.0:
        return "low_confidence"
    return "low_quality"


def _empty_metrics() -> dict[str, float]:
    return {
        "duration_s": 0.0,
        "stick_activity": 0.0,
        "throttle_variation": 0.0,
        "gyro_activity": 0.0,
        "segment_diversity": 0.0,
        "jitter": 0.0,
        "propwash_score": 0.0,
        "spectral_noise_score": 0.0,
        "segment_score": 0.0,
    }


def _empty_quality_result() -> dict[str, Any]:
    return {
        "score": 0.0,
        "grade": "D",
        "status": "low_quality",
        "ready": False,
        "issues": ["No valid samples in log"],
        "warnings": [],
        "metrics": _empty_metrics(),
        "components": {},
    }


def _segment_type_score_from_segments(segments: Any) -> float:
    if not isinstance(segments, dict):
        return 50.0
    raw = segments.get("segments")
    if not isinstance(raw, list) or not raw:
        return 50.0
    types: set[str] = set()
    for seg in raw:
        if isinstance(seg, dict) and seg.get("type") is not None:
            types.add(str(seg["type"]))
    num_types = len(types)
    if num_types >= 4:
        segment_score = 100.0
    elif num_types == 3:
        segment_score = 85.0
    elif num_types == 2:
        segment_score = 65.0
    elif num_types == 1:
        segment_score = 50.0
    else:
        segment_score = 50.0
    return float(segment_score)


def _time_domain_bundle(samples_matrices: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(samples_matrices, dict):
        return None
    n, gyro, sp, throttle, time_us = qe._align_samples(samples_matrices)
    if n < 2:
        return None
    setpoint_mag = qe._row_norm_xyz(sp)
    gyro_mag = qe._row_norm_xyz(gyro)
    if setpoint_mag.size != n or gyro_mag.size != n:
        return None

    duration_s = qe._duration_seconds(time_us)
    stick_activity = qe._normalize_activity_rms(setpoint_mag)
    throttle_var = qe._throttle_variation(throttle)
    gyro_activity = qe._normalize_activity_rms(gyro_mag)
    diversity = qe._segment_diversity(setpoint_mag, gyro_mag, throttle, time_us)
    jitter = qe._gyro_jitter_index(gyro_mag)

    duration_sc = qe._duration_score(duration_s)
    stick_sc = 100.0 * stick_activity
    throttle_sc = 100.0 * throttle_var
    motion_bump = qe._quadratic_bump(gyro_activity, center=0.42, half_width=0.55)
    gyro_motion_sc = 100.0 * motion_bump
    gyro_sc = float(
        np.clip(gyro_motion_sc * (1.0 - 0.55 * jitter), 0.0, 100.0),
    )
    diversity_sc = 100.0 * diversity

    return {
        "duration_s": float(duration_s),
        "stick_activity": float(stick_activity),
        "throttle_variation": float(throttle_var),
        "gyro_activity": float(gyro_activity),
        "segment_diversity": float(diversity),
        "jitter": float(jitter),
        "duration_sc": float(duration_sc),
        "stick_sc": float(stick_sc),
        "throttle_sc": float(throttle_sc),
        "gyro_sc": float(gyro_sc),
        "diversity_sc": float(diversity_sc),
    }


def _light_score_from_bundle(td: dict[str, Any]) -> float:
    score = (
        float(td["duration_sc"]) * 0.25
        + float(td["stick_sc"]) * 0.25
        + float(td["throttle_sc"]) * 0.15
        + float(td["gyro_sc"]) * 0.20
        + float(td["diversity_sc"]) * 0.15
    )
    s = float(np.clip(score, 0.0, 100.0))
    if not np.isfinite(s):
        return 0.0
    return s


def evaluate_quality_light(samples_matrices: dict) -> float:
    """
    Lightweight quality score for flight selection ONLY.
    Uses ONLY time-domain metrics.
    Returns score 0–100.
    """
    td = _time_domain_bundle(samples_matrices)
    if td is None:
        return 0.0
    return _light_score_from_bundle(td)


def _issues_warnings_from_time_domain(td: dict[str, Any]) -> tuple[list[str], list[str]]:
    issues: list[str] = []
    warnings: list[str] = []
    duration_s = float(td["duration_s"])
    stick_activity = float(td["stick_activity"])
    throttle_var = float(td["throttle_variation"])
    diversity = float(td["segment_diversity"])
    gyro_activity = float(td["gyro_activity"])
    jitter = float(td["jitter"])

    if duration_s < 12.0:
        issues.append("Flight duration too short for reliable analysis")
    elif duration_s < 25.0:
        warnings.append("Flight duration is on the short side for robust tuning")

    if stick_activity < 0.12:
        issues.append("Very low stick activity (no maneuvers detected)")
    elif stick_activity < 0.22:
        warnings.append("Stick activity is low; log may be mostly cruise or hover")

    if throttle_var < 0.14:
        warnings.append("Limited throttle range used")
    if diversity < 0.30:
        warnings.append("Low segment diversity (few distinct flight behaviors)")

    if gyro_activity < 0.08 and duration_s >= 12.0:
        issues.append("Very low gyro activity (aircraft may be static or log unusable)")

    if jitter > 0.72:
        issues.append("Gyro signal appears excessively noisy or glitchy")
    elif jitter > 0.45:
        warnings.append("Elevated gyro roughness; check vibrations or logging issues")

    return issues, warnings


def _flight_selection_quality_report(
    samples_matrices: dict[str, Any],
    *,
    light_score: float | None = None,
) -> dict[str, Any]:
    """
    v2-shaped quality dict for pre-``_build_response`` gating; ``score`` matches
    :func:`evaluate_quality_light` (pass ``light_score`` from that call to avoid
    recomputing the scalar). Spectral/propwash/segment metrics are neutral
    placeholders (not used in the light score).
    """
    td = _time_domain_bundle(samples_matrices)
    if td is None:
        return dict(_empty_quality_result())

    if light_score is not None and np.isfinite(light_score):
        light = float(np.clip(float(light_score), 0.0, 100.0))
    else:
        light = _light_score_from_bundle(td)
    if not np.isfinite(light):
        light = 0.0
    light = float(np.clip(light, 0.0, 100.0))

    issues, warnings = _issues_warnings_from_time_domain(td)
    grade = _grade_from_score_v2(light)
    status = _status_from_score_v2(light)
    ready = status == "ok"

    neutral_ps = 100.0
    neutral_spec = 100.0
    neutral_seg = 50.0

    components: dict[str, float] = {
        "duration": float(np.clip(td["duration_sc"], 0.0, 100.0)),
        "stick": float(np.clip(td["stick_sc"], 0.0, 100.0)),
        "throttle": float(np.clip(td["throttle_sc"], 0.0, 100.0)),
        "gyro": float(np.clip(td["gyro_sc"], 0.0, 100.0)),
        "diversity": float(np.clip(td["diversity_sc"], 0.0, 100.0)),
        "propwash": neutral_ps,
        "spectral": neutral_spec,
        "segments": neutral_seg,
    }
    for k, v in list(components.items()):
        if not np.isfinite(v):
            components[k] = 0.0

    metrics = {
        "duration_s": float(td["duration_s"]) if np.isfinite(td["duration_s"]) else 0.0,
        "stick_activity": float(td["stick_activity"]) if np.isfinite(td["stick_activity"]) else 0.0,
        "throttle_variation": float(td["throttle_variation"])
        if np.isfinite(td["throttle_variation"])
        else 0.0,
        "gyro_activity": float(td["gyro_activity"]) if np.isfinite(td["gyro_activity"]) else 0.0,
        "segment_diversity": float(td["segment_diversity"])
        if np.isfinite(td["segment_diversity"])
        else 0.0,
        "jitter": float(td["jitter"]) if np.isfinite(td["jitter"]) else 0.0,
        "propwash_score": neutral_ps,
        "spectral_noise_score": neutral_spec,
        "segment_score": neutral_seg,
    }

    return {
        "score": light,
        "grade": grade,
        "status": status,
        "ready": bool(ready),
        "issues": issues,
        "warnings": warnings,
        "metrics": metrics,
        "components": components,
    }


def evaluate_quality_v2(
    samples_matrices: dict[str, Any],
    samples_raw: list[dict],
    analysis: dict[str, Any],
) -> dict[str, Any]:
    """
    Single quality model: score 0–100, grade A–D, status, ready.

    ``analysis`` may include:
    - ``propwash``: dict with ``score`` in [0, 1] (unified propwash)
    - ``noise``: dict with ``value`` in [0, 100] (metrics noise cleanliness)
    - ``segments``: optional ``detect_segments``-shaped dict; if absent or empty,
      segment contribution is neutral (no extra segment detection here).
    """
    base_empty = _empty_quality_result()

    if not isinstance(samples_matrices, dict):
        return dict(base_empty)

    td = _time_domain_bundle(samples_matrices)
    if td is None:
        return dict(base_empty)

    duration_s = float(td["duration_s"])
    stick_activity = float(td["stick_activity"])
    throttle_var = float(td["throttle_variation"])
    gyro_activity = float(td["gyro_activity"])
    diversity = float(td["segment_diversity"])
    jitter = float(td["jitter"])
    duration_sc = float(td["duration_sc"])
    stick_sc = float(td["stick_sc"])
    throttle_sc = float(td["throttle_sc"])
    gyro_sc = float(td["gyro_sc"])
    diversity_sc = float(td["diversity_sc"])

    ana = analysis if isinstance(analysis, dict) else {}

    pw_data = ana.get("propwash")
    propwash_score = 100.0
    if isinstance(pw_data, dict) and "score" in pw_data and pw_data.get("score") is not None:
        try:
            pw = float(pw_data["score"])
        except (TypeError, ValueError):
            pw = float("nan")
        if np.isfinite(pw):
            pw = float(np.clip(pw, 0.0, 1.0))
            propwash_score = float(np.clip(100.0 * (1.0 - pw), 0.0, 100.0))
        if not np.isfinite(propwash_score):
            propwash_score = 100.0

    nz = ana.get("noise")
    noise_val = 50.0
    if isinstance(nz, dict):
        try:
            noise_val = float(nz.get("value", 50.0) or 50.0)
        except (TypeError, ValueError):
            noise_val = 50.0
    if not np.isfinite(noise_val):
        noise_val = 50.0
    noise_val = float(np.clip(noise_val, 0.0, 100.0))
    nv = noise_val / 100.0
    spectral_noise_score = float(np.clip(100.0 * (1.0 - nv**1.5), 0.0, 100.0))
    if not np.isfinite(spectral_noise_score):
        spectral_noise_score = 50.0

    seg_payload = ana.get("segments")
    if (
        isinstance(seg_payload, dict)
        and isinstance(seg_payload.get("segments"), list)
        and seg_payload["segments"]
    ):
        segment_score = _segment_type_score_from_segments(seg_payload)
    else:
        segment_score = 50.0
    if not np.isfinite(segment_score):
        segment_score = 50.0
    segment_score = float(np.clip(segment_score, 0.0, 100.0))

    w_duration = 0.15
    w_stick = 0.20
    w_throttle = 0.10
    w_gyro = 0.15
    w_diversity = 0.10
    w_propwash = 0.10
    w_spectral = 0.15
    w_segments = 0.05

    components: dict[str, float] = {
        "duration": float(np.clip(duration_sc, 0.0, 100.0)),
        "stick": float(np.clip(stick_sc, 0.0, 100.0)),
        "throttle": float(np.clip(throttle_sc, 0.0, 100.0)),
        "gyro": float(np.clip(gyro_sc, 0.0, 100.0)),
        "diversity": float(np.clip(diversity_sc, 0.0, 100.0)),
        "propwash": float(np.clip(propwash_score, 0.0, 100.0)),
        "spectral": float(np.clip(spectral_noise_score, 0.0, 100.0)),
        "segments": float(np.clip(segment_score, 0.0, 100.0)),
    }
    for k, v in list(components.items()):
        if not np.isfinite(v):
            components[k] = 0.0

    score = (
        w_duration * components["duration"]
        + w_stick * components["stick"]
        + w_throttle * components["throttle"]
        + w_gyro * components["gyro"]
        + w_diversity * components["diversity"]
        + w_propwash * components["propwash"]
        + w_spectral * components["spectral"]
        + w_segments * components["segments"]
    )
    score = float(np.clip(score, 0.0, 100.0))

    grade = _grade_from_score_v2(score)
    status = _status_from_score_v2(score)
    ready = status == "ok"

    issues, warnings = _issues_warnings_from_time_domain(td)

    if not np.isfinite(score):
        score = 0.0
        grade = "D"
        status = "low_quality"
        ready = False
        issues.append("Quality score computation produced non-finite values")

    return {
        "score": float(score),
        "grade": grade,
        "status": status,
        "ready": bool(ready),
        "issues": issues,
        "warnings": warnings,
        "metrics": {
            "duration_s": float(duration_s) if np.isfinite(duration_s) else 0.0,
            "stick_activity": float(stick_activity) if np.isfinite(stick_activity) else 0.0,
            "throttle_variation": float(throttle_var) if np.isfinite(throttle_var) else 0.0,
            "gyro_activity": float(gyro_activity) if np.isfinite(gyro_activity) else 0.0,
            "segment_diversity": float(diversity) if np.isfinite(diversity) else 0.0,
            "jitter": float(jitter) if np.isfinite(jitter) else 0.0,
            "propwash_score": float(propwash_score) if np.isfinite(propwash_score) else 100.0,
            "spectral_noise_score": float(spectral_noise_score)
            if np.isfinite(spectral_noise_score)
            else 50.0,
            "segment_score": float(segment_score) if np.isfinite(segment_score) else 50.0,
        },
        "components": components,
    }
