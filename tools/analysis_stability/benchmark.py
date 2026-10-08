#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy>=1.24", "scipy>=1.10"]
# ///
# How to run:
# Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh
# PYTHONPATH=.:core uv run tools/analysis_stability/benchmark.py REAL_BBL LOG_INDEX current|full
"""Single-process stage timings and peak RSS; compare in separate processes.

Run after sensitivity/gate jobs finish. This compares CURRENT to the FULL DATA
experiment, not an implemented before/after change. Full rows include dictionary
materialization; no proposal or tune computation is timed.
"""

from __future__ import annotations

import json
import resource
import sys
import time
from enum import StrEnum
from pathlib import Path
from typing import assert_never

from gyrocore.analysis.evidence import build_analysis_evidence
from gyrocore.analysis.resonance import analyze_resonance
from gyrocore.analysis.signal_composition import compute_spectral_bundle
from gyrocore.decode import decode_bbl
from gyrocore.parse.blackbox_csv import parse_csv_with_meta
from tools.analysis_stability.run import full_rows


class Policy(StrEnum):
    CURRENT = "current"
    FULL = "full"


def benchmark(path: Path, index: int, policy: Policy) -> None:
    """Print timings at the actual decode/parser/evidence boundaries."""
    start = time.perf_counter()
    decoded = decode_bbl(path, log_index=index)
    decode_seconds = time.perf_counter() - start
    start = time.perf_counter()
    match policy:
        case Policy.CURRENT:
            samples, meta = parse_csv_with_meta(decoded.csv_text)
            original_count = meta.get("original_sample_count")
        case Policy.FULL:
            samples = full_rows(decoded.csv_text)
            original_count = None
        case unreachable:
            assert_never(unreachable)
    prepare_seconds = time.perf_counter() - start
    start = time.perf_counter()
    evidence = build_analysis_evidence(samples, raw_sample_count=original_count)
    analysis_seconds = time.perf_counter() - start
    bundle = compute_spectral_bundle(evidence["samples"])
    start = time.perf_counter()
    analyze_resonance(bundle["merged_freqs"], bundle["merged_spectrum"], bundle["gx"], bundle["fs"])
    resonance_seconds = time.perf_counter() - start
    print(json.dumps({"policy": policy, "log_index": index, "input_rows": len(samples),
        "selected_rows": len(evidence["samples"]), "decode_seconds": decode_seconds,
        "input_prepare_seconds": prepare_seconds, "analysis_seconds": analysis_seconds,
        "resonance_seconds": resonance_seconds,
        "rss_highwater_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}))


if __name__ == "__main__":
    benchmark(Path(sys.argv[1]), int(sys.argv[2]), Policy(sys.argv[3]))
