"""Python reference goldens for the browser CHIRP port (CHIRP_BROWSER_WU1).

Runs the *unchanged* Python reference (``gyrocore.chirp``) and writes, under
``tests/fixtures/chirp/browser/``:

- ``bbl_golden.json.gz``  ``identify_chirp_system_from_bbl(...).to_dict(include_arrays=True)``
                         for every WU7 ``.bbl.gz`` fixture (decoded by ``blackbox_decode``,
                         every valid main frame). The browser decodes the same bytes with
                         FlightLog and must reproduce these results.
- ``frame_cases.json.gz`` deterministic frame tables (raw logged integers) for edge cases
                         without a BBL fixture, plus ``identify_chirp_system(frames=...)``
                         output for each.

Non-finite floats are written as ``null``; files are gzip'd with mtime 0 (deterministic). Regenerate with::

    PYTHONPATH=.:core python3 tools/chirp_reference/make_browser_golden.py

``tests/core/chirp/test_browser_golden_fresh.py`` fails when these files are stale.

Local / private logs (never committed, never required by CI)::

    PYTHONPATH=.:core python3 tools/chirp_reference/make_browser_golden.py \
        --local LOG.BBL --log-index N --out /tmp/local_golden.json.gz
    GYROCORE_CHIRP_LOCAL_GOLDEN=/tmp/local_golden.json.gz GYROCORE_CHIRP_LOCAL_BBL=LOG.BBL \
        npx vitest run src/chirp/parity.local.test.ts
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))

from gyrocore.chirp import ChirpFrames, identify_chirp_system, identify_chirp_system_from_bbl  # noqa: E402

WU7 = ROOT / "tests" / "fixtures" / "chirp" / "wu7"
OUT_DIR = ROOT / "tests" / "fixtures" / "chirp" / "browser"

BOXCHIRP_FLAG = 1 << 6
FS_HZ = 1000.0
DT_US = 1000

BASE_HEADERS = {
    "Data version": "2",
    "I interval": "32",
    "P interval": "1/1",
    "Firmware revision": "Betaflight 2026.6.0 (synthetic) STM32F7X2",
    "looptime": "250",
    "pid_process_denom": "4",
    "debug_mode": "96",
    "blackbox_high_resolution": "0",
    "chirp_frequency_start_deci_hz": "20",
    "chirp_frequency_end_deci_hz": "2000",
    "chirp_time_seconds": "2",
}


def sanitize(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if isinstance(value, np.generic):
        return sanitize(value.item())
    return value


def bbl_goldens() -> dict[str, Any]:
    cases = json.loads((WU7 / "cases.json").read_text())["cases"]
    out: dict[str, Any] = {}
    with tempfile.TemporaryDirectory(prefix="gyrocore-chirp-golden-") as tmp:
        for case in cases:
            raw = gzip.decompress((WU7 / case["bbl"]).read_bytes())
            path = Path(tmp) / f"{case['case_id']}.bbl"
            path.write_bytes(raw)
            result = identify_chirp_system_from_bbl(path)
            out[case["case_id"]] = {
                "bbl": case["bbl"],
                "bbl_sha256": hashlib.sha256(raw).hexdigest(),
                "result": sanitize(result.to_dict(include_arrays=True)),
            }
    return out


# ---------------------------------------------------------------------------
# Frame-level edge cases
# ---------------------------------------------------------------------------


def _chirp(n: int, amplitude: float, f0: float = 2.0, f1: float = 200.0) -> np.ndarray:
    t = np.arange(n) / FS_HZ
    dur = n / FS_HZ
    phase = 2 * np.pi * (f0 * t + 0.5 * (f1 - f0) / dur * t * t)
    return amplitude * np.sin(phase)


class _Builder:
    def __init__(self, seed: int) -> None:
        self.rng = np.random.RandomState(seed)
        self.cols: dict[str, list[float]] = {k: [] for k in ("time", "sp0", "sp1", "sp2", "g0", "g1", "g2", "d0", "d1", "d2", "d3", "flags")}
        self.t = 1_000_000

    def idle(self, n: int, *, flags: int = 0) -> None:
        for _ in range(n):
            self._row([0.0, 0.0, 0.0], [0.0, 0.0, 0.0], -1, flags)

    def chirp(self, axis: int, n: int, *, amplitude: float = 200.0, gain: float = 1.0, noise: float = 0.0,
              debug_axis: int | None = None, flags: int = BOXCHIRP_FLAG) -> None:
        x = _chirp(n, amplitude)
        y = gain * x + (self.rng.standard_normal(n) * noise if noise else 0.0)
        for i in range(n):
            sp = [0.0, 0.0, 0.0]
            gy = [0.0, 0.0, 0.0]
            sp[axis] = float(np.rint(x[i]))
            gy[axis] = float(np.rint(y[i]))
            self._row(sp, gy, axis if debug_axis is None else debug_axis, flags)

    def _row(self, sp: list[float], gy: list[float], debug_axis: int, flags: int) -> None:
        c = self.cols
        c["time"].append(float(self.t))
        for a in range(3):
            c[f"sp{a}"].append(sp[a])
            c[f"g{a}"].append(gy[a])
        c["d0"].append(0.0)
        c["d1"].append(float(debug_axis))
        c["d2"].append(0.0)
        c["d3"].append(0.0)
        c["flags"].append(float(flags))
        self.t += DT_US

    def skip_time(self, samples: int) -> None:
        self.t += DT_US * samples


def _frames(cols: dict[str, list[float]], *, with_flags: bool = True) -> ChirpFrames:
    def arr(k: str) -> np.ndarray:
        return np.asarray(cols[k], dtype=np.float64)

    n = len(cols["time"])
    return ChirpFrames(
        loop_iteration=np.arange(n, dtype=np.float64),
        time_us=arr("time"),
        setpoint=np.vstack([arr("sp0"), arr("sp1"), arr("sp2")]),
        gyro_adc=np.vstack([arr("g0"), arr("g1"), arr("g2")]),
        debug=np.vstack([arr("d0"), arr("d1"), arr("d2"), arr("d3")]),
        flight_mode_flags=arr("flags").astype(np.int64) if with_flags else None,
        source="frame_case",
        gyro_columns=("gyroADC[0]", "gyroADC[1]", "gyroADC[2]"),
        warnings=() if with_flags else ("flight_mode_flags_column_missing",),
    )


def _frame_cases() -> list[dict[str, Any]]:
    specs: list[tuple[str, str, Any, dict[str, str], bool]] = []

    def case(case_id: str, description: str, build, headers: dict[str, str] | None = None, with_flags: bool = True) -> None:
        specs.append((case_id, description, build, {**BASE_HEADERS, **(headers or {})}, with_flags))

    def valid_roll(b: _Builder) -> None:
        b.idle(200); b.chirp(0, 2048); b.idle(200)

    def each_axis(b: _Builder) -> None:
        b.idle(100)
        for axis in range(3):
            b.chirp(axis, 2048, gain=[1.0, 0.8, 0.6][axis])
        b.idle(100)

    def repeated(b: _Builder) -> None:
        b.idle(100); b.chirp(0, 2048, gain=1.0); b.idle(100); b.chirp(0, 2048, gain=0.5); b.idle(100)

    def flags_never(b: _Builder) -> None:
        b.idle(200); b.chirp(0, 2048, flags=0); b.idle(200)

    def axis_minus1(b: _Builder) -> None:
        b.idle(200, flags=BOXCHIRP_FLAG); b.chirp(0, 2048, debug_axis=-1); b.idle(200)

    def too_short(b: _Builder) -> None:
        b.idle(200); b.chirp(0, 300); b.idle(200)

    def low_excitation(b: _Builder) -> None:
        b.idle(200); b.chirp(0, 2048, amplitude=3.0); b.idle(200)

    def low_coherence(b: _Builder) -> None:
        b.idle(200); b.chirp(0, 2048, noise=2000.0); b.idle(200)

    def gap(b: _Builder) -> None:
        b.idle(200); b.chirp(0, 1024); b.skip_time(100); b.chirp(0, 1024); b.idle(200)

    def reset(b: _Builder) -> None:
        b.idle(200); b.chirp(0, 1024); b.t -= 600 * DT_US; b.chirp(0, 1024); b.idle(200)

    def nan_times(b: _Builder) -> None:
        b.idle(200); b.chirp(0, 2048); b.idle(200)
        for i in range(500, 2300, 97):
            b.cols["time"][i] = float("nan")

    case("valid_roll", "Valid roll chirp, unity plant, 1 kHz.", valid_roll)
    case("each_axis", "Roll, pitch, yaw chirps in sequence (gains 1.0/0.8/0.6).", each_axis)
    case("repeated_axis", "Two roll segments; the later (gain 0.5) is selected.", repeated)
    case("no_chirp_flag_never_set", "Excitation present but BOXCHIRP never set.", flags_never)
    case("no_chirp_axis_minus1", "BOXCHIRP set but debug[1] = -1 throughout (no axis).", axis_minus1)
    case("too_short", "300-sample chirp; shorter than the Welch segment.", too_short)
    case("low_excitation", "3 deg/s amplitude chirp.", low_excitation)
    case("low_coherence", "Output dominated by noise.", low_coherence)
    case("timestamp_gap", "100-sample timestamp gap inside the segment.", gap)
    case("timestamp_reset", "Timestamp jumps backwards inside the segment.", reset)
    case("malformed_timestamps", "NaN timestamps inside the segment.", nan_times)
    case("no_flags_column", "flightModeFlags column absent (debug-axis gating).", valid_roll, with_flags=False)
    case("wrong_debug_mode", "debug_mode is not CHIRP.", valid_roll, headers={"debug_mode": "6"})
    case("missing_rate_headers", "No looptime / P interval headers (timestamp rate).", valid_roll,
         headers={"looptime": "", "pid_process_denom": "", "P interval": ""})

    out = []
    for i, (case_id, description, build, headers, with_flags) in enumerate(specs):
        b = _Builder(seed=100 + i)
        build(b)
        headers = {k: v for k, v in headers.items() if v != ""}
        header_text = "\n".join(f"H {k}:{v}" for k, v in headers.items())
        frames = _frames(b.cols, with_flags=with_flags)
        result = identify_chirp_system(frames=frames, headers=header_text)
        cols = {k: v for k, v in b.cols.items() if with_flags or k != "flags"}
        out.append({
            "case_id": case_id,
            "description": description,
            "headers": [[k, v] for k, v in headers.items()],
            "columns": sanitize(cols),
            "result": sanitize(result.to_dict(include_arrays=True)),
        })
    return out


def serialize(payload: Any) -> bytes:
    """Deterministic gzip (mtime 0) of compact sorted JSON."""
    text = json.dumps(payload, allow_nan=False, separators=(",", ":"), sort_keys=True) + "\n"
    return gzip.compress(text.encode("utf-8"), compresslevel=9, mtime=0)


def build() -> dict[str, Any]:
    return {
        "bbl_golden.json": {
            "generator": "tools/chirp_reference/make_browser_golden.py",
            "reference": "gyrocore.chirp.identify_chirp_system_from_bbl",
            "numpy": np.__version__,
            "cases": bbl_goldens(),
        },
        "frame_cases.json": {
            "generator": "tools/chirp_reference/make_browser_golden.py",
            "reference": "gyrocore.chirp.identify_chirp_system",
            "numpy": np.__version__,
            "cases": _frame_cases(),
        },
    }


def local_golden(bbl: Path, log_index: int) -> dict[str, Any]:
    raw = bbl.read_bytes()
    result = identify_chirp_system_from_bbl(bbl, log_index=log_index)
    return {
        "bbl_sha256": hashlib.sha256(raw).hexdigest(),
        "log_index": log_index,
        "numpy": np.__version__,
        "result": sanitize(result.to_dict(include_arrays=True)),
    }


def main() -> None:
    if "--local" in sys.argv:
        args = sys.argv[1:]
        bbl = Path(args[args.index("--local") + 1])
        log_index = int(args[args.index("--log-index") + 1])
        out = Path(args[args.index("--out") + 1])
        out.write_bytes(serialize(local_golden(bbl, log_index)))
        print(f"wrote {out}")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, payload in build().items():
        (OUT_DIR / f"{name}.gz").write_bytes(serialize(payload))
        print(f"wrote {OUT_DIR / name}.gz")


if __name__ == "__main__":
    main()
