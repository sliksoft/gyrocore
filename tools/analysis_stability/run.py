#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.24", "scipy>=1.10"]
# ///
# How to run:
# Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# PYTHONPATH=.:core uv run tools/analysis_stability/run.py OUTPUT_DIR [REAL_BBL CLI_FILE]
# Existing project environment: PYTHONPATH=.:core python tools/analysis_stability/run.py ...
"""Offline policy experiments. No production mutation or candidate promotion.

All full-pipeline experiments reuse the existing evidence and safety functions.
Tune is computed from full BBL once: parser policies do not feed autotune.
D is a PSD/transient prototype only: downstream classification is unavailable.
Runtime observations are single runs; RSS is process high-water, not allocation.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import resource
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypeAlias
from unittest.mock import patch

import numpy as np
import scipy

from gyrocore.analysis.evidence import build_analysis_evidence
from gyrocore.analysis.resonance import analyze_resonance
from gyrocore.analysis.signal_composition import compute_spectral_bundle
from gyrocore.autotune import propose_absolute_tune, recommend_autotune_from_bbl
from gyrocore.autotune.absolute import AbsoluteTuneProposal
from gyrocore.chirp.pipeline import identify_chirp_system
from gyrocore.decode import decode_bbl
from gyrocore.parse import blackbox_csv
from gyrocore.safety.pipeline import run_safety_pipeline
from gyrocore.preprocess.normalize import normalize_raw_samples
from gyrocore.preprocess.flight_selection import select_best_flight_for_analysis
from tools.analysis_stability.policies import (
    Sample, contiguous_window, perturbations, resample_grid, select_current,
    synthetic_samples, noise_samples, window_summary,
)

Json: TypeAlias = None | bool | int | float | str | list["Json"] | dict[str, "Json"]
ROOT: Final = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class ObservationContext:
    """Input provenance and the unchanged full-data tuning proposal."""
    source_count: int
    capped: bool
    proposal: AbsoluteTuneProposal | None = None


@dataclass(frozen=True, slots=True)
class ExperimentOutput:
    """Artifact destination with the source's full-data proposal."""
    directory: Path
    proposal: AbsoluteTuneProposal | None = None


def digest(value: Json) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def full_rows(text: str) -> list[Sample]:
    """Research-only cap override scoped to this process; preserve every field."""
    with patch.object(blackbox_csv, "MAX_PARSED_SAMPLES", max(20_000, text.count("\n") + 1)):
        rows = blackbox_csv.parse_csv(text)
    for i, row in enumerate(rows):
        row["source_index"] = i
    return rows


def legacy_rows(path: Path) -> list[Sample]:
    """Adapt committed golden CSV aliases, which the production parser lacks."""
    import csv
    with path.open(encoding="utf-8") as stream:
        return [Sample(t=int(float(r["t"])), gx=float(r["gx"]), gy=float(r["gy"]), gz=float(r["gz"]),
            throttle=float(r["throttle"]), motors=[float(r[k]) for k in ("m0", "m1", "m2", "m3")],
            source_index=i, **{k: float(r[k]) for k in ("setpoint_roll", "setpoint_pitch", "setpoint_yaw")})
            for i, r in enumerate(csv.DictReader(stream))]


def measure(samples: list[Sample], context: ObservationContext) -> dict[str, Json]:
    """Record legacy behavior and separate normalized spectral diagnostics."""
    start = time.perf_counter()
    evidence = build_analysis_evidence(samples,
        raw_sample_count=context.source_count if context.capped else None)
    analysis_seconds = time.perf_counter() - start
    selected = evidence["samples"]
    t = np.array([s["t"] for s in selected], dtype=float)
    dt = np.diff(t)
    bundle = compute_spectral_bundle(selected)
    start = time.perf_counter()
    analyze_resonance(bundle["merged_freqs"], bundle["merged_spectrum"], bundle["gx"], bundle["fs"])
    spectral_seconds = time.perf_counter() - start
    resonance = evidence["resonance"]
    metrics = evidence["metrics"]
    ids = [s.get("source_index", s["t"]) for s in samples]
    result = {
        "input_count": len(samples), "selected_count": len(selected),
        "indices_digest": digest(ids), "source_identities": ids,
        "cadence_us": {"median": float(np.median(dt)), "mean": float(np.mean(dt)),
            "min": float(np.min(dt)), "max": float(np.max(dt)),
            "p01": float(np.quantile(dt, .01)), "p99": float(np.quantile(dt, .99)),
            "gap_count": int(np.sum(dt > 1.5 * np.median(dt))),
            "nonpositive": int(np.sum(dt <= 0))},
        "sample_rate_hz": evidence["sample_rate_hz"],
        "resonance": resonance, "quality": evidence["quality"],
        "gyro_scale": evidence["gyro_scale"],
        "noise": metrics.get("noise"), "propwash": metrics.get("propwash"),
        "resonance_severity": metrics.get("resonance", {}).get("severity"), "confidence": evidence["confidence"],
        "oscillation": [p for p in evidence["problems"].get("problems", []) if p.get("type") == "oscillation"],
        "metrics_resonance": metrics.get("resonance"),
        "problems": evidence["problems"], "sample_rate_metadata": evidence["sample_rate_metadata"],
        "analysis_seconds": analysis_seconds, "resonance_seconds": spectral_seconds,
        "peak_threshold": float(np.mean(bundle["merged_spectrum"][(bundle["merged_freqs"] >= 30) & (bundle["merged_freqs"] <= 500)]) +
            1.8 * np.std(bundle["merged_spectrum"][(bundle["merged_freqs"] >= 30) & (bundle["merged_freqs"] <= 500)])),
        "near_481hz_max": float(np.max(bundle["merged_spectrum"][(bundle["merged_freqs"] >= 475) & (bundle["merged_freqs"] <= 487)]))
            if np.any((bundle["merged_freqs"] >= 475) & (bundle["merged_freqs"] <= 487)) else None,
        "rss_highwater_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "input_retained_bytes_estimate": len(samples) * (sys.getsizeof(samples[0]) +
            sum(sys.getsizeof(v) for v in samples[0].values())) + sys.getsizeof(samples),
        "reference_window_psd": window_summary(selected),
        "safety": None if context.proposal is None else run_safety_pipeline(context.proposal, analysis=evidence).to_dict(),
        "tune_digest": None if context.proposal is None else digest(context.proposal.to_dict()),
    }
    # Keep NumPy out of JSON and omit the large identity list from the artifact.
    return json.loads(json.dumps(result, default=lambda x: x.tolist()))


def evaluate(name: str, samples: list[Sample], output: ExperimentOutput) -> None:
    """All policies see exactly the same row-preserving perturbations."""
    results = []
    baseline: dict[str, set[int | float | str]] = {}
    for case, rows in perturbations(samples):
        for label, selector in (("A_CURRENT", select_current), ("B_TIMESTAMP_RESAMPLE", resample_grid),
                                ("C_CONTIGUOUS_WINDOWS", contiguous_window), ("E_FULL_DATA", list)):
            start = time.perf_counter()
            inputs = selector(rows)
            prep = time.perf_counter() - start
            measured = measure(inputs, ObservationContext(len(rows), label == "A_CURRENT", output.proposal))
            identities = measured.pop("source_identities")
            identity_set = set(identities)
            if case == "complete":
                baseline[label] = identity_set
            measured["identities_lost_vs_complete"] = len(baseline[label] - identity_set)
            measured["prepare_seconds"] = prep
            comparison = case.replace("tail_add", "tail_remove") if case.startswith("tail_add") else "complete"
            results.append({"case": case, "policy": label, "comparison_case": comparison, **measured})
        start = time.perf_counter()
        normalized, scale = normalize_raw_samples(rows)
        selected, _, _, _ = select_best_flight_for_analysis(normalized)
        results.append({"case": case, "policy": "D_WINDOWED_AGGREGATION",
            "diagnostic_only": True, "classification": "UNAVAILABLE_NOT_CALIBRATED",
            "input_stage": "normalized_selected_full_flight", "gyro_scale": scale,
            **window_summary(selected), "seconds": time.perf_counter() - start})
        print(f"{name}: {case}", flush=True)
    (output.directory / f"{name}.json").write_text(json.dumps({"name": name, "source_rows": len(samples),
        "python": sys.version, "numpy": np.__version__, "scipy": scipy.__version__,
        "results": results}, indent=2), encoding="utf-8")


def chirp_proof(output: Path) -> None:
    """Actual CHIRP transfer/coherence/gates hashes with untouched full CSV."""
    rows = []
    for name in ("three_axis_sequence", "chirp_at_log_end"):
        source = ROOT / f"tests/fixtures/chirp/wu7/bbl/{name}.bbl.gz"
        temporary = output / f"{name}.bbl"
        temporary.write_bytes(gzip.decompress(source.read_bytes()))
        decoded = decode_bbl(temporary, log_index=0)
        header = temporary.read_bytes()
        before = identify_chirp_system(csv_text=decoded.csv_text, headers=header).to_dict(include_arrays=True)
        samples = full_rows(decoded.csv_text)
        for selector in (select_current, resample_grid, contiguous_window, list):
            selector(samples)
        window_summary(samples)
        after = identify_chirp_system(csv_text=decoded.csv_text, headers=header).to_dict(include_arrays=True)
        rows.append({"fixture": name, "before": digest(before), "after": digest(after),
                     "equal": before == after, "detected": before["detected"], "status": before["status"]})
        temporary.unlink()
    (output / "chirp-proof.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


def main() -> None:
    """Write artifacts to the explicitly supplied directory outside user files."""
    output = Path(sys.argv[1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if "--real-only" not in sys.argv:
        chirp_proof(output)
        for fixture in ("gl001_clean", "gl002_noisy"):
            evaluate(fixture, legacy_rows(ROOT / f"tests/fixtures/legacy/{fixture}/input/flight.csv"), ExperimentOutput(output))
        for name, samples in (("stationary", synthetic_samples()), ("short_burst", synthetic_samples(burst=True)),
                              ("true_shift", synthetic_samples(shifted=True))):
            evaluate(name, samples, ExperimentOutput(output))
        evaluate("noise_only", noise_samples(), ExperimentOutput(output))
    if len(sys.argv) > 2:
        path = Path(sys.argv[2]).resolve()
        cli = Path(sys.argv[3]).read_text(encoding="utf-8")
        for index in range(3):
            start = time.perf_counter()
            decoded = decode_bbl(path, log_index=index)
            decode_seconds = time.perf_counter() - start
            start = time.perf_counter()
            full = full_rows(decoded.csv_text)
            full_parse_seconds = time.perf_counter() - start
            start = time.perf_counter()
            parsed = blackbox_csv.parse_csv(decoded.csv_text)
            current_parse_seconds = time.perf_counter() - start
            proposal = propose_absolute_tune(recommend_autotune_from_bbl(path, cli_dump=cli, log_index=index), cli_dump=cli)
            evaluate(f"real_log{index + 1}", full, ExperimentOutput(output, proposal))
            (output / f"real_log{index + 1}-source.json").write_text(json.dumps({
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "embedded_log_index": index,
                "decode_seconds": decode_seconds, "full_parse_seconds": full_parse_seconds,
                "current_parse_seconds": current_parse_seconds, "current_rows": len(parsed),
                "full_rows": len(full)}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
