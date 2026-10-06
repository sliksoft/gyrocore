"""Core-domain errors for GyroCore.

These replace HTTP/JSONResponse failure modes for library callers.

Expected analysis outcomes such as a blocked tune remain domain *data*
(``AnalyzeResult`` / safety views), not exceptions.
"""

from __future__ import annotations


class GyroCoreError(Exception):
    """Base error for GyroCore Core program/IO failures."""


class InvalidInputError(GyroCoreError, ValueError):
    """Caller-supplied inputs are missing, contradictory, or out of range."""


class DecodeError(GyroCoreError):
    """Blackbox decode failed (binary missing, subprocess failure, empty CSV, etc.)."""


class ParseError(GyroCoreError):
    """Decoded log / CLI parse failed."""


class UnsupportedFirmwareError(GyroCoreError):
    """Firmware is outside Core support for the requested operation."""


class AnalysisError(GyroCoreError):
    """Analysis pipeline failed unexpectedly (not a normal blocked/limited outcome)."""


class ConfigurationError(GyroCoreError):
    """Core configuration is invalid."""


class SafetyBlockedError(GyroCoreError):
    """
    Raised only when a caller demands an actionable CLI and safety forbids it.

    Ordinary blocked/limited results are carried on ``AnalyzeResult``; this error
    is for APIs that explicitly require an actionable tune and refuse to return one.
    """
