"""Core decode must carry every valid frame across Blackbox mode events.

``tests/fixtures/decode/mode_events.bbl.gz`` (``tools/decode_reference/make_mode_event_fixture.py``)
holds FLIGHT_MODE / DISARM events whose payloads desynchronised the unpatched
``blackbox_decode`` and dropped P-frames until the next I-frame. The GyroCore-patched
decoder (docs/upstream/PATCHES.md) must return the full frame set, matching the browser
decoder. ``tools/ci/integrity.sh`` runs this file and hard-fails without a decoder.
"""

from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest

from gyrocore.decode import decode_bbl
from gyrocore.parse import parse_blackbox_csv

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "decode"

needs_decoder = pytest.mark.skipif(shutil.which("blackbox_decode") is None, reason="blackbox_decode not on PATH")


@pytest.fixture()
def mode_events_bbl(tmp_path: Path) -> Path:
    path = tmp_path / "mode_events.bbl"
    path.write_bytes(gzip.decompress((FIXTURES / "mode_events.bbl.gz").read_bytes()))
    return path


def _meta() -> dict:
    return json.loads((FIXTURES / "mode_events.json").read_text(encoding="utf-8"))


@needs_decoder
def test_decode_keeps_every_frame_across_mode_events(mode_events_bbl: Path) -> None:
    meta = _meta()
    result = decode_bbl(mode_events_bbl, log_index=0)
    rows = [line for line in result.csv_text.splitlines()[1:] if line.strip()]
    assert len(rows) != meta["unpatched_native_frame_count"], "blackbox_decode on PATH is unpatched"
    assert len(rows) == meta["frame_count"]
    iterations = [int(r.split(",", 1)[0]) for r in rows]
    assert iterations == list(range(meta["frame_count"]))


@needs_decoder
def test_parsed_series_is_contiguous(mode_events_bbl: Path) -> None:
    meta = _meta()
    parsed = parse_blackbox_csv(decode_bbl(mode_events_bbl, log_index=0).csv_text)
    assert parsed["count"] == meta["frame_count"]
    samples = parsed["samples"]
    assert [s["loop_iteration"] for s in samples] == list(range(meta["frame_count"]))
    assert all(b["t"] - a["t"] == 250 for a, b in zip(samples, samples[1:]))
