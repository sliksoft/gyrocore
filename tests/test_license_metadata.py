"""Published package metadata must declare the project license from the root LICENSE.

The root ``LICENSE`` is the unmodified GNU GPL v3 text with no "or any later version"
grant for GyroCore, and ``docs/upstream/PROVENANCE_MANIFEST.md`` states
"GyroCore license: GPL-3.0" — i.e. SPDX ``GPL-3.0-only``.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_SPDX = "GPL-3.0-only"


def test_root_license_is_gpl3_text() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in text
    assert "Version 3, 29 June 2007" in text


def test_provenance_manifest_declares_gpl3() -> None:
    manifest = (ROOT / "docs/upstream/PROVENANCE_MANIFEST.md").read_text(encoding="utf-8")
    assert re.search(r"GyroCore license: \*\*GPL-3\.0\*\*", manifest)


def test_pyproject_license_matches() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["license"] == {"text": PROJECT_SPDX}


def test_npm_packages_license_matches() -> None:
    for rel in ("apps/desktop/gyrocore-app/package.json", "apps/desktop/blackbox-host/package.json"):
        assert json.loads((ROOT / rel).read_text(encoding="utf-8")).get("license") == PROJECT_SPDX, rel
    lock = json.loads((ROOT / "apps/desktop/gyrocore-app/package-lock.json").read_text(encoding="utf-8"))
    assert lock["packages"][""].get("license") == PROJECT_SPDX


def test_tauri_crate_license_matches() -> None:
    data = tomllib.loads((ROOT / "apps/desktop/gyrocore-app/src-tauri/Cargo.toml").read_text(encoding="utf-8"))
    assert data["package"]["license"] == PROJECT_SPDX


def test_no_permissive_license_claim_in_metadata() -> None:
    for rel in (
        "pyproject.toml",
        "apps/desktop/gyrocore-app/package.json",
        "apps/desktop/blackbox-host/package.json",
        "apps/desktop/gyrocore-app/src-tauri/Cargo.toml",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert not re.search(r'licen[cs]e[^\n]*\b(MIT|Apache|BSD)\b', text, re.I), rel
