"""Flight split + selection extracted from AeroTuner ``backend/routes/analyze.py`` (WU4)."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from gyrocore.analysis.flight_split import split_samples_into_flights
from gyrocore.analysis.metrics_engine import samples_dict_from_normalized_rows
from gyrocore.analysis.quality_engine_v2 import (
    _flight_selection_quality_report,
    evaluate_quality_light,
)

logger = logging.getLogger(__name__)


def quality_engine_fallback(reason: str) -> dict[str, Any]:
    """Donor ``_quality_engine_fallback``."""
    return {
        "score": 0.0,
        "grade": "D",
        "status": "low_quality",
        "ready": False,
        "issues": [reason],
        "warnings": [],
        "metrics": {
            "duration_s": 0.0,
            "stick_activity": 0.0,
            "throttle_variation": 0.0,
            "gyro_activity": 0.0,
            "segment_diversity": 0.0,
            "jitter": 0.0,
            "propwash_score": 0.0,
            "spectral_noise_score": 0.0,
            "segment_score": 0.0,
        },
        "components": {},
    }


def flight_duration_seconds_from_t(samples: list[dict]) -> float:
    """Wall duration from first to last valid integer ``t`` (microseconds)."""
    ts: list[int] = []
    for s in samples:
        if not isinstance(s, dict):
            continue
        try:
            ts.append(int(s["t"]))
        except (KeyError, TypeError, ValueError):
            continue
    if len(ts) < 2:
        return 0.0
    return max(0.0, float(ts[-1] - ts[0]) / 1e6)


def compute_activity_score(samples: list[dict]) -> float:
    """Donor ``_compute_activity_score``."""
    if not samples or len(samples) < 50:
        return 0.0

    gx = np.array([s.get("gx", 0.0) for s in samples])
    gy = np.array([s.get("gy", 0.0) for s in samples])
    gz = np.array([s.get("gz", 0.0) for s in samples])

    throttle = np.asarray(
        [s.get("throttle", 0.0) for s in samples],
        dtype=float,
    )
    if throttle.max() > 10:
        throttle = (throttle - 1000.0) / 1000.0

    rc_roll = np.array(
        [s.get("rcCommand[0]") or s.get("setpoint_roll", 0.0) for s in samples],
        dtype=float,
    )
    rc_pitch = np.array(
        [s.get("rcCommand[1]") or s.get("setpoint_pitch", 0.0) for s in samples],
        dtype=float,
    )
    rc_yaw = np.array(
        [s.get("rcCommand[2]") or s.get("setpoint_yaw", 0.0) for s in samples],
        dtype=float,
    )

    movement = np.mean(np.abs(gx) + np.abs(gy) + np.abs(gz))
    movement_score = min(movement / 200.0, 1.0)
    throttle_var = np.std(throttle)
    throttle_score = min(throttle_var / 0.5, 1.0)
    stick = np.mean(np.abs(rc_roll) + np.abs(rc_pitch) + np.abs(rc_yaw))
    stick_score = min(stick / 300.0, 1.0)

    return movement_score * 0.5 + throttle_score * 0.3 + stick_score * 0.2


def flight_samples_from_split(
    flights: list,
    index: int,
) -> list[dict] | None:
    if index < 0 or index >= len(flights):
        return None
    flight = flights[index]
    if isinstance(flight, dict):
        seg = flight.get("samples")
        return seg if isinstance(seg, list) else None
    return flight if isinstance(flight, list) else None


def select_best_flight_for_analysis(
    samples: list[dict],
    *,
    requested_index: int | None = None,
) -> tuple[list[dict], dict[str, Any], int, int]:
    """
    Split multi-flight logs and select the analysis segment.

    Returns ``(selected_samples, quality_report, flight_count, selected_flight_index)``.
    """
    flights = split_samples_into_flights(samples)
    if len(flights) <= 1:
        chunk = samples
        n_reported = max(len(flights), 1)
        try:
            matrices = samples_dict_from_normalized_rows(chunk)
            lite = evaluate_quality_light(matrices)
            q = _flight_selection_quality_report(matrices, light_score=lite)
        except Exception as exc:
            logger.warning("_select_best_flight: flight selection quality failed: %s", exc)
            q = quality_engine_fallback("Quality evaluation failed")
        return chunk, q, n_reported, 0

    scored_flights: list[dict[str, Any]] = []
    for i, f in enumerate(flights):
        seg = f["samples"] if isinstance(f, dict) else f
        if not seg or len(seg) < 100:
            continue
        activity = compute_activity_score(seg)
        try:
            duration = float(seg[-1]["t"] - seg[0]["t"]) / 1e6 if len(seg) > 1 else 0.0
        except (KeyError, TypeError, ValueError):
            duration = flight_duration_seconds_from_t(seg)
        scored_flights.append(
            {"flight": f, "activity": activity, "duration": duration, "index": i}
        )

    if not scored_flights:
        for i, f in enumerate(flights):
            seg = f["samples"] if isinstance(f, dict) else f
            if not seg:
                continue
            activity = compute_activity_score(seg)
            try:
                duration = float(seg[-1]["t"] - seg[0]["t"]) / 1e6 if len(seg) > 1 else 0.0
            except (KeyError, TypeError, ValueError):
                duration = flight_duration_seconds_from_t(seg)
            scored_flights.append(
                {"flight": f, "activity": activity, "duration": duration, "index": i}
            )

    if not scored_flights:
        try:
            matrices = samples_dict_from_normalized_rows(samples)
            lite = evaluate_quality_light(matrices)
            q = _flight_selection_quality_report(matrices, light_score=lite)
        except Exception as exc:
            logger.warning("_select_best_flight: flight selection quality failed: %s", exc)
            q = quality_engine_fallback("Quality evaluation failed")
        return samples, q, len(flights), 0

    active_flights = [f for f in scored_flights if f["activity"] > 0.2]
    if active_flights:
        best = max(active_flights, key=lambda x: (x["activity"], x["duration"]))
    else:
        best = max(scored_flights, key=lambda x: (x["duration"],))

    selected_idx = int(best["index"])
    if requested_index is not None:
        try:
            req_idx = int(requested_index)
        except (TypeError, ValueError):
            req_idx = -1
        if 0 <= req_idx < len(flights):
            manual = flight_samples_from_split(flights, req_idx)
            if manual:
                selected_idx = req_idx
                chosen = manual
            else:
                selected_flight = best["flight"]
                chosen = (
                    selected_flight["samples"]
                    if isinstance(selected_flight, dict)
                    else selected_flight
                )
        else:
            selected_flight = best["flight"]
            chosen = (
                selected_flight["samples"]
                if isinstance(selected_flight, dict)
                else selected_flight
            )
    else:
        selected_flight = best["flight"]
        chosen = (
            selected_flight["samples"]
            if isinstance(selected_flight, dict)
            else selected_flight
        )

    try:
        matrices = samples_dict_from_normalized_rows(chosen)
        lite = evaluate_quality_light(matrices)
        q = _flight_selection_quality_report(matrices, light_score=lite)
    except Exception as exc:
        logger.warning(
            "_select_best_flight: flight selection quality failed flight_index=%s: %s",
            selected_idx,
            exc,
        )
        q = quality_engine_fallback("Quality evaluation failed")

    return chosen, q, len(flights), selected_idx
