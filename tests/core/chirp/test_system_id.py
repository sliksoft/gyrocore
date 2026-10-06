"""WU6 — minimal system-ID numeric parity foundation."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from gyrocore.chirp.system_id import hanning_window, welch_transfer_function

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[2] / "fixtures" / "chirp" / "system_id_parity_vectors.json").read_text(
        encoding="utf-8"
    )
)


def test_hanning_window_matches_upstream_formula() -> None:
    expected = np.asarray(FIXTURE["hanning"]["expected"], dtype=float)
    got = hanning_window(FIXTURE["hanning"]["size"])
    assert got == pytest.approx(expected, rel=1e-12, abs=1e-12)


def test_welch_gain2_magnitude_phase_coherence() -> None:
    cfg = FIXTURE["welch_gain2"]
    fs = cfg["sample_rate_hz"]
    n = cfg["n_samples"]
    t = np.arange(n) / fs
    tone = np.sin(2.0 * np.pi * cfg["tone_hz"] * t)
    inp = tone
    out = 2.0 * tone

    tf = welch_transfer_function(
        inp,
        out,
        sample_rate_hz=fs,
        segment_size=cfg["segment_size"],
        overlap=cfg["overlap"],
    )

    # Bin nearest the tone
    k = int(round(cfg["tone_hz"] / (fs / cfg["segment_size"])))
    assert tf.magnitude_db[k] == pytest.approx(
        cfg["expected_magnitude_db"],
        abs=cfg["magnitude_tolerance_db"],
    )
    assert abs(tf.phase_deg[k]) <= cfg["phase_tolerance_deg"]
    assert tf.coherence[k] >= cfg["min_coherence"]


def test_welch_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError):
        welch_transfer_function([1, 2, 3], [1, 2], 1000.0)
    with pytest.raises(ValueError):
        welch_transfer_function([1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 3.0, 4.0], 0.0)
