"""Minimal Betaflight Blackbox (.BBL) *writer* for CHIRP parity fixtures.

Encodes synthetic logs that both the vendored Betaflight ``parseChirpLog``
(TypeScript) and the vendored ``blackbox_decode`` (C) can read, so the same
bytes drive the upstream reference and the GyroCore pipeline.

Only the subset of the format needed for CHIRP fixtures is emitted:

- main frames are always I-frames (predictor 0; signed/unsigned VB)
- S-frames carry ``flightModeFlags`` / ``stateFlags`` / ``failsafePhase``
- a trailing ``E`` LOG_END event

This module never decodes Blackbox data; decoding stays with
``blackbox_decode`` + ``gyrocore.parse``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence

LOG_START = "H Product:Blackbox flight data recorder by Nicholas Sherlock\n"

PREDICTOR_0 = 0
ENCODING_SIGNED_VB = 0
ENCODING_UNSIGNED_VB = 1

EVENT_LOG_END = 255


def _unsigned_vb(value: int) -> bytes:
    if value < 0:
        raise ValueError("unsigned VB requires value >= 0")
    value &= 0xFFFFFFFF
    out = bytearray()
    while value > 127:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _signed_vb(value: int) -> bytes:
    zigzag = ((value << 1) ^ (value >> 31)) & 0xFFFFFFFF
    return _unsigned_vb(zigzag)


@dataclass(frozen=True)
class FieldSpec:
    name: str
    signed: bool


def chirp_main_fields(*, include_debug3: bool = True) -> list[FieldSpec]:
    fields = [FieldSpec("loopIteration", False), FieldSpec("time", False)]
    fields += [FieldSpec(f"setpoint[{i}]", True) for i in range(4)]
    fields += [FieldSpec(f"gyroADC[{i}]", True) for i in range(3)]
    debug_count = 4 if include_debug3 else 3
    fields += [FieldSpec(f"debug[{i}]", True) for i in range(debug_count)]
    fields += [FieldSpec(f"motor[{i}]", False) for i in range(4)]
    return fields


SLOW_FIELDS = [
    FieldSpec("flightModeFlags", False),
    FieldSpec("stateFlags", False),
    FieldSpec("failsafePhase", False),
]


@dataclass
class BblLog:
    """Builder for one flight log (header + frames)."""

    headers: list[tuple[str, str]]
    main_fields: list[FieldSpec]
    slow_fields: list[FieldSpec] = field(default_factory=lambda: list(SLOW_FIELDS))
    _body: bytearray = field(default_factory=bytearray)

    def header_bytes(self) -> bytes:
        lines = [LOG_START]
        for key, value in self.headers:
            lines.append(f"H {key}:{value}\n")
        main = self.main_fields
        lines.append("H Field I name:" + ",".join(f.name for f in main) + "\n")
        lines.append("H Field I signed:" + ",".join("1" if f.signed else "0" for f in main) + "\n")
        lines.append("H Field I predictor:" + ",".join(str(PREDICTOR_0) for _ in main) + "\n")
        lines.append(
            "H Field I encoding:"
            + ",".join(str(ENCODING_SIGNED_VB if f.signed else ENCODING_UNSIGNED_VB) for f in main)
            + "\n"
        )
        lines.append("H Field P predictor:" + ",".join("1" for _ in main) + "\n")
        lines.append("H Field P encoding:" + ",".join(str(ENCODING_SIGNED_VB) for _ in main) + "\n")
        slow = self.slow_fields
        lines.append("H Field S name:" + ",".join(f.name for f in slow) + "\n")
        lines.append("H Field S signed:" + ",".join("1" if f.signed else "0" for f in slow) + "\n")
        lines.append("H Field S predictor:" + ",".join(str(PREDICTOR_0) for _ in slow) + "\n")
        lines.append(
            "H Field S encoding:"
            + ",".join(str(ENCODING_SIGNED_VB if f.signed else ENCODING_UNSIGNED_VB) for f in slow)
            + "\n"
        )
        return "".join(lines).encode("ascii")

    def _encode(self, specs: Sequence[FieldSpec], values: Sequence[int]) -> bytes:
        if len(values) != len(specs):
            raise ValueError(f"expected {len(specs)} values, got {len(values)}")
        out = bytearray()
        for spec, value in zip(specs, values):
            v = int(value)
            out += _signed_vb(v) if spec.signed else _unsigned_vb(v)
        return bytes(out)

    def add_i_frame(self, values: Sequence[int]) -> None:
        self._body += b"I" + self._encode(self.main_fields, values)

    def add_s_frame(self, flight_mode_flags: int, state_flags: int = 0, failsafe_phase: int = 0) -> None:
        self._body += b"S" + self._encode(
            self.slow_fields, [flight_mode_flags, state_flags, failsafe_phase]
        )

    def add_log_end(self) -> None:
        self._body += b"E" + bytes([EVENT_LOG_END]) + b"End of log\x00"

    def to_bytes(self) -> bytes:
        return self.header_bytes() + bytes(self._body)


def concat_logs(logs: Iterable[BblLog]) -> bytes:
    return b"".join(log.to_bytes() for log in logs)
