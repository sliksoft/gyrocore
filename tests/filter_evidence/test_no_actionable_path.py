"""Architectural guard: WU13 diagnostics must not reach authorize_cli."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = [
    ROOT / "core/gyrocore/filter_evidence",
    ROOT / "core/gyrocore/throttle_analysis",
    ROOT / "core/gyrocore/verification",
]

FORBIDDEN = (
    "authorize_cli",
    "ActionableTuneBundle",
    "run_safety_pipeline",
    "BayesianPIDOptimizer",
    "recommendGains",
    "serial",
    "msp_write",
)


def test_wu13_packages_do_not_import_actionable_path():
    for package in PACKAGES:
        for path in package.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for token in FORBIDDEN:
                assert token not in text, f"{path} contains forbidden token {token}"


def test_filter_result_actionable_false_invariant():
    from gyrocore.filter_evidence import analyze_filter_evidence

    samples = [
        {
            "time": i / 1000.0,
            "gyroADC[0]": 0.1,
            "gyroADC[1]": 0.1,
            "gyroADC[2]": 0.1,
            "rcCommand[3]": 1400,
        }
        for i in range(2000)
    ]
    result = analyze_filter_evidence(samples, sample_rate_hz=1000.0)
    d = result.to_dict()
    assert d["actionable"] is False
    assert d["filter_candidate"]["actionable"] is False
