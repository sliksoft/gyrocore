"""Pytest bootstrap for GyroCore tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = REPO_ROOT / "core"
for path in (REPO_ROOT, CORE_SRC):
    path_s = str(path)
    if path_s not in sys.path:
        sys.path.insert(0, path_s)

# Default donor location for local development (WU0 oracle).
os.environ.setdefault("AEROTUNER_ROOT", str(REPO_ROOT.parent / "aerotuner"))


@pytest.fixture(autouse=True)
def _disable_ai_for_all_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GYROCORE_AI_EXPLANATIONS_ENABLED", "0")
    monkeypatch.setenv("GYROCORE_AI_PROVIDER", "disabled")
    monkeypatch.setenv("AEROTUNER_BYPASS_ANALYSIS_CACHE", "1")
