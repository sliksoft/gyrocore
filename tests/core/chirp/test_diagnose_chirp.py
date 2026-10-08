"""The real-flight CHIRP diagnostic tool reports the reference verdict verbatim."""

from __future__ import annotations

import gzip
import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools" / "chirp_reference" / "diagnose_chirp.py"
WU7 = ROOT / "tests" / "fixtures" / "chirp" / "wu7" / "bbl"

pytestmark = pytest.mark.skipif(shutil.which("blackbox_decode") is None, reason="blackbox_decode not on PATH")


def _diagnose(tmp_path: Path, name: str) -> dict:
    spec = importlib.util.spec_from_file_location("diagnose_chirp", TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    bbl = tmp_path / f"{name}.bbl"
    bbl.write_bytes(gzip.decompress((WU7 / f"{name}.bbl.gz").read_bytes()))
    return module.diagnose_bbl(bbl)


def test_clean_fixture_is_event_free_and_passes(tmp_path):
    log = _diagnose(tmp_path, "clean_single_axis")["logs"][0]
    assert log["status"] == "ok"
    roll = log["axes"]["roll"]
    assert roll["usable"] is True
    assert roll["disturbance_events"] == []
    assert roll["coherence"]["gate_mean"] >= 0.6
    assert roll["timestamps"]["gap_count"] == 0


def test_chirp_cut_by_log_end_is_named(tmp_path):
    roll = _diagnose(tmp_path, "chirp_at_log_end")["logs"][0]["axes"]["roll"]
    assert roll["segment"]["end_cause"] == "log_ended_during_chirp"


def test_low_coherence_verdict_is_the_reference_verdict(tmp_path):
    log = _diagnose(tmp_path, "poor_coherence")["logs"][0]
    assert log["status"] == "unusable"
    assert "roll:low_coherence" in log["errors"]
    roll = log["axes"]["roll"]
    assert roll["usable"] is False
    assert roll["gates"]["low_coherence"]["passed"] is False
    assert roll["coherence"]["gate_mean"] < 0.6
