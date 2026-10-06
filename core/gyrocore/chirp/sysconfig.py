"""CHIRP log header (sysConfig) parsing — mirror of upstream ``parseHeader``.

Upstream: ``third_party/betaflight/configurator/src/js/blackbox/chirp_bbl_parser.ts``
``findLogBoundaries`` / ``parseHeader`` / ``parseHeaderLine`` / ``parseIntHeader`` /
``parsePIntervalHeader`` / ``parsePRatioHeader``.

Only the ASCII ``H key:value`` header block is read here; binary frames are
decoded by ``blackbox_decode`` (``gyrocore.decode``), never by this module.

Accepted header sources:

- raw BBL bytes (``read_bbl_header_text``; log boundaries as upstream)
- ``H key:value`` text
- ``blackbox_decode --save-headers`` Field/Value CSV
- a mapping (normalized keys, or upstream sysConfig names such as ``frameIntervalPDenom``)

Values keep upstream ``Number.parseInt`` semantics, but GyroCore records which
keys were actually present so callers never confuse an upstream default
(``looptime`` 125, ``pid_process_denom`` 1) with a logged value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping

from gyrocore.parse.firmware_metadata import _normalize_field_key, _parse_headers_flat

LOG_START_MARKER = b"H Product:Blackbox flight data recorder by Nicholas Sherlock"

UPSTREAM_DEFAULTS: dict[str, int] = {
    "data_version": 2,
    "looptime": 125,
    "pid_process_denom": 1,
    "debug_mode": -1,
    "blackbox_high_resolution": 0,
    "i_interval": 32,
    "p_interval_num": 1,
    "p_interval_denom": 1,
}

_INT_KEYS = (
    "data_version",
    "looptime",
    "pid_process_denom",
    "debug_mode",
    "blackbox_high_resolution",
    "i_interval",
    "chirp_lag_freq_hz",
    "chirp_lead_freq_hz",
    "chirp_amplitude_roll",
    "chirp_amplitude_pitch",
    "chirp_amplitude_yaw",
    "chirp_frequency_start_deci_hz",
    "chirp_frequency_end_deci_hz",
    "chirp_time_seconds",
)

# Upstream sysConfig attribute names -> normalized header keys.
_SYSCONFIG_ALIASES = {
    "dataversion": "data_version",
    "frameintervali": "i_interval",
    "frameintervalpnum": "p_interval_num",
    "frameintervalpdenom": "p_interval_denom",
    "firmwareapiversion": "firmware_api_version",
    "firmwarerevision": "firmware_revision",
}

_JS_INT = re.compile(r"^\s*([+-]?\d+)")


def js_parse_int(value: Any) -> int | None:
    """``Number.parseInt(value, 10)``; ``None`` where JS yields ``NaN``."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value == value and abs(value) != float("inf") else None
    m = _JS_INT.match(str(value))
    return int(m.group(1)) if m else None


@dataclass(frozen=True)
class ChirpSysConfig:
    """Header values relevant to CHIRP analysis (``None`` = absent / NaN)."""

    data_version: int | None = None
    looptime: int | None = None
    pid_process_denom: int | None = None
    debug_mode: int | None = None
    blackbox_high_resolution: int | None = None
    i_interval: int | None = None
    p_interval_num: int | None = None
    p_interval_denom: int | None = None
    p_interval_seen: bool = False
    chirp_lag_freq_hz: int | None = None
    chirp_lead_freq_hz: int | None = None
    chirp_amplitude_roll: int | None = None
    chirp_amplitude_pitch: int | None = None
    chirp_amplitude_yaw: int | None = None
    chirp_frequency_start_deci_hz: int | None = None
    chirp_frequency_end_deci_hz: int | None = None
    chirp_time_seconds: int | None = None
    firmware_revision: str | None = None
    firmware_api_version: str | None = None
    field_i_names: tuple[str, ...] = ()
    present_keys: frozenset[str] = field(default_factory=frozenset)

    def upstream_value(self, key: str) -> int:
        """Value as upstream ``sysConfig`` would hold it (defaults applied, NaN -> 0)."""
        value = getattr(self, key)
        if value is None:
            return 0 if key in self.present_keys else UPSTREAM_DEFAULTS.get(key, 0)
        return int(value)

    @property
    def high_resolution_scale(self) -> float:
        """``hiResScale`` from ``parseChirpLog``: 0.1 when ``blackbox_high_resolution`` is truthy."""
        return 0.1 if self.upstream_value("blackbox_high_resolution") else 1.0

    def chirp_frequency_range_hz(self) -> tuple[float, float] | None:
        start = self.chirp_frequency_start_deci_hz
        end = self.chirp_frequency_end_deci_hz
        if start is None or end is None or start <= 0 or end <= start:
            return None
        return start / 10.0, end / 10.0

    def sample_rate_inputs(self) -> dict[str, int | None]:
        """Keys for ``resolve_chirp_sample_rate`` (absent values stay ``None``)."""
        return {
            "looptime_us": self.looptime if self.looptime and self.looptime > 0 else None,
            "pid_process_denom": (
                self.pid_process_denom if self.pid_process_denom and self.pid_process_denom > 0 else None
            ),
            "frame_interval_p_num": self.p_interval_num if self.p_interval_seen else None,
            "frame_interval_p_denom": self.p_interval_denom if self.p_interval_seen else None,
        }

    def to_dict(self) -> dict[str, Any]:
        out = {k: getattr(self, k) for k in self.__dataclass_fields__ if k not in ("present_keys", "field_i_names")}
        out["present_keys"] = sorted(self.present_keys)
        out["field_i_names"] = list(self.field_i_names)
        return out


def find_log_boundaries(data: bytes) -> list[tuple[int, int]]:
    """Byte ranges of each log in a BBL file (upstream ``findLogBoundaries``)."""
    out: list[tuple[int, int]] = []
    offset = 0
    while offset < len(data):
        start = data.find(LOG_START_MARKER, offset)
        if start < 0:
            break
        nxt = data.find(LOG_START_MARKER, start + len(LOG_START_MARKER))
        end = len(data) if nxt < 0 else nxt
        out.append((start, end))
        offset = end
    return out


def read_bbl_header_text(data: bytes, log_index: int = 0) -> str:
    """ASCII ``H`` header block of one log (``log_index`` is 0-based)."""
    bounds = find_log_boundaries(data)
    if not bounds:
        raise ValueError("no_blackbox_log_found")
    if log_index < 0 or log_index >= len(bounds):
        raise ValueError(f"log_index_out_of_range: {log_index} (logs={len(bounds)})")
    start, end = bounds[log_index]
    lines: list[str] = []
    pos = start
    while pos < end and data[pos : pos + 2] == b"H ":
        nl = data.find(b"\n", pos, end)
        stop = end if nl < 0 else nl
        lines.append(data[pos:stop].decode("latin-1"))
        pos = stop + 1
    return "\n".join(lines)


def _h_lines(text: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for raw in text.splitlines():
        if not raw.startswith("H "):
            continue
        line = raw[2:]
        colon = line.find(":")
        if colon < 0:
            continue
        pairs.append((line[:colon], line[colon + 1 :]))
    return pairs


def _pairs_from_mapping(mapping: Mapping[str, Any]) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    for key, value in mapping.items():
        norm = _normalize_field_key(str(key))
        compact = norm.replace("_", "")
        pairs.append((_SYSCONFIG_ALIASES.get(compact, norm), value))
    return pairs


def parse_chirp_sysconfig(source: bytes | str | Mapping[str, Any], *, log_index: int = 0) -> ChirpSysConfig:
    """Build :class:`ChirpSysConfig` from a BBL, header text, Field/Value CSV or mapping."""
    if isinstance(source, (bytes, bytearray)):
        source = read_bbl_header_text(bytes(source), log_index)
    pairs: list[tuple[str, Any]]
    if isinstance(source, Mapping):
        pairs = _pairs_from_mapping(source)
    elif any(line.startswith("H ") for line in source.splitlines()[:5]):
        pairs = [(_normalize_field_key(k), v) for k, v in _h_lines(source)]
    else:
        pairs = list(_parse_headers_flat(source).items())

    values: dict[str, Any] = {}
    present: set[str] = set()
    p_interval_seen = False
    p_ratio: int | None = None
    for key, raw in pairs:
        if key in _INT_KEYS:
            values[key] = js_parse_int(raw)
            present.add(key)
        elif key == "p_interval":
            p_interval_seen = True
            present.add(key)
            text = str(raw)
            if "/" in text:
                num, den = text.split("/", 1)
                values["p_interval_num"] = js_parse_int(num)
                values["p_interval_denom"] = js_parse_int(den)
            else:
                values["p_interval_num"] = 1
                values["p_interval_denom"] = js_parse_int(text)
        elif key in ("p_interval_num", "p_interval_denom"):
            p_interval_seen = True
            present.add("p_interval")
            values[key] = js_parse_int(raw)
        elif key == "p_ratio":
            p_ratio = js_parse_int(raw)
            present.add(key)
        elif key == "firmware_revision":
            values[key] = str(raw).strip()
            present.add(key)
        elif key == "firmware_api_version":
            values[key] = str(raw).strip()
            present.add(key)
        elif key == "field_i_name":
            values["field_i_names"] = tuple(str(raw).split(","))
            present.add(key)
    if not p_interval_seen and p_ratio is not None and p_ratio > 0:
        values["p_interval_num"] = 1
        values["p_interval_denom"] = p_ratio
        p_interval_seen = True
    return ChirpSysConfig(**values, p_interval_seen=p_interval_seen, present_keys=frozenset(present))


__all__ = [
    "ChirpSysConfig",
    "LOG_START_MARKER",
    "UPSTREAM_DEFAULTS",
    "find_log_boundaries",
    "js_parse_int",
    "parse_chirp_sysconfig",
    "read_bbl_header_text",
]
