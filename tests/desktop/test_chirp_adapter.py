"""Desktop CHIRP adapter: real reference series, status passed through, no empty-series PASS."""

from __future__ import annotations

import gzip
import math
import shutil
from pathlib import Path

import pytest

from apps.desktop.worker import analyze_local

ROOT = Path(__file__).resolve().parents[2]
WU7 = ROOT / "tests" / "fixtures" / "chirp" / "wu7" / "bbl"

needs_decoder = pytest.mark.skipif(shutil.which("blackbox_decode") is None, reason="blackbox_decode not on PATH")


def _bbl(tmp_path: Path, name: str) -> Path:
    p = tmp_path / f"{name}.bbl"
    p.write_bytes(gzip.decompress((WU7 / f"{name}.bbl.gz").read_bytes()))
    return p


@needs_decoder
@pytest.mark.parametrize(("name", "status"), [("clean_single_axis", "ok"), ("repeated_axis", "usable_with_warnings")])
def test_usable_chirp_has_aligned_reference_series(tmp_path, name, status):
    c = analyze_local._chirp_from_core(_bbl(tmp_path, name), None)
    assert c["available"] is True
    assert c["status"] == status
    assert c["quality"] == status
    n = len(c["magnitude"])
    assert n > 8 and len(c["phase"]) == n and len(c["coherence"]) == n
    assert all(math.isfinite(p["hz"]) for p in c["magnitude"])
    ref = c["core"]["axes"][c["axis"]]["transfer_function"]
    assert [p["hz"] for p in c["magnitude"]] == ref["frequencies_hz"]
    assert [p["value"] for p in c["coherence"]] == ref["coherence"]


@needs_decoder
def test_unusable_chirp_is_not_available(tmp_path):
    c = analyze_local._chirp_from_core(_bbl(tmp_path, "poor_coherence"), None)
    assert c["available"] is False
    assert c["status"] == "unusable"
    assert c["magnitude"] == c["phase"] == c["coherence"] == []


class _Usable:
    """A usable reference result whose transfer function carries no arrays."""

    detected = True
    usable = True
    status = "ok"
    warnings = ()
    errors = ()

    def __init__(self, tf):
        self._tf = tf

    def to_dict(self, include_arrays=False):
        return {"axes": {"roll": {"usable": True, "transfer_function": self._tf, "quality": {}}}}


@pytest.mark.parametrize(
    "tf",
    [
        None,
        {},
        {"frequency_hz": [1.0, 2.0], "magnitude_db": [0.0, 0.0], "phase_deg": [0.0, 0.0], "coherence": [1.0, 1.0]},
        {"frequencies_hz": [1.0, 2.0], "magnitude_db": [0.0, 0.0], "phase_deg": [0.0], "coherence": [1.0, 1.0]},
    ],
    ids=["no_tf", "empty_tf", "legacy_key", "length_mismatch"],
)
def test_available_true_with_empty_series_is_impossible(monkeypatch, tmp_path, tf):
    monkeypatch.setattr(analyze_local, "identify_chirp_system_from_bbl", lambda *a, **k: _Usable(tf))
    c = analyze_local._chirp_from_core(tmp_path / "x.bbl", None)
    assert c["available"] is False
    assert c["reason"] == "chirp_series_empty"
    assert c["magnitude"] == c["phase"] == c["coherence"] == []
