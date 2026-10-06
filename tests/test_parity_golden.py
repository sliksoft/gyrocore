"""Golden parity tests against frozen legacy DOMAIN projections."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.golden.compare import compare_projections
from tests.golden.legacy_oracle import (
    NewCoreNotImplemented,
    load_expected_golden,
    load_fixture_metadata,
    run_fixture_oracle,
)
from tests.golden.paths import aerotuner_root, fixture_expected_path, list_live_oracle_fixtures
from tests.golden.safety import assert_safety_invariants


def _aerotuner_available() -> bool:
    try:
        root = aerotuner_root()
    except FileNotFoundError:
        return False
    return (root / "backend" / "routes" / "analyze.py").is_file()


pytestmark = pytest.mark.skipif(
    not _aerotuner_available(),
    reason="AeroTuner donor not available (set AEROTUNER_ROOT)",
)


LIVE_FIXTURES = [
    "gl001_clean",
    "gl002_noisy",
    "gl001_with_cli",
]


@pytest.mark.parametrize("fixture_name", LIVE_FIXTURES)
def test_live_legacy_oracle_matches_frozen_golden(fixture_name: str):
    meta = load_fixture_metadata(fixture_name)
    assert meta["oracle_mode"] == "live_legacy"
    expected_path = fixture_expected_path(fixture_name)
    assert expected_path.is_file(), (
        f"Missing frozen golden {expected_path}. "
        "Run: python tools/update_legacy_golden.py"
    )
    expected = load_expected_golden(fixture_name)
    actual = run_fixture_oracle(fixture_name)
    assert_safety_invariants(actual, require_full_safety=True)
    compare_projections(expected, actual)


def test_whoop75_snapshot_partial_frozen_and_bbl_blocked():
    meta = load_fixture_metadata("whoop75_cli_snapshot")
    assert meta["real_bbl_status"] == "BLOCKED_REAL_BBL_FIXTURE"
    assert meta["oracle_mode"] == "snapshot_partial"
    expected = load_expected_golden("whoop75_cli_snapshot")
    actual = run_fixture_oracle("whoop75_cli_snapshot")
    assert actual.get("real_bbl_status") == "BLOCKED_REAL_BBL_FIXTURE"
    assert_safety_invariants(actual, require_full_safety=False)
    compare_projections(expected, actual)


def test_dual_runner_new_side_not_implemented():
    """WU0 must not fake NEW==OLD by calling the same function twice."""
    core = NewCoreNotImplemented()
    with pytest.raises(NotImplementedError):
        core.analyze()


def test_list_live_oracle_fixtures_discovers_csv_fixtures():
    names = list_live_oracle_fixtures()
    assert "gl001_clean" in names
    assert "gl002_noisy" in names
    assert "whoop75_cli_snapshot" not in names


def test_frozen_goldens_declare_ai_disabled():
    for name in LIVE_FIXTURES + ["whoop75_cli_snapshot"]:
        data = json.loads(Path(fixture_expected_path(name)).read_text(encoding="utf-8"))
        assert data.get("ai_disabled") is True
