"""Donor-free regression: GyroCore analysis vs frozen legacy DOMAIN goldens (WU15).

Separates four concerns:

- input fixture   -> :func:`load_fixture_samples` (in-repo ``flight.csv``)
- GyroCore run    -> :func:`run_gyrocore_analysis` (``build_analysis_evidence``)
- frozen expected -> :func:`load_frozen_golden` (``expected/legacy_domain_result.json``)
- comparison      -> :func:`classify_golden_leaves` + :func:`compare_value`

The goldens were frozen from the live AeroTuner route (``_build_response``) in
commit 10105d6, before any GyroCore Core code existed, and have not changed
since. This module never imports, executes or locates AeroTuner.

Every golden leaf in analysis scope is classified exactly once:

- ``COMPARED``  : GyroCore's entry point produces the same quantity; strict compare
- ``ROUTE_ONLY``: only the donor route produces it (not a GyroCore analysis output)
- ``DIVERGENT`` : GyroCore produces it but differs; proven cause recorded, NOT compared

Unclassified leaves fail the accounting test, so new golden fields cannot be
dropped silently.
"""

from __future__ import annotations

import csv
import fnmatch
import json
import math
from pathlib import Path
from typing import Any, Iterator

from gyrocore.analysis import build_analysis_evidence

from tests.golden.paths import fixture_expected_path, fixture_input_dir

# Distinct analysis inputs with live-oracle goldens. gl001_with_cli reuses the
# gl001_clean CSV (CLI only affects tuning/safety), and whoop75_cli_snapshot has
# no sample input, so neither is an independent analysis case.
REGRESSION_FIXTURES = ("gl001_clean", "gl002_noisy")

# Same relative tolerance as the donor parity suite (TOL_SCORE / TOL_HZ = 1e-9):
# covers last-bit numpy FFT / BLAS differences across CI numpy versions only.
FLOAT_REL_TOL = 1e-9
FLOAT_ABS_FLOOR = 1e-12

COMPARED = "COMPARED"
ROUTE_ONLY = "ROUTE_ONLY"
DIVERGENT = "DIVERGENT"

# Top-level golden keys outside the analysis chain (tuning, safety, CLI, UI,
# oracle inputs echoed back, run_score). Not GyroCore analysis outputs.
OUT_OF_SCOPE_TOP_LEVEL = frozenset(
    {
        "schema_version",
        "oracle_entrypoint",
        "ai_disabled",
        "analysis_status",
        "valid_log",
        "quality_status",
        "quality_grade",
        "quality_score",
        "recommended_flight_index",
        "selected_embedded_log_index",
        "flight_selection_mode",
        "tuning_mode",
        "pid_summary",
        "filter_summary",
        "mechanical_safety",
        "tuning_output_safety",
        "authoritative_cli",
        "tuning_decision",
        "result_view",
    }
)

ANALYSIS_TOP_LEVEL = frozenset(
    {
        "metrics",
        "erpm",
        "resonance",
        "selected_flight_index",
        "flight_count",
        "problem_types",
        "problem_severities",
    }
)

_TIME_BASE = (
    "time base: donor route runs spectral/metrics on raw float-us 't' "
    "(199.8333 Hz); GyroCore evidence uses normalize_raw_samples int-us 't' "
    "(199.8401 Hz). Reproduced bit-exactly with GyroCore functions on raw 't'. "
    "Real blackbox_decode output is integer us, so only synthetic CSVs differ."
)
_COMPOSITION = (
    "composition: donor route _build_analysis feeds noise_model / fft peaks / "
    "propwash into build_metrics; GyroCore build_analysis_evidence does not, so "
    "metrics_engine returns its fallback block."
)

# (golden path glob, classification, GyroCore path template or reason).
# First match wins; ``{i}`` / ``{rest}`` are filled from the golden path.
_RULES: tuple[tuple[str, str, str], ...] = (
    # --- route-only (donor _build_response attaches these) ---
    ("metrics.response.confidence_limited_by_sample_rate", ROUTE_ONLY,
     "donor analyze.py:4125-4133 derives it from route sample-rate gating"),
    ("metrics.response.sample_rate_limit_reasons", ROUTE_ONLY,
     "donor analyze.py:4125-4133 derives it from route sample-rate gating"),
    ("erpm.motor_poles", ROUTE_ONLY, "route merges hardware motor_poles into erpm"),
    ("erpm.pole_pairs", ROUTE_ONLY, "route merges hardware motor_poles into erpm"),
    ("resonance.resonance_v2_hz", ROUTE_ONLY, "route _build_analysis resonance_v2 only"),
    # --- divergent (reported, not compared) ---
    ("metrics.noise.*", DIVERGENT, _COMPOSITION),
    ("metrics.propwash.*", DIVERGENT, _COMPOSITION),
    ("metrics.resonance.dominant_hz", DIVERGENT, _COMPOSITION),
    ("metrics.resonance.severity", DIVERGENT, _COMPOSITION),
    ("resonance.dominant_hz", DIVERGENT, _COMPOSITION),
    ("resonance.severity", DIVERGENT, _COMPOSITION),
    ("metrics.response.sample_rate_metadata.source_kind", DIVERGENT,
     "composition: donor route passes source_kind=raw_full_rate to "
     "build_sample_rate_metadata (analyze.py:3839-3846); GyroCore evidence passes "
     "none, yielding 'unknown'."),
    ("metrics.resonance.peaks[*].freq", DIVERGENT, _TIME_BASE),
    ("metrics.resonance.peaks[*].bandwidth_hz", DIVERGENT, _TIME_BASE),
    # --- compared ---
    # Same build_sample_rate_metadata on the same rows; the route nests it under
    # response (donor analyze.py:4111-4130), GyroCore exposes it top-level.
    ("metrics.response.sample_rate_metadata.*", COMPARED, "sample_rate_metadata.{rest}"),
    ("metrics.response.*", COMPARED, "metrics.response.{rest}"),
    ("metrics.tracking.*", COMPARED, "metrics.tracking.{rest}"),
    ("metrics.motor.*", COMPARED, "metrics.motor.{rest}"),
    ("metrics.d_effectiveness.*", COMPARED, "metrics.d_effectiveness.{rest}"),
    # Golden metrics.resonance.peaks are analyze_resonance peaks (freq/bandwidth
    # reproduce bit-exactly from analyze_resonance on raw 't'); amplitude does
    # not depend on the sample rate.
    ("metrics.resonance.peaks[*].amplitude", COMPARED, "resonance.peaks[{i}].amplitude"),
    ("erpm.dominant_frequency", COMPARED, "erpm.dominant_frequency"),
    ("erpm.erpm_sample_coverage", COMPARED, "erpm.erpm_sample_coverage"),
    ("erpm.erpm_scale_assumption", COMPARED, "erpm.erpm_scale_assumption"),
    ("selected_flight_index", COMPARED, "selected_flight.index"),
    ("flight_count", COMPARED, "selected_flight.count"),
    ("problem_types", COMPARED, "projected.problem_types"),
    ("problem_severities.*", COMPARED, "projected.problem_severities.{rest}"),
)

# Fixture-specific divergences (same proven time-base cause).
_FIXTURE_RULES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "gl002_noisy": (("metrics.tracking.latency_ms", DIVERGENT, _TIME_BASE),),
}


def load_frozen_golden(fixture: str) -> dict[str, Any]:
    return json.loads(fixture_expected_path(fixture).read_text(encoding="utf-8"))


def load_fixture_options(fixture: str) -> dict[str, Any]:
    path = fixture_input_dir(fixture) / "options.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _num(raw: dict[str, str], key: str, default: float) -> float:
    value = raw.get(key)
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_fixture_samples(fixture: str) -> list[dict[str, Any]]:
    """Read ``flight.csv`` with the same row semantics the golden was frozen with.

    Mirrors donor ``golden_pipeline._row_from_csv_raw``: rows without a finite
    ``t`` are dropped, setpoints default 0.0, throttle 0.5, motors only when all
    four are finite. ``t`` stays raw float microseconds (no rounding).
    """
    rows: list[dict[str, Any]] = []
    path: Path = fixture_input_dir(fixture) / "flight.csv"
    with path.open(newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            t = _num(raw, "t", math.nan)
            if not math.isfinite(t):
                continue
            row: dict[str, Any] = {
                "gx": _num(raw, "gx", math.nan),
                "gy": _num(raw, "gy", math.nan),
                "gz": _num(raw, "gz", math.nan),
                "t": t,
                "setpoint_roll": _num(raw, "setpoint_roll", 0.0),
                "setpoint_pitch": _num(raw, "setpoint_pitch", 0.0),
                "setpoint_yaw": _num(raw, "setpoint_yaw", 0.0),
                "throttle": _num(raw, "throttle", 0.5),
            }
            motors = [_num(raw, k, math.nan) for k in ("m0", "m1", "m2", "m3") if k in raw]
            if len(motors) == 4 and all(math.isfinite(m) for m in motors):
                row["motors"] = motors
            rows.append(row)
    return rows


def run_gyrocore_analysis(fixture: str) -> dict[str, Any]:
    """GyroCore execution: public analysis entry point plus the golden's problem projection."""
    from tests.golden.projection import _problem_projection

    options = load_fixture_options(fixture)
    evidence = build_analysis_evidence(
        load_fixture_samples(fixture),
        gyro_source_is_raw_adc=False,
        hardware=options.get("hardware"),
    )
    # Same projection code that produced golden problem_types / problem_severities.
    types, severities = _problem_projection({"problems": evidence.get("problems")})
    evidence["projected"] = {"problem_types": types, "problem_severities": severities}
    return evidence


def flatten(value: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    """Leaves keyed by dotted path; lists of dicts are indexed, other lists are leaves."""
    if isinstance(value, dict) and value:
        for key, sub in value.items():
            yield from flatten(sub, f"{prefix}.{key}" if prefix else str(key))
    elif isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
        for i, sub in enumerate(value):
            yield from flatten(sub, f"{prefix}[{i}]")
    else:
        yield prefix, value


def _match(rules: tuple[tuple[str, str, str], ...], path: str) -> tuple[str, str] | None:
    for pattern, kind, target in rules:
        glob = pattern.replace("[*]", "[[]*[]]")
        if fnmatch.fnmatchcase(path, glob):
            if kind != COMPARED:
                return kind, target
            head = pattern.split("*", 1)[0]
            rest = path[len(head):] if pattern.endswith(".*") else ""
            index = ""
            if "[*]" in pattern:
                index = path[len(pattern.split("[*]", 1)[0]) + 1:].split("]", 1)[0]
            return kind, target.format(rest=rest, i=index)
    return None


def classify_golden_leaves(fixture: str, golden: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Map every analysis-scope golden leaf to (classification, target-or-reason)."""
    rules = _FIXTURE_RULES.get(fixture, ()) + _RULES
    out: dict[str, tuple[str, str]] = {}
    for key in sorted(ANALYSIS_TOP_LEVEL & golden.keys()):
        for path, _ in flatten(golden[key], key):
            hit = _match(rules, path)
            if hit is None:
                raise AssertionError(f"{fixture}: unclassified golden leaf {path}")
            out[path] = hit
    return out


def resolve(payload: Any, path: str) -> Any:
    """Follow a dotted/indexed path; raises KeyError when GyroCore lacks it."""
    cur = payload
    for part in path.replace("[", ".[").split("."):
        if part.startswith("["):
            cur = cur[int(part[1:-1])]
        else:
            if not isinstance(cur, dict) or part not in cur:
                raise KeyError(path)
            cur = cur[part]
    return cur


def compare_value(expected: Any, actual: Any) -> str | None:
    """Return a mismatch description, or None when equal under the field rules.

    bool/str/None/lists are exact; numbers compare with FLOAT_REL_TOL (int vs float
    representation is accepted only when numerically equal within tolerance).
    """
    if isinstance(expected, bool) or isinstance(actual, bool):
        return None if type(expected) is type(actual) and expected == actual else "exact"
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        e, a = float(expected), float(actual)
        if math.isnan(e) or math.isnan(a):
            return None if math.isnan(e) and math.isnan(a) else "nan"
        if abs(a - e) <= max(FLOAT_ABS_FLOOR, FLOAT_REL_TOL * abs(e)):
            return None
        return f"abs={abs(a - e):.3e} rel={abs(a - e) / abs(e) if e else math.inf:.3e}"
    return None if expected == actual else "exact"
