#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.24", "scipy>=1.10"]
# ///
# How to run:
# Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# PYTHONPATH=.:core uv run tools/analysis_stability/summarize.py OUTPUT_DIR [REAL_BBL]
"""Derive compact observations, preserving complete measurement JSON artifacts.

Reads actual oscillation problems, never equates them with resonance severity.
Restoring a tail is compared to that tail's shortened source. D is recomputed
on normalized, flight-selected full rows for older artifacts made on raw rows.
The repaired D input stage and its own runtime are explicit in summary.json.
"""

from __future__ import annotations

import json
import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from gyrocore.decode import decode_bbl
from gyrocore.preprocess.flight_selection import select_best_flight_for_analysis
from gyrocore.preprocess.normalize import normalize_raw_samples
from tools.analysis_stability.policies import perturbations, window_summary
from tools.analysis_stability.run import full_rows


@dataclass(frozen=True, slots=True)
class SourceMismatchError(ValueError):
    """A summary must not combine observations from different real flights."""
    expected: str
    actual: str

    def __str__(self) -> str:
        return f"real BBL SHA256 mismatch: expected {self.expected}, got {self.actual}"


def summarize(directory: Path, real_path: Path | None = None) -> None:
    """Summarize measured Core outputs; D classification remains unavailable."""
    reports = []
    real_digest = hashlib.sha256(real_path.read_bytes()).hexdigest() if real_path is not None else None
    for path in sorted(directory.glob("*.json")):
        if path.name in {"summary.json", "chirp-proof.json"} or path.name.endswith("-source.json"):
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        normalized_d = {}
        if real_path is not None and path.stem.startswith("real_log"):
            provenance = json.loads(path.with_name(path.stem + "-source.json").read_text(encoding="utf-8"))
            if provenance["sha256"] != real_digest:
                raise SourceMismatchError(provenance["sha256"], real_digest)
            index = int(path.stem[-1]) - 1
            rows = full_rows(decode_bbl(real_path, log_index=index).csv_text)
            for case, samples in perturbations(rows):
                start = time.perf_counter()
                normalized, scale = normalize_raw_samples(samples)
                selected, _, _, _ = select_best_flight_for_analysis(normalized)
                normalized_d[case] = {**window_summary(selected), "gyro_scale": scale,
                    "input_stage": "normalized_selected_full_flight", "seconds": time.perf_counter() - start}
        entries = []
        for r in data["results"]:
            comparison = r["case"].replace("tail_add", "tail_remove") if r["case"].startswith("tail_add") else "complete"
            if r["policy"] == "D_WINDOWED_AGGREGATION":
                derived = normalized_d.get(r["case"], r)
                entries.append({"case": r["case"], "policy": r["policy"], "comparison_case": comparison,
                    "classification": "UNAVAILABLE_NOT_CALIBRATED",
                    **{k: derived.get(k) for k in ("input_stage", "gyro_scale", "available", "windows", "rejected_windows",
                        "bin_hz", "peaks_hz", "peaks_psd", "transient_peaks_hz", "transient_peak_windows", "band_power", "spectrum_digest", "seconds")}})
                continue
            res = r["resonance"]
            safety = r["safety"]
            entries.append({"case": r["case"], "policy": r["policy"], "comparison_case": comparison,
                "clusters": [c["center"] for c in res.get("clusters", [])],
                "cluster_scores": [c["score"] for c in res.get("clusters", [])],
                "cluster_amplitudes": [c["total_amplitude"] for c in res.get("clusters", [])],
                "primary": res.get("primary"), "spread": res.get("spread"),
                "oscillation": [{k: p[k] for k in ("severity", "confidence")} for p in r["problems"].get("problems", []) if p["type"] == "oscillation"],
                "resonance_severity": r["metrics_resonance"]["severity"],
                "confidence": r["confidence"]["score"], "quality": r["quality"]["score"],
                "noise": r["noise"], "propwash": r["propwash"],
                "cadence_us": r["cadence_us"], "sample_rate_hz": r["sample_rate_hz"],
                "indices_digest": r["indices_digest"], "identities_lost": r["identities_lost_vs_complete"],
                "count": r["input_count"], "selected_count": r["selected_count"],
                "prepare_seconds": r["prepare_seconds"], "analysis_seconds": r["analysis_seconds"],
                "resonance_seconds": r["resonance_seconds"], "retained_bytes_estimate": r["input_retained_bytes_estimate"],
                "rss_highwater_kib": r["rss_highwater_kib"],
                "peak_threshold": r["peak_threshold"], "near_481hz_max": r["near_481hz_max"],
                "tune_digest": r["tune_digest"], "safety": safety,
                "gyro_scale": r["gyro_scale"], "reference_window_psd": r["reference_window_psd"]})
        reports.append({"name": data["name"], "source_rows": data["source_rows"], "results": entries})
    (directory / "summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    for report in reports:
        print(report["name"])
        for entry in report["results"]:
            if entry["case"] != "complete":
                continue
            print(entry["policy"], {k: entry.get(k) for k in ("count", "clusters", "confidence", "oscillation", "analysis_seconds", "peaks_hz", "windows", "seconds")})


if __name__ == "__main__":
    summarize(Path(sys.argv[1]), Path(sys.argv[2]) if len(sys.argv) > 2 else None)
