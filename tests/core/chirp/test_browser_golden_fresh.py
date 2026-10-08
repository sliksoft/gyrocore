"""The browser CHIRP parity goldens must match the current Python reference.

``apps/desktop/gyrocore-app/src/chirp/parity.golden.test.ts`` compares the
browser port against ``tests/fixtures/chirp/browser/*.json.gz``. Regenerating
those files from the reference must reproduce them, so a Python CHIRP change can
never silently leave the browser gate stale.

numpy is not pinned exactly (``numpy>=1.24``), so the comparison is semantic
rather than byte-for-byte: structure, strings, booleans and integers exact;
floats within rel 1e-7 / abs 1e-9 (last-ULP FFT differences between numpy
builds are not staleness). The ``numpy`` provenance field is ignored.
"""

from __future__ import annotations

import gzip
import importlib.util
import json
import math
import shutil
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
GENERATOR = ROOT / "tools" / "chirp_reference" / "make_browser_golden.py"
OUT_DIR = ROOT / "tests" / "fixtures" / "chirp" / "browser"
FLOAT_REL = 1e-7
FLOAT_ABS = 1e-9

pytestmark = pytest.mark.skipif(shutil.which("blackbox_decode") is None, reason="blackbox_decode not on PATH")


def _generator():
    spec = importlib.util.spec_from_file_location("make_browser_golden", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _diff(path: str, ref: Any, got: Any) -> str | None:
    if isinstance(ref, float) or isinstance(got, float):
        if isinstance(ref, (int, float)) and isinstance(got, (int, float)) and not isinstance(ref, bool) and not isinstance(got, bool):
            if math.isclose(ref, got, rel_tol=FLOAT_REL, abs_tol=FLOAT_ABS):
                return None
        return f"{path}: {ref!r} != {got!r}"
    if isinstance(ref, dict) and isinstance(got, dict):
        if set(ref) != set(got):
            return f"{path}: keys {sorted(set(ref) ^ set(got))}"
        for k in ref:
            if k == "numpy":
                continue
            d = _diff(f"{path}.{k}", ref[k], got[k])
            if d:
                return d
        return None
    if isinstance(ref, list) and isinstance(got, list):
        if len(ref) != len(got):
            return f"{path}: length {len(ref)} != {len(got)}"
        for i, (a, b) in enumerate(zip(ref, got)):
            d = _diff(f"{path}[{i}]", a, b)
            if d:
                return d
        return None
    return None if ref == got and type(ref) is type(got) else f"{path}: {ref!r} != {got!r}"


def test_browser_chirp_goldens_are_fresh():
    gen = _generator()
    for name, payload in gen.build().items():
        committed = json.loads(gzip.decompress((OUT_DIR / f"{name}.gz").read_bytes()))
        fresh = json.loads(gzip.decompress(gen.serialize(payload)))
        diff = _diff(name, committed, fresh)
        assert diff is None, f"{diff} — {name}.gz is stale; rerun {GENERATOR.relative_to(ROOT)}"


def test_freshness_check_detects_a_changed_value():
    assert _diff("x", {"a": [1.0, 2.0]}, {"a": [1.0, 2.0 * (1 + 1e-10)]}) is None
    assert _diff("x", {"a": [1.0, 2.0]}, {"a": [1.0, 2.001]}) is not None
    assert _diff("x", {"s": "ok"}, {"s": "unusable"}) is not None
    assert _diff("x", {"b": True}, {"b": False}) is not None
    assert _diff("x", {"numpy": "1.26.4"}, {"numpy": "2.1.0"}) is None
