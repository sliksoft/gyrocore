"""Backward-compatible facade for hardware plausibility evaluation."""
from __future__ import annotations

from gyrocore.analysis._support.hardware_compatibility import evaluate_hardware_compatibility


def evaluate_hardware_plausibility(hardware):
    return evaluate_hardware_compatibility(hardware)
