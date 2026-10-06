"""Legacy/Core parity harness (WU0)."""

from __future__ import annotations

from tests.golden.compare import compare_projections
from tests.golden.normalize import normalize_cli_text
from tests.golden.projection import extract_domain_projection
from tests.golden.safety import assert_safety_invariants

__all__ = [
    "compare_projections",
    "extract_domain_projection",
    "normalize_cli_text",
    "assert_safety_invariants",
]
