"""WU17: safety-adapter mapping of analysis evidence onto mechanical-gate inputs."""

from __future__ import annotations

import pytest

from gyrocore.safety.analysis_adapter import mechanical_inputs_from_analysis


def _evidence(value, hf_ratio):
    return {"ok": True, "metrics": {"noise": {"value": value, "hf_ratio": hf_ratio}}}


@pytest.mark.parametrize(
    ("cleanliness", "hf_ratio", "expected"),
    [
        # metrics.noise.value is cleanliness (higher = cleaner), banded like the donor route.
        (99.9, 0.0, "LOW"),
        (75.0, 0.0, "LOW"),
        (74.9, 0.0, "MEDIUM"),
        (50.0, 0.0, "MEDIUM"),
        (49.9, 0.0, "HIGH"),
        (0.0, 0.0, "HIGH"),
        # hf_ratio must not override cleanliness (it is a 0-1 ratio on another scale).
        (49.9, 0.2, "HIGH"),
        (46.0, 0.34, "HIGH"),
        (99.9, 0.7, "LOW"),
    ],
)
def test_noise_level_follows_cleanliness_bands(cleanliness, hf_ratio, expected):
    assert mechanical_inputs_from_analysis(_evidence(cleanliness, hf_ratio))["noise_level"] == expected


def test_noise_level_missing_value_is_conservative():
    assert mechanical_inputs_from_analysis(_evidence(None, 0.0))["noise_level"] == "HIGH"
