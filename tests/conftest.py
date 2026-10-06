"""Pytest bootstrap for GyroCore WU0 parity tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Default donor location for local development.
os.environ.setdefault("AEROTUNER_ROOT", str(REPO_ROOT.parent / "aerotuner"))


@pytest.fixture(autouse=True)
def _disable_ai_for_all_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GYROCORE_AI_EXPLANATIONS_ENABLED", "0")
    monkeypatch.setenv("GYROCORE_AI_PROVIDER", "disabled")
    monkeypatch.setenv("AEROTUNER_BYPASS_ANALYSIS_CACHE", "1")
