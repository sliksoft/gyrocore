"""Public entry: ``analyze_filter_evidence`` — non-actionable diagnostics only."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import numpy as np

from gyrocore.analysis.betaflight_filter_model import parse_filter_state

from .candidate import analyze_dynamic_lowpass_evidence, build_filter_candidate
from .constants import MAX_SEGMENTS, PROVENANCE
from .group_delay import estimate_group_delay
from .models import FilterCandidate, FilterEvidenceResult, SpectralPeak
from .noise import analyze_axis_noise
from .segments import select_analysis_segments


def _extract_series(
    samples: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
) -> np.ndarray:
    out: list[float] = []
    for row in samples:
        if not isinstance(row, Mapping):
            continue
        val = None
        for key in keys:
            if key in row and row[key] is not None:
                try:
                    val = float(row[key])
                    break
                except (TypeError, ValueError):
                    continue
        if val is not None and np.isfinite(val):
            out.append(val)
    return np.asarray(out, dtype=float)


def _sample_rate(samples: Sequence[Mapping[str, Any]], explicit: float | None) -> float:
    if explicit is not None and explicit > 0:
        return float(explicit)
    times: list[float] = []
    for row in samples:
        if not isinstance(row, Mapping):
            continue
        for key in ("time", "time_s", "timestamp_s"):
            if key in row:
                try:
                    times.append(float(row[key]))
                    break
                except (TypeError, ValueError):
                    pass
    if len(times) >= 2:
        dt = (times[-1] - times[0]) / max(1, len(times) - 1)
        if dt > 0:
            return 1.0 / dt
    return 0.0


def analyze_filter_evidence(
    samples: Sequence[Mapping[str, Any]],
    *,
    sample_rate_hz: float | None = None,
    headers: str | None = None,
    cli_dump: str | None = None,
    filter_state: Mapping[str, Any] | None = None,
    throttle_band_noise: list[dict[str, float]] | None = None,
) -> FilterEvidenceResult:
    """Structured filter evidence. Always ``actionable=False``."""
    warnings: list[str] = []
    fs = _sample_rate(samples, sample_rate_hz)
    gyro_r = _extract_series(samples, ("gyroADC[0]", "gyro_roll", "gyro[0]"))
    gyro_p = _extract_series(samples, ("gyroADC[1]", "gyro_pitch", "gyro[1]"))
    gyro_y = _extract_series(samples, ("gyroADC[2]", "gyro_yaw", "gyro[2]"))
    throttle = _extract_series(samples, ("rcCommand[3]", "setpoint[3]", "throttle", "rcCommands[3]"))
    if throttle.size == 0:
        throttle = np.zeros(gyro_r.size, dtype=float)

    n = int(min(gyro_r.size, gyro_p.size, gyro_y.size, throttle.size if throttle.size else gyro_r.size))
    gyro_r, gyro_p, gyro_y = gyro_r[:n], gyro_p[:n], gyro_y[:n]
    if throttle.size:
        throttle = throttle[:n]
    else:
        throttle = np.zeros(n)

    segments, seg_warnings = select_analysis_segments(
        throttle, gyro_r, gyro_p, gyro_y, fs, max_segments=MAX_SEGMENTS
    )
    warnings.extend(seg_warnings)

    # Concatenate selected contiguous segment slices only (never splice non-contiguous)
    if segments:
        idxs: list[np.ndarray] = []
        for seg in segments:
            idxs.append(np.arange(seg.start_index, seg.end_index))
        # Keep per-segment analysis and average floors — do not concatenate across gaps for FFT
        axis_results = []
        for axis_name, series in (("roll", gyro_r), ("pitch", gyro_p), ("yaw", gyro_y)):
            floors = []
            peaks: list[SpectralPeak] = []
            for seg in segments:
                sl = series[seg.start_index : seg.end_index]
                ar = analyze_axis_noise(sl, fs)
                if ar["noise_floor_db"] is not None:
                    floors.append(ar["noise_floor_db"])
                peaks.extend(ar["peaks"])
            floor = float(np.mean(floors)) if floors else None
            axis_results.append((axis_name, floor, peaks))
    else:
        axis_results = [
            (name, analyze_axis_noise(series, fs)["noise_floor_db"], analyze_axis_noise(series, fs)["peaks"])
            for name, series in (("roll", gyro_r), ("pitch", gyro_p), ("yaw", gyro_y))
        ]

    noise_floor = {
        name: (round(floor, 3) if floor is not None else None) for name, floor, _ in axis_results
    }
    # flatten peaks (dedupe by frequency)
    all_peaks: list[SpectralPeak] = []
    seen: set[int] = set()
    for _, _, peaks in axis_results:
        for peak in peaks:
            key = int(round(peak.frequency_hz))
            if key in seen:
                continue
            seen.add(key)
            all_peaks.append(peak)

    roll_f = noise_floor.get("roll")
    pitch_f = noise_floor.get("pitch")
    floors_valid = [f for f in (roll_f, pitch_f) if f is not None]
    worst = max(floors_valid) if floors_valid else None
    if worst is None:
        overall = "unknown"
    elif worst >= -20:
        overall = "high"
    elif worst >= -40:
        overall = "medium"
    else:
        overall = "low"

    # Current filter state
    if filter_state is not None:
        current = dict(filter_state)
    else:
        parsed = parse_filter_state(headers=headers, cli_dump=cli_dump)
        current = dict(parsed.get("state") or {})

    dyn_ev = None
    if throttle_band_noise:
        dyn_ev = analyze_dynamic_lowpass_evidence(throttle_band_noise)
    throttle_dep = dyn_ev or {"recommended": False, "summary": "no throttle-band noise provided"}

    candidate = build_filter_candidate(
        worst_noise_floor_db=worst,
        current_settings=current,
        dynamic_evidence=dyn_ev,
    )
    # Hard invariant
    candidate.actionable = False

    current_gd = estimate_group_delay(current) if current else None
    proposed_settings = dict(current)
    proposed_settings.update(candidate.settings)
    if candidate.gyro_lpf1_hz is not None and "gyro_lpf1_static_hz" not in candidate.settings:
        pass
    proposed_gd = estimate_group_delay(proposed_settings) if proposed_settings else None
    if proposed_gd and current_gd:
        proposed_gd.proposed_gyro_total_ms = proposed_gd.gyro_total_ms
        proposed_gd.proposed_dterm_total_ms = proposed_gd.dterm_total_ms

    if current_gd and current_gd.gyro_over_budget:
        warnings.append("excessive_group_delay")
    if current_gd and current_gd.gyro_total_ms < 0.5:
        warnings.append("low_group_delay")

    conf = "low"
    if segments and segments[0].kind != "entire" and worst is not None:
        conf = "high" if len(segments) >= 2 else "medium"
    if any("insufficient_stable_segment" in w for w in warnings):
        conf = "low"

    return FilterEvidenceResult(
        selected_segments=segments,
        noise_floor_db={k: (v if v is not None else float("nan")) for k, v in noise_floor.items()},
        overall_noise_level=overall,
        peaks=all_peaks,
        throttle_dependent_noise=throttle_dep,
        current_filter_state=current,
        filter_candidate=candidate if isinstance(candidate, FilterCandidate) else FilterCandidate(actionable=False),
        current_group_delay=current_gd,
        proposed_group_delay=proposed_gd,
        confidence=conf,
        warnings=warnings,
        provenance=dict(PROVENANCE),
        actionable=False,
    )
