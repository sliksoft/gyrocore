"""Authorized Betaflight CLI generation (WU11).

Public entry: :func:`authorize_cli` on a completed ``FinalSafeTuneResult``.
No serial, USB, MSP, or flight-controller I/O.
"""

from gyrocore.cli.authorize import authorize_cli
from gyrocore.cli.results import (
    KIND_ACTIONABLE,
    KIND_DENIAL,
    KIND_PREVIEW,
    ActionableTuneBundle,
    CliAuthorizationResult,
    TuneCliDenial,
    TuneCliPreview,
)
from gyrocore.cli.settings import CANONICAL_SET_ORDER, FIRMWARE_CLI_PROVENANCE, SAVE_COMMAND

__all__ = [
    "ActionableTuneBundle",
    "CANONICAL_SET_ORDER",
    "CliAuthorizationResult",
    "FIRMWARE_CLI_PROVENANCE",
    "KIND_ACTIONABLE",
    "KIND_DENIAL",
    "KIND_PREVIEW",
    "SAVE_COMMAND",
    "TuneCliDenial",
    "TuneCliPreview",
    "authorize_cli",
]
