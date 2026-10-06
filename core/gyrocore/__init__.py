"""
GyroCore Python Core — foundational package.

WU1 exposes models, errors, and configuration only.
Analysis / tuning / decode engines are not migrated yet.
``GyroCore.analyze()`` is intentionally not provided in WU1.
"""

from __future__ import annotations

from .config import CoreConfig
from .errors import (
    AnalysisError,
    ConfigurationError,
    DecodeError,
    GyroCoreError,
    InvalidInputError,
    ParseError,
    SafetyBlockedError,
    UnsupportedFirmwareError,
)
from .models import (
    AnalyzeOptions,
    AnalyzeRequest,
    AnalyzeResult,
    FirmwareContext,
    FlightSelection,
    HardwareContext,
    MechanicalSafetyView,
    TuningOutputSafetyStatus,
    TuningOutputSafetyView,
    actionable_cli_allowed,
)

__all__ = [
    "AnalyzeOptions",
    "AnalyzeRequest",
    "AnalyzeResult",
    "AnalysisError",
    "ConfigurationError",
    "CoreConfig",
    "DecodeError",
    "FirmwareContext",
    "FlightSelection",
    "GyroCoreError",
    "HardwareContext",
    "InvalidInputError",
    "MechanicalSafetyView",
    "ParseError",
    "SafetyBlockedError",
    "TuningOutputSafetyStatus",
    "TuningOutputSafetyView",
    "UnsupportedFirmwareError",
    "actionable_cli_allowed",
]

__version__ = "0.1.0"
