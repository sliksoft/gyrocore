#!/usr/bin/env python3
"""Build the C simplified-tuning reference harness (Betaflight 2026.6.2)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REF = ROOT / "tools" / "simplified_tuning_reference"
CC = "gcc"
CFLAGS = [
    "-std=c11",
    "-O0",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-DUSE_SIMPLIFIED_TUNING",
    "-DUSE_D_MAX",
    "-DUSE_DYN_LPF",
    "-I",
    str(REF / "include"),
]


def binary_path() -> Path:
    return REF / "harness"


def build(out: Path | None = None) -> Path:
    dest = out or binary_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        CC,
        *CFLAGS,
        "-o",
        str(dest),
        str(REF / "harness.c"),
        str(ROOT / "third_party/betaflight/firmware/src/main/config/simplified_tuning.c"),
    ]
    subprocess.check_call(cmd)
    return dest


def run_batch(lines: list[str], binary: Path | None = None) -> list[str]:
    """Send harness commands; return stdout lines (stripped)."""
    exe = binary or build()
    payload = "\n".join(lines) + "\n"
    proc = subprocess.run([str(exe)], input=payload, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"harness failed ({proc.returncode}): {proc.stderr}")
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


if __name__ == "__main__":
    path = build()
    print(path)
    sys.exit(0)
