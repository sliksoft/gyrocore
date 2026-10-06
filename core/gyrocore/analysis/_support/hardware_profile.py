# GyroCore WU4: adapted from AeroTuner backend/services/hardware_profile.py
"""Canonical backend hardware profiles derived from explicit hardware class."""

from __future__ import annotations

from dataclasses import dataclass

from gyrocore.analysis._support.hardware_class import (
    HARDWARE_CLASS_VALUES,
    normalize_hardware_class,
)


@dataclass(frozen=True)
class HardwareProfile:
    hardware_class: str
    frame_size_label: str
    frame_ordinal: int
    ducted: bool
    noise_expectation: str
    typical_cells: tuple[int, ...] | None = None
    prop_size_range_inches: tuple[float, float] | None = None


_HARDWARE_PROFILES: dict[str, HardwareProfile] = {
    "whoop_1s": HardwareProfile(
        hardware_class="whoop_1s",
        frame_size_label='micro (2-3")',
        frame_ordinal=0,
        ducted=True,
        noise_expectation="high",
        typical_cells=(1,),
        prop_size_range_inches=(1.2, 2.0),
    ),
    "whoop_2s": HardwareProfile(
        hardware_class="whoop_2s",
        frame_size_label='micro (2-3")',
        frame_ordinal=0,
        ducted=True,
        noise_expectation="high",
        typical_cells=(2,),
        prop_size_range_inches=(1.6, 2.5),
    ),
    "micro_2_5_3_5": HardwareProfile(
        hardware_class="micro_2_5_3_5",
        frame_size_label='micro (2-3")',
        frame_ordinal=0,
        ducted=False,
        noise_expectation="medium",
        typical_cells=(3, 4, 6),
        prop_size_range_inches=(2.5, 3.5),
    ),
    "freestyle_5": HardwareProfile(
        hardware_class="freestyle_5",
        frame_size_label='5"',
        frame_ordinal=1,
        ducted=False,
        noise_expectation="medium",
        typical_cells=(4, 6),
        prop_size_range_inches=(4.8, 5.2),
    ),
    "racing_5": HardwareProfile(
        hardware_class="racing_5",
        frame_size_label='5"',
        frame_ordinal=1,
        ducted=False,
        noise_expectation="medium",
        typical_cells=(4, 6),
        prop_size_range_inches=(4.8, 5.2),
    ),
    "long_range_7": HardwareProfile(
        hardware_class="long_range_7",
        frame_size_label='7"+',
        frame_ordinal=2,
        ducted=False,
        noise_expectation="low",
        typical_cells=(4, 6),
        prop_size_range_inches=(6.8, 7.5),
    ),
    "long_range_10_large": HardwareProfile(
        hardware_class="long_range_10_large",
        frame_size_label='7"+',
        frame_ordinal=2,
        ducted=False,
        noise_expectation="low",
        typical_cells=(6, 8, 12),
        prop_size_range_inches=(10.0, 13.0),
    ),
    "cine_heavy": HardwareProfile(
        hardware_class="cine_heavy",
        frame_size_label='7"+',
        frame_ordinal=2,
        ducted=False,
        noise_expectation="low",
        typical_cells=(6, 8, 12),
        prop_size_range_inches=(7.0, 13.0),
    ),
}


def get_hardware_profile(hardware_class: str | None) -> HardwareProfile | None:
    normalized = normalize_hardware_class(hardware_class)
    if normalized is None:
        return None
    return _HARDWARE_PROFILES.get(normalized)


def all_hardware_profiles() -> tuple[HardwareProfile, ...]:
    """Return profiles in canonical hardware-class order for tests."""
    return tuple(_HARDWARE_PROFILES[key] for key in sorted(HARDWARE_CLASS_VALUES))


def hardware_profile_map() -> dict[str, HardwareProfile]:
    """Return a shallow copy of the canonical profile map for tests."""
    return dict(_HARDWARE_PROFILES)
