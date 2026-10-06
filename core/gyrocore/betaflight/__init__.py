"""GyroCore Betaflight / CLI / configuration foundation (WU2).

Library-only: no FastAPI, sessions, Redis, DB, auth, or desktop IPC.
Does not analyze flights or emit actionable tune CLI.
"""

from __future__ import annotations

from .baseline import (
    effective_current_tune_baseline,
    is_structurally_valid_baseline_slice,
)
from .cli import cli_dump_baseline_strictly_valid, parse_cli_dump
from .cli_profile import (
    parse_cli_baseline_with_profile_isolation,
    parse_cli_profile_blocks,
    resolve_cli_profile_context,
)
from .defaults import load_betaflight_defaults
from .effective_config import build_board_overlay, build_effective_config
from .parser import parse_tuning_headers, tuning_profile_cli_strictly_valid
from .support import resolve_support_matrix_policy
from .target_defaults import load_target_defaults
from .validation import validate_config_log_consistency
from .version import classify_betaflight_version, classify_firmware_metadata
from .vocabulary import (
    enrich_cli_status_vocabulary,
    resolve_user_facing_cli_state,
)

__all__ = [
    "build_board_overlay",
    "build_effective_config",
    "classify_betaflight_version",
    "classify_firmware_metadata",
    "cli_dump_baseline_strictly_valid",
    "effective_current_tune_baseline",
    "enrich_cli_status_vocabulary",
    "is_structurally_valid_baseline_slice",
    "load_betaflight_defaults",
    "load_target_defaults",
    "parse_cli_baseline_with_profile_isolation",
    "parse_cli_dump",
    "parse_cli_profile_blocks",
    "parse_tuning_headers",
    "resolve_cli_profile_context",
    "resolve_support_matrix_policy",
    "resolve_user_facing_cli_state",
    "tuning_profile_cli_strictly_valid",
    "validate_config_log_consistency",
]
