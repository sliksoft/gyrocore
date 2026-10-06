"""Fixture discovery paths for the WU0 parity harness."""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURES_ROOT = _REPO_ROOT / "tests" / "fixtures" / "legacy"


def repo_root() -> Path:
    return _REPO_ROOT


def fixtures_root() -> Path:
    return _FIXTURES_ROOT


def fixture_dir(name: str) -> Path:
    path = _FIXTURES_ROOT / name
    if not path.is_dir():
        raise FileNotFoundError(f"Unknown legacy fixture: {name} ({path})")
    return path


def fixture_input_dir(name: str) -> Path:
    return fixture_dir(name) / "input"


def fixture_expected_path(name: str) -> Path:
    return fixture_dir(name) / "expected" / "legacy_domain_result.json"


def aerotuner_root() -> Path:
    """Resolve donor AeroTuner checkout used as the legacy oracle."""
    env = os.environ.get("AEROTUNER_ROOT", "").strip()
    if env:
        root = Path(env).expanduser().resolve()
    else:
        # Sibling checkout next to GyroCore (common local layout).
        root = (repo_root().parent / "aerotuner").resolve()
    if not (root / "backend").is_dir():
        raise FileNotFoundError(
            "AeroTuner donor not found. Set AEROTUNER_ROOT to the checkout path "
            f"(tried {root})."
        )
    return root


def list_live_oracle_fixtures() -> list[str]:
    """Fixtures that can execute the live legacy analyze path (CSV/BBL inputs)."""
    names: list[str] = []
    if not _FIXTURES_ROOT.is_dir():
        return names
    for child in sorted(_FIXTURES_ROOT.iterdir()):
        if not child.is_dir():
            continue
        meta_path = child / "input" / "metadata.json"
        if not meta_path.is_file():
            continue
        import json

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("oracle_mode") == "live_legacy":
            names.append(child.name)
    return names
