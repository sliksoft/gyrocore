# GyroCore WU4: adapted from AeroTuner backend/analysis/betaflight_filter_model.py
"""Conservative Betaflight filter-state detection and confidence metadata.

This module preserves observed filter state and describes confidence. It is not a
full Betaflight filter simulator.
"""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Any, Mapping

from gyrocore.analysis.erpm_units import has_pole_pair_conflict, to_mechanical_hz

FILTER_INTELLIGENCE_VERSION = 2
RPM_HARMONIC_MATCH_TOLERANCE_PERCENT = 5.0
RPM_HARMONIC_HIGH_TOLERANCE_PERCENT = 3.0
WELCH_PSD_SUPPORTING_NOTE = (
    "Welch PSD preview is supporting evidence, not a full Betaflight filter simulation."
)

SOURCE_BLACKBOX_HEADER = "blackbox_header"
SOURCE_CLI_DUMP = "cli_dump"
SOURCE_INFERRED = "inferred"
SOURCE_METADATA = "metadata"
SOURCE_MISSING = "missing"
SOURCE_USER_INPUT = "user_input"

FILTER_KEYS: tuple[str, ...] = (
    "gyro_lpf1_static_hz",
    "gyro_lpf2_static_hz",
    "gyro_lpf1_dyn_min_hz",
    "gyro_lpf1_dyn_max_hz",
    "gyro_notch_hz",
    "gyro_notch_cutoff",
    "dynamic_notch_count",
    "dynamic_notch_min_hz",
    "dynamic_notch_max_hz",
    "dynamic_notch_q",
    "dynamic_notch_width_percent",
    "dterm_lpf1_static_hz",
    "dterm_lpf1_dyn_min_hz",
    "dterm_lpf1_dyn_max_hz",
    "dterm_lpf2_static_hz",
    "dterm_notch_hz",
    "dterm_notch_cutoff",
    "yaw_lowpass_hz",
    "rpm_filter",
    "rpm_filter_harmonics",
    "rpm_filter_min_hz",
    "rpm_filter_max_hz",
    "dshot_bidir",
    "motor_poles",
    "betaflight_version",
    "sample_rate_hz",
    "loop_rate_hz",
    "pid_process_denom",
    "rpm_telemetry_present",
    "rpm_telemetry_confidence",
    "rpm_harmonic_confidence",
    "dyn_idle_min_rpm",
    "transient_throttle_limit",
    "anti_gravity_gain",
    "anti_gravity_cutoff",
    "anti_gravity_p_gain",
)

_HEADER_ALIASES: dict[str, str] = {
    "dyn_notch_count": "dynamic_notch_count",
    "dyn_notch_min_hz": "dynamic_notch_min_hz",
    "dyn_notch_max_hz": "dynamic_notch_max_hz",
    "dyn_notch_q": "dynamic_notch_q",
    "dyn_notch_width_percent": "dynamic_notch_width_percent",
    "motor_poles": "motor_poles",
    "motor_pole_count": "motor_poles",
    "motor_poles_count": "motor_poles",
    "firmware revision": "betaflight_version",
    "firmware": "betaflight_version",
    "looptime": "loop_rate_hz",
    "pid_process_denom": "pid_process_denom",
}

_DIRECT_KEYS = set(FILTER_KEYS) | set(_HEADER_ALIASES)
_SET_LINE_RE = re.compile(
    r"^\s*set\s+([a-zA-Z0-9_]+)\s*=\s*(.+?)\s*$",
    re.IGNORECASE,
)


def _empty_state() -> dict[str, Any]:
    return {key: None for key in FILTER_KEYS}


def _empty_evidence() -> dict[str, str]:
    return {key: SOURCE_MISSING for key in FILTER_KEYS}


def _canonical_key(key: str) -> str | None:
    k = str(key or "").strip().lower()
    if not k:
        return None
    if k in _HEADER_ALIASES:
        return _HEADER_ALIASES[k]
    if k in FILTER_KEYS:
        return k
    return None


def _coerce_bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and math.isfinite(float(raw)):
        return bool(int(raw))
    s = str(raw).strip().strip('"').strip("'").lower()
    if s in {"on", "true", "yes", "1", "enabled", "enable"}:
        return True
    if s in {"off", "false", "no", "0", "disabled", "disable", "none"}:
        return False
    return None


def _coerce_number(raw: Any) -> int | float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(str(raw).strip().strip('"').strip("'"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if abs(value - round(value)) < 1e-9:
        return int(round(value))
    return value


def _coerce_value(key: str, raw: Any) -> Any:
    if key in {"rpm_filter", "dshot_bidir", "rpm_telemetry_present"}:
        return _coerce_bool(raw)
    if key == "betaflight_version":
        s = str(raw or "").strip()
        return s or None
    return _coerce_number(raw)


def _assign(
    state: dict[str, Any],
    evidence: dict[str, str],
    key: str,
    raw: Any,
    source: str,
    *,
    overwrite: bool = True,
) -> None:
    canonical = _canonical_key(key)
    if canonical is None:
        return
    value = _coerce_value(canonical, raw)
    if value is None:
        return
    if not overwrite and state.get(canonical) is not None:
        return
    state[canonical] = value
    evidence[canonical] = source


def _flat_headers(headers: str | None) -> dict[str, str]:
    if not headers or not str(headers).strip():
        return {}
    text = str(headers).lstrip("\ufeff")
    flat: dict[str, str] = {}
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        rows = []
    for row in rows:
        if len(row) < 2:
            continue
        key = str(row[0]).strip().lower()
        val = str(row[1]).strip().strip('"')
        if key:
            flat[key] = val
    if flat:
        return flat
    for line in text.splitlines():
        if "," not in line:
            continue
        key, val = line.split(",", 1)
        key = key.strip().lower()
        if key:
            flat[key] = val.strip().strip('"')
    return flat


def _parse_cli_set_lines(cli_dump: str | None) -> dict[str, str]:
    if not cli_dump or not str(cli_dump).strip():
        return {}
    out: dict[str, str] = {}
    for line in str(cli_dump).splitlines():
        match = _SET_LINE_RE.match(line.strip())
        if not match:
            continue
        out[match.group(1).strip().lower()] = match.group(2).strip()
    return out


def _filter_dict_from_tuning(tuning_headers: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(tuning_headers, Mapping):
        return {}
    filters = tuning_headers.get("filters")
    return filters if isinstance(filters, Mapping) else {}


def _meta_dict_from_tuning(tuning_headers: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not isinstance(tuning_headers, Mapping):
        return {}
    meta = tuning_headers.get("meta")
    return meta if isinstance(meta, Mapping) else {}


def _rpm_telemetry_from_erpm(erpm: Mapping[str, Any] | None) -> tuple[bool | None, float | None]:
    if not isinstance(erpm, Mapping):
        return None, None
    coverage_raw = erpm.get("erpm_sample_coverage")
    try:
        coverage = float(coverage_raw)
    except (TypeError, ValueError):
        coverage = 0.0
    motor_freqs = erpm.get("motor_frequencies_hz")
    has_motor_freq = False
    if isinstance(motor_freqs, list):
        for item in motor_freqs:
            try:
                fv = float(item)
            except (TypeError, ValueError):
                continue
            if math.isfinite(fv) and fv > 0:
                has_motor_freq = True
                break
    confidence_raw = erpm.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = None
    present = bool(coverage > 0.05 or has_motor_freq)
    return present, confidence


def _valid_positive_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return value


def _label_score(label: str) -> float:
    return {"high": 1.0, "medium": 0.62, "low": 0.25}.get(label, 0.25)


def _downgrade_label(label: str, steps: int = 1) -> str:
    order = ["low", "medium", "high"]
    try:
        idx = order.index(label)
    except ValueError:
        return "low"
    return order[max(0, idx - max(1, int(steps)))]


def _plausible_hz(raw: Any, *, min_hz: float = 0.0, max_hz: float = 2000.0) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    if value < min_hz or value > max_hz:
        return None
    return value


def _is_non_finite_number(raw: Any) -> bool:
    if raw is None or isinstance(raw, bool):
        return False
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return False
    return not math.isfinite(value)


def _collect_filter_plausibility_warnings(
    state: Mapping[str, Any],
    harmonic_confidence: Any,
    log_metadata: Mapping[str, Any] | None,
) -> tuple[list[str], dict[str, int]]:
    warnings: list[str] = []
    penalties = {"gyro": 0, "dterm": 0, "dynamic": 0, "rpm": 0}

    def add_warning(message: str, *domains: str) -> None:
        warnings.append(message)
        for domain in domains:
            penalties[domain] = penalties.get(domain, 0) + 1

    def check_negative_or_non_finite(field: str, domain: str) -> None:
        raw = state.get(field)
        if _is_non_finite_number(raw):
            add_warning(f"{field} is non-finite and treated as unreliable evidence.", domain)
            return
        if raw is None or isinstance(raw, bool):
            return
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return
        if value < 0:
            add_warning(f"{field} is negative and treated as unreliable evidence.", domain)

    check_negative_or_non_finite("gyro_lpf1_dyn_min_hz", "gyro")
    check_negative_or_non_finite("gyro_lpf1_dyn_max_hz", "gyro")
    check_negative_or_non_finite("dterm_lpf1_dyn_min_hz", "dterm")
    check_negative_or_non_finite("dterm_lpf1_dyn_max_hz", "dterm")
    check_negative_or_non_finite("dynamic_notch_min_hz", "dynamic")
    check_negative_or_non_finite("dynamic_notch_max_hz", "dynamic")

    gyro_min = _plausible_hz(state.get("gyro_lpf1_dyn_min_hz"), max_hz=1000.0)
    gyro_max = _plausible_hz(state.get("gyro_lpf1_dyn_max_hz"), max_hz=1000.0)
    if gyro_min is None and state.get("gyro_lpf1_dyn_min_hz") is not None:
        add_warning("gyro_lpf1_dyn_min_hz is outside plausible range (0-1000 Hz).", "gyro")
    if gyro_max is None and state.get("gyro_lpf1_dyn_max_hz") is not None:
        add_warning("gyro_lpf1_dyn_max_hz is outside plausible range (0-1000 Hz).", "gyro")
    if gyro_min is not None and gyro_max is not None and gyro_min > gyro_max:
        add_warning("gyro_lpf1_dyn_min_hz is greater than gyro_lpf1_dyn_max_hz.", "gyro", "dynamic")

    dterm_min = _plausible_hz(state.get("dterm_lpf1_dyn_min_hz"), max_hz=1000.0)
    dterm_max = _plausible_hz(state.get("dterm_lpf1_dyn_max_hz"), max_hz=1000.0)
    if dterm_min is None and state.get("dterm_lpf1_dyn_min_hz") is not None:
        add_warning("dterm_lpf1_dyn_min_hz is outside plausible range (0-1000 Hz).", "dterm")
    if dterm_max is None and state.get("dterm_lpf1_dyn_max_hz") is not None:
        add_warning("dterm_lpf1_dyn_max_hz is outside plausible range (0-1000 Hz).", "dterm")
    if dterm_min is not None and dterm_max is not None and dterm_min > dterm_max:
        add_warning("dterm_lpf1_dyn_min_hz is greater than dterm_lpf1_dyn_max_hz.", "dterm", "dynamic")

    notch_min = _plausible_hz(state.get("dynamic_notch_min_hz"), max_hz=2000.0)
    notch_max = _plausible_hz(state.get("dynamic_notch_max_hz"), max_hz=2000.0)
    if notch_min is None and state.get("dynamic_notch_min_hz") is not None:
        add_warning("dynamic_notch_min_hz is outside plausible range (0-2000 Hz).", "dynamic")
    if notch_max is None and state.get("dynamic_notch_max_hz") is not None:
        add_warning("dynamic_notch_max_hz is outside plausible range (0-2000 Hz).", "dynamic")
    if notch_min is not None and notch_max is not None and notch_min > notch_max:
        add_warning("dynamic_notch_min_hz is greater than dynamic_notch_max_hz.", "dynamic")

    rpm_harmonics_raw = state.get("rpm_filter_harmonics")
    if rpm_harmonics_raw is not None:
        try:
            rpm_harmonics = float(rpm_harmonics_raw)
        except (TypeError, ValueError):
            rpm_harmonics = None
        if rpm_harmonics is None or not math.isfinite(rpm_harmonics) or rpm_harmonics <= 0:
            add_warning("rpm_filter_harmonics is non-positive and treated conservatively.", "rpm")

    erpm_map = log_metadata.get("erpm_analysis") if isinstance(log_metadata, Mapping) else None
    if isinstance(erpm_map, Mapping):
        scale_assumption = str(erpm_map.get("erpm_scale_assumption") or "").strip().lower()
        if scale_assumption == "ambiguous":
            add_warning("ERPM scale is ambiguous near threshold; RPM evidence confidence is reduced.", "rpm")

        pole_pairs_meta = erpm_map.get("pole_pairs")
        if has_pole_pair_conflict(motor_poles=state.get("motor_poles"), pole_pairs=pole_pairs_meta):
            add_warning("motor_poles and pole_pairs disagree; RPM evidence is treated as uncertain.", "rpm")

        dominant_elec = _valid_positive_float(erpm_map.get("dominant_frequency"))
        dominant_mech = _valid_positive_float(erpm_map.get("dominant_frequency_mechanical_hz"))
        if dominant_elec is not None and dominant_mech is not None:
            converted = to_mechanical_hz(
                dominant_elec,
                motor_poles=state.get("motor_poles"),
                pole_pairs=pole_pairs_meta,
                already_mechanical_hz=False,
            )
            if converted is not None and converted > 0:
                mismatch = abs(converted - dominant_mech) / max(dominant_mech, 1e-6)
                if mismatch > 0.2:
                    add_warning(
                        "Electrical and mechanical ERPM dominant frequencies disagree; harmonic evidence is uncertain.",
                        "rpm",
                    )

    if harmonic_confidence == "high" and state.get("motor_poles") is None:
        add_warning("High RPM harmonic confidence without motor_poles is treated conservatively.", "rpm")

    return warnings, penalties


def _compact_spectral_peak(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    hz = _valid_positive_float(item.get("hz"))
    rel = _valid_positive_float(item.get("relative_power"))
    confidence = str(item.get("confidence") or "low")
    if hz is None or rel is None:
        return None
    return {
        "hz": round(hz, 3),
        "relative_power": round(max(0.0, min(1.0, rel)), 6),
        "confidence": confidence if confidence in {"high", "medium", "low"} else "low",
    }


def _compact_spectral_throttle_bands(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, Any] = {}
    for name in ("low", "mid", "high"):
        block = raw.get(name)
        if not isinstance(block, Mapping):
            continue
        sample_count_raw = block.get("sample_count")
        sample_count = (
            int(sample_count_raw)
            if isinstance(sample_count_raw, (int, float))
            and not isinstance(sample_count_raw, bool)
            and math.isfinite(float(sample_count_raw))
            and sample_count_raw >= 0
            else 0
        )
        peaks_raw = block.get("peaks")
        peaks: list[dict[str, Any]] = []
        if isinstance(peaks_raw, list):
            for peak_raw in peaks_raw[:3]:
                peak = _compact_spectral_peak(peak_raw)
                if peak is not None:
                    peaks.append(peak)
        out[name] = {"sample_count": sample_count, "peaks": peaks}
    return out


def _compact_spectral_persistence(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:5]:
        if not isinstance(item, Mapping):
            continue
        hz = _valid_positive_float(item.get("hz"))
        if hz is None:
            continue
        bands_raw = item.get("bands_seen")
        bands_seen = (
            [str(band) for band in bands_raw if isinstance(band, str) and band in {"low", "mid", "high"}]
            if isinstance(bands_raw, list)
            else []
        )
        score_raw = item.get("persistence_score")
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            score = 0.0
        if not math.isfinite(score):
            score = 0.0
        likely_type = str(item.get("likely_type") or "unknown")
        confidence = str(item.get("confidence") or "low")
        out.append(
            {
                "hz": round(hz, 3),
                "bands_seen": bands_seen,
                "persistence_score": round(max(0.0, min(1.0, score)), 4),
                "likely_type": likely_type
                if likely_type in {"persistent_frame_resonance", "throttle_dependent", "unknown"}
                else "unknown",
                "confidence": confidence if confidence in {"high", "medium", "low"} else "low",
            }
        )
    return out


def _compact_spectral_evidence_from_metadata(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {
            "version": 1,
            "method": "existing_fft_fallback",
            "quality": "medium",
            "sample_rate_hz": None,
            "sample_count": None,
            "warnings": [],
            "notes": [WELCH_PSD_SUPPORTING_NOTE],
            "dominant_peaks": [],
            "throttle_bands": {},
            "persistence": [],
        }
    raw = metadata.get("spectral_evidence")
    if isinstance(raw, Mapping):
        warnings_raw = raw.get("warnings")
        warnings = (
            [str(w) for w in warnings_raw if isinstance(w, str) and str(w) != WELCH_PSD_SUPPORTING_NOTE]
            if isinstance(warnings_raw, list)
            else []
        )
        notes_raw = raw.get("notes")
        notes = [str(note) for note in notes_raw if isinstance(note, str)] if isinstance(notes_raw, list) else []
        peaks_raw = raw.get("dominant_peaks")
        peaks: list[dict[str, Any]] = []
        if isinstance(peaks_raw, list):
            for item in peaks_raw[:5]:
                peak = _compact_spectral_peak(item)
                if peak is not None:
                    peaks.append(peak)
        throttle_bands = _compact_spectral_throttle_bands(raw.get("throttle_bands"))
        persistence = _compact_spectral_persistence(raw.get("persistence"))
        quality = str(raw.get("quality") or "low")
        method = str(raw.get("method") or "welch_psd_preview")
        sample_rate = _valid_positive_float(raw.get("sample_rate_hz"))
        effective_sample_rate = _valid_positive_float(raw.get("effective_sample_rate_hz"))
        original_sample_rate = _valid_positive_float(raw.get("original_sample_rate_hz"))
        sample_count_raw = raw.get("sample_count")
        sample_count = int(sample_count_raw) if isinstance(sample_count_raw, (int, float)) and sample_count_raw >= 0 else None
        analyzed_sample_count_raw = raw.get("analyzed_sample_count")
        analyzed_sample_count = (
            int(analyzed_sample_count_raw)
            if isinstance(analyzed_sample_count_raw, (int, float))
            and not isinstance(analyzed_sample_count_raw, bool)
            and analyzed_sample_count_raw >= 0
            else None
        )
        used_sample_count_raw = raw.get("used_sample_count")
        used_sample_count = (
            int(used_sample_count_raw)
            if isinstance(used_sample_count_raw, (int, float))
            and not isinstance(used_sample_count_raw, bool)
            and used_sample_count_raw >= 0
            else analyzed_sample_count
        )
        original_sample_count_raw = raw.get("original_sample_count")
        original_sample_count = (
            int(original_sample_count_raw)
            if isinstance(original_sample_count_raw, (int, float))
            and not isinstance(original_sample_count_raw, bool)
            and original_sample_count_raw >= 0
            else None
        )
        samples_were_capped = bool(raw.get("samples_were_capped"))
        samples_were_subsampled = bool(raw.get("samples_were_subsampled"))
        return {
            "version": 1,
            "method": method if method in {"welch_psd_preview", "existing_fft_fallback"} else "welch_psd_preview",
            "quality": quality if quality in {"high", "medium", "low"} else "low",
            "sample_rate_hz": round(sample_rate, 3) if sample_rate is not None else None,
            "effective_sample_rate_hz": round(effective_sample_rate, 3)
            if effective_sample_rate is not None
            else (round(sample_rate, 3) if sample_rate is not None else None),
            "original_sample_rate_hz": round(original_sample_rate, 3) if original_sample_rate is not None else None,
            "sample_count": sample_count,
            "analyzed_sample_count": analyzed_sample_count,
            "used_sample_count": used_sample_count,
            "original_sample_count": original_sample_count,
            "samples_were_capped": samples_were_capped,
            "samples_were_subsampled": samples_were_subsampled,
            "warnings": list(dict.fromkeys(warnings)),
            "notes": list(dict.fromkeys([*notes, WELCH_PSD_SUPPORTING_NOTE])),
            "dominant_peaks": peaks,
            "throttle_bands": throttle_bands,
            "persistence": persistence,
        }

    peaks = _measured_peaks_from_metadata(metadata)
    dominant_peaks = [{"hz": round(hz, 3), "relative_power": 1.0, "confidence": "medium"} for hz in peaks[:5]]
    sample_rate = _valid_positive_float(metadata.get("sample_rate_hz"))
    return {
        "version": 1,
        "method": "existing_fft_fallback",
        "quality": "medium" if dominant_peaks else "low",
        "sample_rate_hz": round(sample_rate, 3) if sample_rate is not None else None,
        "sample_count": None,
        "warnings": [
            "High-frequency spectral confidence is limited by sample count or subsampling.",
        ]
        if not dominant_peaks
        else [],
        "notes": [WELCH_PSD_SUPPORTING_NOTE],
        "dominant_peaks": dominant_peaks,
        "throttle_bands": {},
        "persistence": [],
    }


def _configured_rpm_harmonics(state: Mapping[str, Any]) -> int:
    raw = _valid_positive_float(state.get("rpm_filter_harmonics"))
    if raw is None:
        return 3
    return max(1, min(5, int(round(raw))))


def _expected_harmonics_from_erpm(
    erpm: Mapping[str, Any] | None,
    *,
    max_harmonic: int,
    motor_poles: Any = None,
    pole_pairs: Any = None,
) -> list[tuple[int, float]]:
    """Return explicit ERPM/RPM harmonic frequencies already present in analysis metadata."""
    if not isinstance(erpm, Mapping):
        return []
    out: list[tuple[int, float]] = []
    harmonics_mech = erpm.get("harmonics_mechanical_hz")
    if isinstance(harmonics_mech, list):
        for motor_row in harmonics_mech:
            if not isinstance(motor_row, list):
                continue
            for idx, raw_hz in enumerate(motor_row[:max_harmonic], start=1):
                hz = _valid_positive_float(raw_hz)
                if hz is not None:
                    out.append((idx, hz))
    if out:
        return out

    harmonics = erpm.get("harmonics_hz")
    if isinstance(harmonics, list):
        for motor_row in harmonics:
            if not isinstance(motor_row, list):
                continue
            for idx, raw_hz in enumerate(motor_row[:max_harmonic], start=1):
                hz = to_mechanical_hz(
                    raw_hz,
                    motor_poles=motor_poles,
                    pole_pairs=pole_pairs,
                    already_mechanical_hz=False,
                )
                if hz is not None and hz > 0:
                    out.append((idx, float(hz)))
    if out:
        return out

    motor_freqs_mech = erpm.get("motor_frequencies_mechanical_hz")
    if isinstance(motor_freqs_mech, list):
        for raw_base in motor_freqs_mech:
            base = _valid_positive_float(raw_base)
            if base is None:
                continue
            for harmonic in range(1, max_harmonic + 1):
                out.append((harmonic, base * harmonic))
    if out:
        return out

    motor_freqs = erpm.get("motor_frequencies_hz")
    if isinstance(motor_freqs, list):
        for raw_base in motor_freqs:
            base = to_mechanical_hz(
                raw_base,
                motor_poles=motor_poles,
                pole_pairs=pole_pairs,
                already_mechanical_hz=False,
            )
            if base is None:
                continue
            for harmonic in range(1, max_harmonic + 1):
                out.append((harmonic, float(base) * harmonic))
    return out


def _measured_peaks_from_metadata(metadata: Mapping[str, Any] | None) -> list[float]:
    if not isinstance(metadata, Mapping):
        return []
    raw_peaks = metadata.get("fft_peaks")
    peaks: list[float] = []
    if isinstance(raw_peaks, list):
        for item in raw_peaks[:32]:
            if isinstance(item, Mapping):
                hz = _valid_positive_float(item.get("freq") or item.get("frequency_hz"))
            else:
                hz = _valid_positive_float(item)
            if hz is not None:
                peaks.append(hz)
    if peaks:
        return peaks
    raw_freqs = metadata.get("peak_frequencies")
    if isinstance(raw_freqs, list):
        for item in raw_freqs[:32]:
            hz = _valid_positive_float(item)
            if hz is not None:
                peaks.append(hz)
    return peaks


def _best_harmonic_match(
    peak_hz: float,
    expected: list[tuple[int, float]],
) -> tuple[int, float, float] | None:
    best: tuple[int, float, float] | None = None
    for harmonic, expected_hz in expected:
        error_percent = abs(peak_hz - expected_hz) / expected_hz * 100.0
        if best is None or error_percent < best[2]:
            best = (harmonic, expected_hz, error_percent)
    return best


def build_rpm_harmonic_evidence(
    state: Mapping[str, Any],
    metadata: Mapping[str, Any] | None = None,
    spectral_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Conservative RPM/ERPM harmonic evidence.

    A high score requires an explicit measured FFT peak within
    ``RPM_HARMONIC_MATCH_TOLERANCE_PERCENT`` of an ERPM-derived harmonic plus
    the RPM filter, bidirectional DSHOT, motor poles, and telemetry gates.
    ERPM stability/confidence alone is context only and cannot produce high confidence.
    """
    erpm = metadata.get("erpm_analysis") if isinstance(metadata, Mapping) else None
    erpm_map = erpm if isinstance(erpm, Mapping) else None
    rpm_enabled = state.get("rpm_filter") is True
    dshot = state.get("dshot_bidir")
    motor_poles = state.get("motor_poles")
    telemetry = state.get("rpm_telemetry_present")
    expected = _expected_harmonics_from_erpm(
        erpm_map,
        max_harmonic=_configured_rpm_harmonics(state),
        motor_poles=state.get("motor_poles"),
        pole_pairs=state.get("pole_pairs"),
    )
    peaks = _measured_peaks_from_metadata(metadata)

    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    used_expected: set[int] = set()
    for peak_hz in peaks:
        best = _best_harmonic_match(peak_hz, expected)
        if best is None:
            unmatched.append({"peak_hz": round(peak_hz, 3), "reason": "expected_harmonic_unavailable"})
            continue
        harmonic, expected_hz, error_percent = best
        if error_percent <= RPM_HARMONIC_MATCH_TOLERANCE_PERCENT:
            expected_key = int(round(expected_hz * 1000.0))
            if expected_key in used_expected:
                unmatched.append({"peak_hz": round(peak_hz, 3), "reason": "duplicate_harmonic_match"})
                continue
            used_expected.add(expected_key)
            matched.append(
                {
                    "peak_hz": round(peak_hz, 3),
                    "expected_hz": round(expected_hz, 3),
                    "harmonic": harmonic,
                    "error_percent": round(error_percent, 3),
                    "confidence": "high"
                    if error_percent <= RPM_HARMONIC_HIGH_TOLERANCE_PERCENT
                    else "medium",
                }
            )
        else:
            unmatched.append({"peak_hz": round(peak_hz, 3), "reason": "outside_harmonic_tolerance"})

    warnings: list[str] = []
    if not rpm_enabled:
        warnings.append("RPM filter enablement could not be confirmed from the parsed inputs.")
    if dshot is not True:
        warnings.append("Bidirectional DSHOT is unknown or disabled.")
    if motor_poles is None:
        warnings.append("motor_poles is unknown.")
    if telemetry is not True:
        warnings.append("ERPM/RPM telemetry is missing or weak.")
    if not expected:
        warnings.append("Expected ERPM/RPM harmonic frequencies are unavailable.")
    if not peaks:
        warnings.append("Measured FFT peaks are unavailable for harmonic matching.")
    if peaks and expected and not matched:
        warnings.append("No measured peak matched an expected ERPM/RPM harmonic within tolerance.")
    spectral_quality = None
    if isinstance(spectral_evidence, Mapping):
        spectral_quality = spectral_evidence.get("quality")
    if spectral_quality == "low":
        warnings.append("RPM harmonic matching is limited because spectral quality is low.")

    score: float | None = None
    confidence = "low"
    harmonic_match_available = bool(expected and peaks)
    if matched:
        best_error = min(float(row["error_percent"]) for row in matched)
        score = max(0.0, min(1.0, 1.0 - (best_error / RPM_HARMONIC_MATCH_TOLERANCE_PERCENT)))
        if rpm_enabled and dshot is True and motor_poles is not None and telemetry is True:
            confidence = "high" if best_error <= RPM_HARMONIC_HIGH_TOLERANCE_PERCENT else "medium"
        else:
            confidence = "medium" if telemetry is True and (dshot is True or motor_poles is not None) else "low"
    elif telemetry is True and rpm_enabled and (dshot is True or motor_poles is not None):
        confidence = "medium"
    if spectral_quality == "low" and confidence == "high":
        confidence = "medium"

    return {
        "available": harmonic_match_available,
        "confidence": confidence,
        "score": round(score, 4) if score is not None else None,
        "rpm_telemetry_present": telemetry if isinstance(telemetry, bool) else None,
        "dshot_bidir_confirmed": dshot if isinstance(dshot, bool) else None,
        "motor_poles_known": motor_poles is not None,
        "harmonic_match_available": harmonic_match_available,
        "matched_harmonics": matched,
        "unmatched_peaks": unmatched,
        "warnings": warnings,
    }


def parse_filter_state(
    headers: str | None = None,
    cli_dump: str | None = None,
    tuning_headers: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Preserve observed Betaflight filter state with per-field evidence labels."""
    state = _empty_state()
    evidence = _empty_evidence()

    for key, value in _flat_headers(headers).items():
        if _canonical_key(key) is not None:
            _assign(state, evidence, key, value, SOURCE_BLACKBOX_HEADER)

    for key, value in _filter_dict_from_tuning(tuning_headers).items():
        if _canonical_key(key) is not None:
            _assign(state, evidence, key, value, SOURCE_BLACKBOX_HEADER)

    meta = _meta_dict_from_tuning(tuning_headers)
    if meta.get("firmware"):
        _assign(state, evidence, "betaflight_version", meta.get("firmware"), SOURCE_BLACKBOX_HEADER)

    for key, value in _parse_cli_set_lines(cli_dump).items():
        if _canonical_key(key) is not None:
            _assign(state, evidence, key, value, SOURCE_CLI_DUMP)

    if isinstance(metadata, Mapping):
        cli_cfg = metadata.get("uploaded_cli_tune")
        if isinstance(cli_cfg, Mapping):
            cli_filters = cli_cfg.get("filters")
            if isinstance(cli_filters, Mapping):
                for key, value in cli_filters.items():
                    _assign(state, evidence, str(key), value, SOURCE_CLI_DUMP)
        input_context = metadata.get("input_context")
        if isinstance(input_context, Mapping):
            _assign(state, evidence, "motor_poles", input_context.get("motor_poles"), SOURCE_METADATA, overwrite=False)
        firmware_meta = metadata.get("firmware_meta")
        if isinstance(firmware_meta, Mapping):
            fw = firmware_meta.get("firmware") or firmware_meta.get("version") or firmware_meta.get("name")
            _assign(state, evidence, "betaflight_version", fw, SOURCE_METADATA, overwrite=False)
        _assign(state, evidence, "sample_rate_hz", metadata.get("sample_rate_hz"), SOURCE_METADATA, overwrite=False)
        erpm_present, erpm_confidence = _rpm_telemetry_from_erpm(
            metadata.get("erpm_analysis") if isinstance(metadata.get("erpm_analysis"), Mapping) else None
        )
        if erpm_present is not None:
            _assign(state, evidence, "rpm_telemetry_present", erpm_present, SOURCE_INFERRED)
        if erpm_confidence is not None:
            _assign(state, evidence, "rpm_telemetry_confidence", erpm_confidence, SOURCE_INFERRED)
        _assign(
            state,
            evidence,
            "rpm_harmonic_confidence",
            metadata.get("rpm_harmonic_confidence"),
            SOURCE_METADATA,
            overwrite=False,
        )

    return {"version": FILTER_INTELLIGENCE_VERSION, "state": state, "evidence": evidence}


def _label_from_score(score: float) -> str:
    if score >= 0.78:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def _known(evidence: Mapping[str, str], *keys: str) -> int:
    return sum(1 for key in keys if evidence.get(key) not in (None, SOURCE_MISSING))


def validate_filter_state(
    filter_state: Mapping[str, Any],
    log_metadata: Mapping[str, Any] | None = None,
    harmonic_evidence: Mapping[str, Any] | None = None,
    spectral_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return conservative confidence, warnings, and unsupported/partial markers."""
    state = filter_state.get("state") if isinstance(filter_state.get("state"), Mapping) else filter_state
    evidence = filter_state.get("evidence") if isinstance(filter_state.get("evidence"), Mapping) else {}
    if not isinstance(state, Mapping):
        state = {}
    if not isinstance(evidence, Mapping):
        evidence = {}

    partial: list[str] = []
    unsupported: list[str] = []
    warnings: list[str] = []
    preview_limitations: list[str] = []

    if state.get("dterm_notch_hz") is not None or state.get("dterm_notch_cutoff") is not None:
        partial.append("dterm_notch")
        unsupported.append("dterm_notch_simulation")
        preview_limitations.append(
            "D-term notch detected (not modeled in filter preview; does not affect tuning output)."
        )

    if state.get("yaw_lowpass_hz") is not None:
        partial.append("yaw_lowpass")
        unsupported.append("yaw_lowpass_simulation")
        preview_limitations.append(
            "Yaw lowpass detected (not modeled in filter preview; does not affect tuning output or paste-ready CLI)."
        )

    dyn_gyro_known = state.get("gyro_lpf1_dyn_min_hz") is not None or state.get("gyro_lpf1_dyn_max_hz") is not None
    if dyn_gyro_known:
        partial.append("dynamic_gyro_lpf")
        preview_limitations.append(
            "Dynamic gyro LPF detected (preview uses representative static cutoff, not a full firmware simulation)."
        )

    dterm_dyn_known = state.get("dterm_lpf1_dyn_min_hz") is not None or state.get("dterm_lpf1_dyn_max_hz") is not None
    if dterm_dyn_known:
        partial.append("dynamic_dterm_lpf")
        preview_limitations.append(
            "Dynamic D-term LPF detected (preview uses midpoint of dynamic range as representative cutoff)."
        )

    rpm_enabled = state.get("rpm_filter") is True
    rpm_output_present = False
    if isinstance(log_metadata, Mapping):
        pkg = log_metadata.get("tuning_package")
        rpm_output_present = isinstance(pkg, Mapping) and isinstance(pkg.get("rpm_filter"), Mapping)

    dshot = state.get("dshot_bidir")
    motor_poles = state.get("motor_poles")
    telemetry = state.get("rpm_telemetry_present")
    harmonic_score = None
    harmonic_confidence = None
    harmonic_matches = []
    if isinstance(harmonic_evidence, Mapping):
        harmonic_confidence = harmonic_evidence.get("confidence")
        harmonic_matches_raw = harmonic_evidence.get("matched_harmonics")
        harmonic_matches = harmonic_matches_raw if isinstance(harmonic_matches_raw, list) else []
        harmonic_score = _valid_positive_float(harmonic_evidence.get("score"))
    spectral_quality = None
    if isinstance(spectral_evidence, Mapping):
        spectral_quality = spectral_evidence.get("quality")
    plausibility_warnings, plausibility_penalties = _collect_filter_plausibility_warnings(
        state,
        harmonic_confidence,
        log_metadata,
    )
    warnings.extend(plausibility_warnings)

    rpm_confidence = "low"
    if (
        rpm_enabled
        and dshot is True
        and motor_poles is not None
        and telemetry is True
        and harmonic_confidence == "high"
        and harmonic_matches
    ):
        rpm_confidence = "high"
    elif telemetry is True and (rpm_enabled or rpm_output_present):
        rpm_confidence = "medium"

    if rpm_enabled or rpm_output_present:
        if state.get("rpm_filter") is None:
            warnings.append(
                "RPM filter output is preview-style; CLI/header enablement could not be directly confirmed in this log."
            )
        if dshot is not True:
            warnings.append("RPM filter confidence is limited because bidirectional DSHOT is unknown or disabled.")
        if motor_poles is None:
            warnings.append("RPM filter confidence is limited because motor_poles is unknown.")
        if telemetry is not True:
            warnings.append("RPM filter confidence is limited because ERPM/RPM telemetry is missing or weak.")
        if harmonic_score is None or harmonic_score < 0.75 or not harmonic_matches:
            warnings.append("RPM filter confidence is limited until explicit harmonic-match evidence is available.")
        if spectral_quality == "low":
            warnings.append("RPM harmonic matching is limited because spectral quality is low.")
            warnings.append("High-frequency spectral confidence is limited by sample count or subsampling.")
    if spectral_quality == "low":
        warnings.append("High-frequency spectral confidence is limited by sample count or subsampling.")

    gyro_known = _known(
        evidence,
        "gyro_lpf1_static_hz",
        "gyro_lpf2_static_hz",
        "gyro_lpf1_dyn_min_hz",
        "gyro_lpf1_dyn_max_hz",
        "gyro_notch_hz",
        "gyro_notch_cutoff",
        "dynamic_notch_count",
    )
    dterm_known = _known(
        evidence,
        "dterm_lpf1_static_hz",
        "dterm_lpf1_dyn_min_hz",
        "dterm_lpf1_dyn_max_hz",
        "dterm_lpf2_static_hz",
        "dterm_notch_hz",
        "dterm_notch_cutoff",
    )
    dynamic_known = _known(
        evidence,
        "gyro_lpf1_dyn_min_hz",
        "gyro_lpf1_dyn_max_hz",
        "dynamic_notch_count",
        "dynamic_notch_min_hz",
        "dynamic_notch_max_hz",
        "dterm_lpf1_dyn_min_hz",
        "dterm_lpf1_dyn_max_hz",
    )

    gyro_conf = _label_from_score(min(1.0, gyro_known / 4.0))
    dterm_conf = _label_from_score(min(1.0, dterm_known / 3.0))
    dynamic_conf = _label_from_score(min(1.0, dynamic_known / 4.0))
    if plausibility_penalties["gyro"] > 0:
        gyro_conf = _downgrade_label(gyro_conf, plausibility_penalties["gyro"])
    if plausibility_penalties["dterm"] > 0:
        dterm_conf = _downgrade_label(dterm_conf, plausibility_penalties["dterm"])
    if plausibility_penalties["dynamic"] > 0:
        dynamic_conf = _downgrade_label(dynamic_conf, plausibility_penalties["dynamic"])
    if plausibility_penalties["rpm"] > 0:
        rpm_confidence = _downgrade_label(rpm_confidence, plausibility_penalties["rpm"])
    overall = _label_from_score(
        (
            _label_score(gyro_conf) * 0.35
            + _label_score(dterm_conf) * 0.25
            + _label_score(rpm_confidence) * 0.25
            + _label_score(dynamic_conf) * 0.15
        )
    )
    total_penalties = sum(plausibility_penalties.values())
    if total_penalties >= 2:
        overall = _downgrade_label(overall, 1)
    if total_penalties >= 4:
        overall = _downgrade_label(overall, 1)

    if any(src == SOURCE_INFERRED for src in evidence.values()):
        warnings.append("Some filter context was inferred from log metadata and may not represent runtime configuration perfectly.")

    return {
        "confidence": {
            "overall": overall,
            "gyro_filters": gyro_conf,
            "dterm_filters": dterm_conf,
            "rpm_filter": rpm_confidence,
            "dynamic_filters": dynamic_conf,
        },
        "unsupported_filters": sorted(set(unsupported)),
        "partial_filters": sorted(set(partial)),
        "preview_limitations": list(dict.fromkeys(preview_limitations)),
        "warnings": list(dict.fromkeys(warnings)),
    }


def summarize_filter_state(filter_state: Mapping[str, Any]) -> dict[str, Any]:
    """Compact detected-state summary for UI display and logs."""
    state = filter_state.get("state") if isinstance(filter_state.get("state"), Mapping) else {}
    evidence = filter_state.get("evidence") if isinstance(filter_state.get("evidence"), Mapping) else {}
    detected = [key for key in FILTER_KEYS if state.get(key) is not None]
    by_source: dict[str, list[str]] = {}
    for key in detected:
        src = str(evidence.get(key) or SOURCE_MISSING)
        by_source.setdefault(src, []).append(key)
    return {
        "detected_keys": detected,
        "detected_count": len(detected),
        "sources": {src: keys for src, keys in sorted(by_source.items())},
    }


def _source_confidence(source: str, value: Any) -> str:
    if source == SOURCE_MISSING or value is None:
        return "low"
    if source in {SOURCE_BLACKBOX_HEADER, SOURCE_CLI_DUMP, SOURCE_USER_INPUT}:
        return "high"
    return "medium"


def build_source_evidence(filter_state: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Compact JSON-safe source metadata; never includes raw CLI/header text."""
    state = filter_state.get("state") if isinstance(filter_state.get("state"), Mapping) else {}
    evidence = filter_state.get("evidence") if isinstance(filter_state.get("evidence"), Mapping) else {}
    if not isinstance(state, Mapping) or not isinstance(evidence, Mapping):
        return []
    out: list[dict[str, Any]] = []
    for field in (
        "rpm_filter",
        "dshot_bidir",
        "motor_poles",
        "rpm_telemetry_present",
        "sample_rate_hz",
        "betaflight_version",
    ):
        value = state.get(field)
        source = str(evidence.get(field) or SOURCE_MISSING)
        if source == SOURCE_METADATA and field == "motor_poles":
            source = SOURCE_USER_INPUT
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            value = str(value)[:80]
        out.append(
            {
                "field": field,
                "value": value,
                "source": source,
                "confidence": _source_confidence(source, value),
            }
        )
    return out


def build_filter_intelligence(
    headers: str | None = None,
    cli_dump: str | None = None,
    tuning_headers: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the additive API payload for Filter Intelligence v2."""
    parsed = parse_filter_state(
        headers=headers,
        cli_dump=cli_dump,
        tuning_headers=tuning_headers,
        metadata=metadata,
    )
    spectral_evidence = _compact_spectral_evidence_from_metadata(metadata)
    harmonic_evidence = build_rpm_harmonic_evidence(parsed["state"], metadata, spectral_evidence)
    validation = validate_filter_state(parsed, metadata, harmonic_evidence, spectral_evidence)
    return {
        "version": FILTER_INTELLIGENCE_VERSION,
        "filter_state": parsed["state"],
        "confidence": validation["confidence"],
        "unsupported_filters": validation["unsupported_filters"],
        "partial_filters": validation["partial_filters"],
        "preview_limitations": validation["preview_limitations"],
        "warnings": validation["warnings"],
        "evidence": parsed["evidence"],
        "source_evidence": build_source_evidence(parsed),
        "harmonic_evidence": harmonic_evidence,
        "spectral_evidence": spectral_evidence,
        "summary": summarize_filter_state(parsed),
    }
