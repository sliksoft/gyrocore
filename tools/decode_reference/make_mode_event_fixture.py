"""Generate ``tests/fixtures/decode/mode_events.bbl.gz``.

A synthetic single log with I/P frames (I interval 32) and Betaflight events whose
payloads used to desynchronise unpatched ``blackbox_decode`` (see
``docs/upstream/PATCHES.md``). Expected decode is the full frame set: every decoder
must return ``FRAME_COUNT`` main frames.

Run from the repo root::

    python3 tools/decode_reference/make_mode_event_fixture.py
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "chirp_reference"))

from bbl_writer import BblLog, FieldSpec, _unsigned_vb, chirp_main_fields  # noqa: E402

I_INTERVAL = 32
FRAME_COUNT = 640
LOOPTIME_US = 250
T0_US = 10_000_000

EVENT_DISARM = 15
EVENT_FLIGHT_MODE = 30

# iteration -> (event type, payload values); the event is written just before that frame.
EVENTS: dict[int, tuple[int, tuple[int, ...]]] = {
    100: (EVENT_FLIGHT_MODE, (5, 69)),  # lead 0x05: not a frame marker
    200: (EVENT_FLIGHT_MODE, (69, 5)),  # lead 0x45 'E': harmless even unpatched
    300: (EVENT_DISARM, (4,)),  # lead 0x04
    410: (EVENT_FLIGHT_MODE, (68, 69)),  # lead 0x44 'D' (real disarm transition)
    600: (EVENT_FLIGHT_MODE, (0x1234, 0)),  # multi-byte VB, lead 0xb4
}


class EventBblLog(BblLog):
    """BblLog plus P-frames (predictor PREVIOUS, signed VB deltas) and events."""

    def add_p_frame(self, values: list[int], previous: list[int]) -> None:
        deltas = [int(v) - int(p) for v, p in zip(values, previous)]
        self._body += b"P" + self._encode([FieldSpec(f.name, True) for f in self.main_fields], deltas)

    def add_event(self, event_type: int, payload: tuple[int, ...]) -> None:
        self._body += b"E" + bytes([event_type]) + b"".join(_unsigned_vb(v) for v in payload)


def unpatched_native_drops() -> int:
    """Frames an unpatched decoder drops: from each non-marker event to the next I-frame."""
    drops = 0
    for it, (_, payload) in EVENTS.items():
        lead = payload[0] if payload[0] <= 0x7F else (payload[0] & 0x7F) | 0x80
        if chr(lead) in "IPESGH" or it % I_INTERVAL == 0:
            continue
        drops += I_INTERVAL - it % I_INTERVAL
    return drops


def build() -> bytes:
    headers = [
        ("Data version", "2"),
        ("I interval", str(I_INTERVAL)),
        ("P interval", "1/1"),
        ("Firmware type", "Cleanflight"),
        ("Firmware revision", "Betaflight 2026.6.0 (synthetic) STM32F7X2"),
        ("Board information", "SYNT SYNTHETIC"),
        ("looptime", str(LOOPTIME_US)),
        ("pid_process_denom", "1"),
        ("debug_mode", "0"),
    ]
    log = EventBblLog(headers, chirp_main_fields())
    log.add_s_frame(0)
    previous: list[int] | None = None
    for it in range(FRAME_COUNT):
        if it in EVENTS:
            log.add_event(*EVENTS[it])
        sp = [(it * 7) % 61 - 30, (it * 11) % 41 - 20, (it * 3) % 21 - 10, 1300 + it % 50]
        gy = [(it * 5) % 53 - 26, (it * 13) % 37 - 18, (it * 17) % 29 - 14]
        dbg = [it % 17, it % 3, 0, (it * 19) % 101]
        mot = [1100 + (it * k) % 300 for k in (1, 2, 3, 4)]
        values = [it, T0_US + it * LOOPTIME_US, *sp, *gy, *dbg, *mot]
        if it % I_INTERVAL == 0 or previous is None:
            log.add_i_frame(values)
        else:
            log.add_p_frame(values, previous)
        previous = values
    log.add_event(EVENT_DISARM, (4,))
    log.add_log_end()
    return log.to_bytes()


def main() -> None:
    out = ROOT / "tests" / "fixtures" / "decode"
    out.mkdir(parents=True, exist_ok=True)
    data = build()
    (out / "mode_events.bbl.gz").write_bytes(gzip.compress(data, mtime=0))
    meta = {
        "frame_count": FRAME_COUNT,
        "i_interval": I_INTERVAL,
        "events": {str(k): {"type": t, "payload": list(p)} for k, (t, p) in EVENTS.items()},
        "unpatched_native_frame_count": FRAME_COUNT - unpatched_native_drops(),
    }
    (out / "mode_events.json").write_text(json.dumps(meta, indent=2) + "\n")


if __name__ == "__main__":
    main()
