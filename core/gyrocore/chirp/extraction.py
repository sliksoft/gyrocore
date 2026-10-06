"""CHIRP segment extraction — port of upstream ``parseChirpLog`` sample collection.

Upstream (``third_party/betaflight/configurator/src/js/blackbox/chirp_bbl_parser.ts``):

- ``validateDebugModeIsChirp``    -> :func:`validate_chirp_debug_mode`
- ``handleSFrame`` (BOXCHIRP bit 6 on/off, ``closeSegment`` on chirp-off)
- ``collectIfActive``             (drop frames with ``debug[1]`` outside -1..2)
- ``collectSample``               (``value * hiResScale`` stored as Float32)
- ``updateSegments`` / ``closeSegment`` (axis change opens a segment; inclusive end)
- end-of-data ``closeSegment``

and ``src/composables/useAutotune.ts`` ``analyzeLog`` (a later segment of the
same axis replaces an earlier one -> :attr:`ChirpExtraction.selected_by_axis`).

Input is the :class:`~gyrocore.chirp.frames.ChirpFrames` table built from
GyroCore's decoded CSV. Per-row ``flightModeFlags`` replaces upstream's S-frame
events: ``blackbox_decode`` repeats the latest S-frame values on every main
row, so the active/inactive transitions happen at the same main-frame
boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .debug_modes import chirp_debug_mode_index, effective_chirp_api_version
from .frames import BOXCHIRP_BIT, ChirpFrames, REQUIRED_FIELDS
from .sysconfig import ChirpSysConfig

AXIS_NAMES = ("roll", "pitch", "yaw")


@dataclass(frozen=True)
class ChirpSegment:
    """One run of samples during which the chirp excited ``axis`` (inclusive indices)."""

    index: int
    axis: int
    start_idx: int
    end_idx: int
    start_time_us: float
    end_time_us: float

    @property
    def sample_count(self) -> int:
        return self.end_idx - self.start_idx + 1

    @property
    def duration_s(self) -> float:
        return max(0.0, (self.end_time_us - self.start_time_us) / 1e6)

    @property
    def axis_name(self) -> str:
        return AXIS_NAMES[self.axis] if 0 <= self.axis < 3 else f"axis{self.axis}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "axis": self.axis,
            "axis_name": self.axis_name,
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
            "sample_count": self.sample_count,
            "start_time_us": self.start_time_us,
            "end_time_us": self.end_time_us,
            "duration_s": self.duration_s,
        }


@dataclass(frozen=True)
class ChirpExtraction:
    """Collected CHIRP samples (concatenated like upstream ``ChirpData``) + evidence."""

    detected: bool
    segments: tuple[ChirpSegment, ...]
    selected_by_axis: dict[int, int]
    setpoint: np.ndarray  # float32, shape (3, n)
    gyro: np.ndarray  # float32, shape (3, n)
    debug: np.ndarray  # float32, shape (4, n)
    time_us: np.ndarray  # float64, shape (n,)
    frame_rows: np.ndarray  # int64 row index into ChirpFrames
    total_frames: int
    dropped_axis_frames: int
    high_resolution_scale: float
    flag_gating: str
    api_version: str | None
    chirp_debug_mode_index: int | None
    frequency_range_hz: tuple[float, float] | None
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def sample_count(self) -> int:
        return int(self.time_us.shape[0])

    @property
    def ok(self) -> bool:
        return not self.errors

    def segment_signals(self, segment: ChirpSegment) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(input=setpoint, output=gyroADC, timestamps_us)`` slices as ``computeAxisResult``."""
        sl = slice(segment.start_idx, segment.end_idx + 1)
        return self.setpoint[segment.axis, sl], self.gyro[segment.axis, sl], self.time_us[sl]

    def selected_segments(self) -> list[ChirpSegment]:
        return [self.segments[i] for _, i in sorted(self.selected_by_axis.items())]

    def to_dict(self) -> dict[str, Any]:
        return {
            "detected": self.detected,
            "segments": [s.to_dict() for s in self.segments],
            "selected_by_axis": {AXIS_NAMES[a]: i for a, i in sorted(self.selected_by_axis.items())},
            "sample_count": self.sample_count,
            "total_frames": self.total_frames,
            "dropped_axis_frames": self.dropped_axis_frames,
            "high_resolution_scale": self.high_resolution_scale,
            "flag_gating": self.flag_gating,
            "api_version": self.api_version,
            "chirp_debug_mode_index": self.chirp_debug_mode_index,
            "frequency_range_hz": list(self.frequency_range_hz) if self.frequency_range_hz else None,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def validate_chirp_debug_mode(
    sysconfig: ChirpSysConfig, api_version: str | None = None
) -> tuple[str, int, str | None]:
    """``validateDebugModeIsChirp``: returns ``(api_version_used, chirp_index, error_code)``."""
    api = effective_chirp_api_version(sysconfig.firmware_api_version, api_version)
    index = chirp_debug_mode_index(api)
    if index < 0:
        return api, index, "chirp_debug_mode_unsupported_api"
    if sysconfig.upstream_value("debug_mode") != index:
        return api, index, "not_chirp_debug_mode"
    return api, index, None


def _empty(frames: ChirpFrames | None, **kw: Any) -> ChirpExtraction:
    base = dict(
        detected=False,
        segments=(),
        selected_by_axis={},
        setpoint=np.zeros((3, 0), dtype=np.float32),
        gyro=np.zeros((3, 0), dtype=np.float32),
        debug=np.zeros((4, 0), dtype=np.float32),
        time_us=np.zeros(0),
        frame_rows=np.zeros(0, dtype=np.int64),
        total_frames=frames.frame_count if frames is not None else 0,
        dropped_axis_frames=0,
        high_resolution_scale=1.0,
        flag_gating="none",
        api_version=None,
        chirp_debug_mode_index=None,
        frequency_range_hz=None,
    )
    base.update(kw)
    return ChirpExtraction(**base)


def extract_chirp(
    frames: ChirpFrames,
    sysconfig: ChirpSysConfig | None,
    *,
    api_version: str | None = None,
    require_flight_mode_flags: bool = False,
) -> ChirpExtraction:
    """Collect chirp-active samples and axis segments from a frame table."""
    warnings = list(frames.warnings)
    api_used: str | None = None
    chirp_index: int | None = None
    scale = 1.0
    freq_range = None
    if sysconfig is None:
        warnings.append("sysconfig_missing_debug_mode_unverified")
    else:
        api_used, chirp_index, err = validate_chirp_debug_mode(sysconfig, api_version)
        if err:
            return _empty(frames, api_version=api_used, chirp_debug_mode_index=chirp_index, errors=(err,), warnings=tuple(warnings))
        if sysconfig.field_i_names:
            missing = [f for f in REQUIRED_FIELDS if f not in sysconfig.field_i_names]
            if missing:
                return _empty(
                    frames,
                    api_version=api_used,
                    chirp_debug_mode_index=chirp_index,
                    errors=("missing_required_field:" + ",".join(missing),),
                    warnings=tuple(warnings),
                )
        scale = sysconfig.high_resolution_scale
        freq_range = sysconfig.chirp_frequency_range_hz()
        if freq_range is None:
            warnings.append("chirp_frequency_range_missing")
    if frames.subsampled:
        return _empty(frames, errors=("subsampled_input",), warnings=tuple(warnings))

    flags = frames.flight_mode_flags
    if flags is None:
        if require_flight_mode_flags:
            return _empty(frames, errors=("flight_mode_flags_unavailable",), warnings=tuple(warnings))
        warnings.append("chirp_mode_flag_unavailable_debug_axis_only")
        gating = "debug_axis_only"
    else:
        gating = "flight_mode_flags"

    axis_col = frames.debug[1]
    rows: list[int] = []
    seg_bounds: list[list[int]] = []  # [axis, start, end]
    active = flags is None
    current_axis = -1
    dropped = 0
    chirp_bit = 1 << BOXCHIRP_BIT

    def close_segment(end_idx: int, axis: int) -> None:
        if seg_bounds and seg_bounds[-1][0] == axis:
            seg_bounds[-1][2] = end_idx

    for r in range(frames.frame_count):
        if flags is not None:
            f = int(flags[r])
            now = active if f < 0 else bool(f & chirp_bit)
            if now and not active:
                current_axis = -1
            if not now and active:
                close_segment(len(rows) - 1, current_axis)
                current_axis = -1
            active = now
        if not active:
            continue
        a = axis_col[r]
        if not np.isfinite(a) or a != int(a) or a < -1 or a > 2:
            dropped += 1
            continue
        axis = int(a)
        rows.append(r)
        sample_idx = len(rows) - 1
        if axis < 0:
            if current_axis >= 0:
                close_segment(sample_idx - 1, current_axis)
        elif axis != current_axis:
            if current_axis >= 0:
                close_segment(sample_idx - 1, current_axis)
            seg_bounds.append([axis, sample_idx, sample_idx])
        current_axis = axis
    if current_axis >= 0:
        close_segment(len(rows) - 1, current_axis)

    idx = np.asarray(rows, dtype=np.int64)
    setpoint = (frames.setpoint[:, idx] * scale).astype(np.float32)
    gyro = (frames.gyro_adc[:, idx] * scale).astype(np.float32)
    debug = frames.debug[:, idx].astype(np.float32)
    time_us = frames.time_us[idx]

    segments = tuple(
        ChirpSegment(
            index=i,
            axis=axis,
            start_idx=start,
            end_idx=end,
            start_time_us=float(time_us[start]) if time_us.size else float("nan"),
            end_time_us=float(time_us[end]) if time_us.size else float("nan"),
        )
        for i, (axis, start, end) in enumerate(seg_bounds)
    )
    selected: dict[int, int] = {}
    for seg in segments:
        selected[seg.axis] = seg.index
    if dropped:
        warnings.append("chirp_axis_out_of_range_frames_dropped")
    if len(segments) > len(selected):
        warnings.append("repeated_axis_segments_last_selected")
    if not segments:
        warnings.append("no_chirp_segments_detected")

    return ChirpExtraction(
        detected=bool(segments),
        segments=segments,
        selected_by_axis=selected,
        setpoint=setpoint,
        gyro=gyro,
        debug=debug,
        time_us=time_us,
        frame_rows=idx,
        total_frames=frames.frame_count,
        dropped_axis_frames=dropped,
        high_resolution_scale=scale,
        flag_gating=gating,
        api_version=api_used,
        chirp_debug_mode_index=chirp_index,
        frequency_range_hz=freq_range,
        warnings=tuple(warnings),
    )


__all__ = [
    "AXIS_NAMES",
    "ChirpExtraction",
    "ChirpSegment",
    "extract_chirp",
    "validate_chirp_debug_mode",
]
