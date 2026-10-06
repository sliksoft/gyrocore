#!/usr/bin/env python3
"""Explicitly regenerate frozen legacy DOMAIN golden files.

Normal pytest runs NEVER call this. Developers must run it consciously:

    AEROTUNER_ROOT=/home/sliksoft/aerotuner \\
      /home/sliksoft/aerotuner/.venv/bin/python tools/update_legacy_golden.py

    # or a single fixture:
    ... python tools/update_legacy_golden.py gl001_clean
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.golden.legacy_oracle import run_fixture_oracle, write_expected_golden  # noqa: E402
from tests.golden.paths import fixture_expected_path, fixtures_root  # noqa: E402


def _list_fixtures() -> list[str]:
    root = fixtures_root()
    names: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / "input" / "metadata.json").is_file():
            names.append(child.name)
    return names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "fixtures",
        nargs="*",
        help="Fixture ids to update (default: all fixtures with metadata.json)",
    )
    args = parser.parse_args(argv)
    selected = args.fixtures or _list_fixtures()
    if not selected:
        print("No fixtures found.", file=sys.stderr)
        return 2

    changed: list[str] = []
    unchanged: list[str] = []
    for name in selected:
        print(f"[update] running oracle for fixture={name}")
        projection = run_fixture_oracle(name)
        out_path = fixture_expected_path(name)
        new_text = json.dumps(projection, indent=2, sort_keys=True, default=str) + "\n"
        old_text = out_path.read_text(encoding="utf-8") if out_path.is_file() else None
        write_expected_golden(name, projection)
        if old_text != new_text:
            print(f"[update] CHANGED {out_path}")
            changed.append(name)
        else:
            print(f"[update] unchanged {out_path}")
            unchanged.append(name)

    print("---")
    print(f"Changed ({len(changed)}): {', '.join(changed) if changed else '(none)'}")
    print(f"Unchanged ({len(unchanged)}): {', '.join(unchanged) if unchanged else '(none)'}")
    print("Golden regeneration complete. Review diffs before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
