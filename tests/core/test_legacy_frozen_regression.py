"""WU15: donor-free numeric regression of GyroCore analysis vs frozen legacy goldens.

Runs in normal CI without AeroTuner. See ``tests/golden/frozen_regression.py``
for provenance, field classification and tolerance rationale.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.golden.frozen_regression import (
    ANALYSIS_TOP_LEVEL,
    COMPARED,
    DIVERGENT,
    OUT_OF_SCOPE_TOP_LEVEL,
    REGRESSION_FIXTURES,
    classify_golden_leaves,
    compare_value,
    flatten,
    load_frozen_golden,
    resolve,
    run_gyrocore_analysis,
)

HELPER = Path(__file__).resolve().parents[1] / "golden" / "frozen_regression.py"

_EVIDENCE: dict[str, dict] = {}


def evidence_for(fixture: str) -> dict:
    if fixture not in _EVIDENCE:
        _EVIDENCE[fixture] = run_gyrocore_analysis(fixture)
    return _EVIDENCE[fixture]


@pytest.mark.parametrize("fixture", REGRESSION_FIXTURES)
def test_golden_scope_is_fully_accounted(fixture):
    golden = load_frozen_golden(fixture)
    assert set(golden) == ANALYSIS_TOP_LEVEL | OUT_OF_SCOPE_TOP_LEVEL
    classes = classify_golden_leaves(fixture, golden)  # raises on any unclassified leaf
    assert sum(1 for kind, _ in classes.values() if kind == COMPARED) >= 150


@pytest.mark.parametrize("fixture", REGRESSION_FIXTURES)
def test_gyrocore_matches_frozen_golden(fixture):
    golden = load_frozen_golden(fixture)
    evidence = evidence_for(fixture)
    leaves = dict(
        leaf for key in ANALYSIS_TOP_LEVEL & golden.keys() for leaf in flatten(golden[key], key)
    )
    mismatches = []
    for path, (kind, target) in classify_golden_leaves(fixture, golden).items():
        if kind != COMPARED:
            continue
        try:
            actual = resolve(evidence, target)
        except (KeyError, IndexError, TypeError):
            mismatches.append(f"{path} -> {target}: missing in GyroCore output")
            continue
        why = compare_value(leaves[path], actual)
        if why:
            mismatches.append(f"{path} -> {target}: golden={leaves[path]!r} gyrocore={actual!r} ({why})")
    assert not mismatches, "\n".join(mismatches)


@pytest.mark.parametrize("fixture", REGRESSION_FIXTURES)
def test_resonance_peak_count_matches_golden(fixture):
    golden_peaks = load_frozen_golden(fixture)["metrics"]["resonance"]["peaks"]
    evidence = evidence_for(fixture)
    assert len(evidence["metrics"]["resonance"]["peaks"]) == len(golden_peaks) > 0
    assert len(evidence["resonance"]["peaks"]) == len(golden_peaks)


@pytest.mark.parametrize("fixture", REGRESSION_FIXTURES)
def test_divergent_fields_carry_a_recorded_cause(fixture):
    classes = classify_golden_leaves(fixture, load_frozen_golden(fixture))
    for path, (kind, reason) in classes.items():
        if kind == DIVERGENT:
            assert reason.startswith("time base:"), path


def test_regression_helper_is_donor_free():
    tree = ast.parse(HELPER.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not {m for m in imported if m.startswith("backend") or "legacy_oracle" in m}
    source = HELPER.read_text(encoding="utf-8")
    assert "aerotuner_root" not in source and "AEROTUNER_ROOT" not in source
