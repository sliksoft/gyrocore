"""Typed Betaflight baseline/candidate config foundation.

This module is intentionally additive and non-invasive: it provides a central typed
representation for parsed Betaflight tuning config data without changing pipeline behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

_PID_COMPONENTS = ("p", "i", "d", "ff")
_AXES = ("roll", "pitch", "yaw")

_FILTER_FIELD_NAMES = {
    "gyro_lpf1_static_hz",
    "gyro_lpf1_dyn_min_hz",
    "gyro_lpf1_dyn_max_hz",
    "gyro_lpf1_dyn_expo",
    "gyro_lpf2_static_hz",
    "gyro_notch1_hz",
    "gyro_notch1_cutoff",
    "gyro_notch2_hz",
    "gyro_notch2_cutoff",
    "dterm_lpf1_static_hz",
    "dterm_lpf1_dyn_min_hz",
    "dterm_lpf1_dyn_max_hz",
    "dterm_lpf1_dyn_expo",
    "dterm_lpf2_static_hz",
    "dterm_notch_hz",
    "dterm_notch_cutoff",
    "dyn_notch_count",
    "dyn_notch_min_hz",
    "dyn_notch_max_hz",
    "dyn_notch_q",
    "dyn_notch_width_percent",
    "rpm_filter_harmonics",
    "rpm_filter_min_hz",
    "rpm_filter_max_hz",
    "rpm_filter_fade_range_hz",
    "rpm_filter_lpf_hz",
    "rpm_filter_q",
    "rpm_filter_weights",
    "yaw_lowpass_hz",
    "simplified_gyro_filter_multiplier",
    "simplified_dterm_filter_multiplier",
    "dyn_idle_min_rpm",
    "transient_throttle_limit",
    "anti_gravity_gain",
    "anti_gravity_cutoff",
    "anti_gravity_p_gain",
    "feedforward_smooth_factor",
    "feedforward_jitter_factor",
    "feedforward_boost",
    "feedforward_transition",
    "rc_smoothing",
    "rc_smoothing_auto_factor",
    "rc_smoothing_feedforward",
    "iterm_relax",
    "iterm_rotation",
    "tpa_rate",
    "tpa_breakpoint",
    "throttle_boost",
    "motor_output_limit",
    "rpm_filter",
    "dshot_bidir",
    "motor_poles",
    "gyro_lpf1_type",
    "gyro_lpf2_type",
    "dterm_lpf1_type",
    "dterm_lpf2_type",
    "pid_process_denom",
    "motor_pwm_protocol",
    "blackbox_sample_rate",
    "blackbox_rate_denom",
    "simplified_master_multiplier",
    "simplified_pids_mode",
    "simplified_gyro_filter",
    "simplified_dterm_filter",
    "simplified_d_gain",
    "simplified_dmax_gain",
    "pidsum_limit",
    "pidsum_limit_yaw",
    "iterm_relax_cutoff",
    "feedforward_averaging",
}

_ENUM_CONTEXT_FIELD_NAMES = {
    "gyro_lpf1_type",
    "gyro_lpf2_type",
    "dterm_lpf1_type",
    "dterm_lpf2_type",
    "motor_pwm_protocol",
    "simplified_pids_mode",
    "simplified_gyro_filter",
    "simplified_dterm_filter",
    "feedforward_averaging",
}

_FLOAT_CONTEXT_FIELD_NAMES = {
    "simplified_master_multiplier",
    "simplified_d_gain",
    "simplified_dmax_gain",
    "simplified_gyro_filter_multiplier",
    "simplified_dterm_filter_multiplier",
    "iterm_relax_cutoff",
}

_D_MIN_FIELD_MAP = {
    "d_min_roll": "roll",
    "d_min_pitch": "pitch",
    "d_min_yaw": "yaw",
    "d_min_boost_gain": "boost_gain",
    "d_min_advance": "advance",
}

_ALT_PID_KEYS = {
    "p_roll": ("roll", "p"),
    "i_roll": ("roll", "i"),
    "d_roll": ("roll", "d"),
    "f_roll": ("roll", "ff"),
    "ff_roll": ("roll", "ff"),
    "roll_p": ("roll", "p"),
    "roll_i": ("roll", "i"),
    "roll_d": ("roll", "d"),
    "roll_f": ("roll", "ff"),
    "roll_ff": ("roll", "ff"),
    "p_pitch": ("pitch", "p"),
    "i_pitch": ("pitch", "i"),
    "d_pitch": ("pitch", "d"),
    "f_pitch": ("pitch", "ff"),
    "ff_pitch": ("pitch", "ff"),
    "pitch_p": ("pitch", "p"),
    "pitch_i": ("pitch", "i"),
    "pitch_d": ("pitch", "d"),
    "pitch_f": ("pitch", "ff"),
    "pitch_ff": ("pitch", "ff"),
    "p_yaw": ("yaw", "p"),
    "i_yaw": ("yaw", "i"),
    "d_yaw": ("yaw", "d"),
    "f_yaw": ("yaw", "ff"),
    "ff_yaw": ("yaw", "ff"),
    "yaw_p": ("yaw", "p"),
    "yaw_i": ("yaw", "i"),
    "yaw_d": ("yaw", "d"),
    "yaw_f": ("yaw", "ff"),
    "yaw_ff": ("yaw", "ff"),
}


def _coerce_int(raw: Any) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError):
        return None


def _coerce_float(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _coerce_bool(raw: Any) -> bool | None:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in {"on", "true", "yes", "1", "enabled", "enable"}:
        return True
    if s in {"off", "false", "no", "0", "disabled", "disable"}:
        return False
    return None


def _coerce_enum(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().strip('"').strip("'")
    return s.upper() if s else None


def _coerce_rpm_weights(raw: Any) -> str | list[float] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        return s or None
    if isinstance(raw, (list, tuple)):
        out: list[float] = []
        for item in raw:
            fv = _coerce_float(item)
            if fv is None:
                continue
            out.append(fv)
        return out if out else None
    return None


@dataclass(frozen=True)
class BetaflightAxisPid:
    p: int | None = None
    i: int | None = None
    d: int | None = None
    ff: int | None = None

    def to_dict(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for comp in _PID_COMPONENTS:
            value = getattr(self, comp)
            if value is not None:
                out[comp] = int(value)
        return out


@dataclass(frozen=True)
class BetaflightPidConfig:
    roll: BetaflightAxisPid = field(default_factory=BetaflightAxisPid)
    pitch: BetaflightAxisPid = field(default_factory=BetaflightAxisPid)
    yaw: BetaflightAxisPid = field(default_factory=BetaflightAxisPid)

    def to_dict(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for axis in _AXES:
            axis_dict = getattr(self, axis).to_dict()
            if axis_dict:
                out[axis] = axis_dict
        return out


@dataclass(frozen=True)
class BetaflightDMinConfig:
    roll: int | None = None
    pitch: int | None = None
    yaw: int | None = None
    boost_gain: int | None = None
    advance: int | None = None

    def to_dict(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for key in ("roll", "pitch", "yaw", "boost_gain", "advance"):
            value = getattr(self, key)
            if value is not None:
                out[key] = int(value)
        return out


@dataclass(frozen=True)
class BetaflightRpmFilterConfig:
    harmonics: int | None = None
    min_hz: int | None = None
    max_hz: int | None = None
    fade_range_hz: int | None = None
    q: int | None = None
    weights: str | list[float] | None = None
    enabled: bool | None = None


@dataclass(frozen=True)
class BetaflightDynamicIdleConfig:
    dyn_idle_min_rpm: int | None = None
    transient_throttle_limit: int | None = None


@dataclass(frozen=True)
class BetaflightFirmwareMetadata:
    firmware_name: str | None = None
    firmware_version: str | None = None
    betaflight_major: int | None = None
    betaflight_minor: int | None = None
    betaflight_patch: int | None = None
    support_classification: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in (
            "firmware_name",
            "firmware_version",
            "betaflight_major",
            "betaflight_minor",
            "betaflight_patch",
            "support_classification",
        ):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


@dataclass(frozen=True)
class BetaflightFilterConfig:
    values: dict[str, Any] = field(default_factory=dict)
    rpm_filter: BetaflightRpmFilterConfig = field(default_factory=BetaflightRpmFilterConfig)
    dynamic_idle: BetaflightDynamicIdleConfig = field(default_factory=BetaflightDynamicIdleConfig)

    def to_dict(self) -> dict[str, Any]:
        out = dict(self.values)
        if self.rpm_filter.harmonics is not None:
            out["rpm_filter_harmonics"] = int(self.rpm_filter.harmonics)
        if self.rpm_filter.min_hz is not None:
            out["rpm_filter_min_hz"] = int(self.rpm_filter.min_hz)
        if self.rpm_filter.max_hz is not None:
            out["rpm_filter_max_hz"] = int(self.rpm_filter.max_hz)
        if self.rpm_filter.fade_range_hz is not None:
            out["rpm_filter_fade_range_hz"] = int(self.rpm_filter.fade_range_hz)
        if self.rpm_filter.q is not None:
            out["rpm_filter_q"] = int(self.rpm_filter.q)
        if self.rpm_filter.weights is not None:
            out["rpm_filter_weights"] = self.rpm_filter.weights
        if self.rpm_filter.enabled is not None:
            out["rpm_filter"] = bool(self.rpm_filter.enabled)
        if self.dynamic_idle.dyn_idle_min_rpm is not None:
            out["dyn_idle_min_rpm"] = int(self.dynamic_idle.dyn_idle_min_rpm)
        if self.dynamic_idle.transient_throttle_limit is not None:
            out["transient_throttle_limit"] = int(self.dynamic_idle.transient_throttle_limit)
        return out


@dataclass(frozen=True)
class BetaflightConfig:
    pid: BetaflightPidConfig = field(default_factory=BetaflightPidConfig)
    d_min: BetaflightDMinConfig = field(default_factory=BetaflightDMinConfig)
    filters: BetaflightFilterConfig = field(default_factory=BetaflightFilterConfig)
    firmware: BetaflightFirmwareMetadata = field(default_factory=BetaflightFirmwareMetadata)
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_baseline_dict(cls, raw: Mapping[str, Any] | None) -> BetaflightConfig:
        data = dict(raw) if isinstance(raw, Mapping) else {}
        nested_filters = data.get("filters") if isinstance(data.get("filters"), Mapping) else {}
        nested_pid = data.get("pid") if isinstance(data.get("pid"), Mapping) else {}
        nested_d_min = data.get("d_min") if isinstance(data.get("d_min"), Mapping) else {}
        nested_meta = data.get("meta") if isinstance(data.get("meta"), Mapping) else {}

        filter_values: dict[str, Any] = {}
        source_filters = (nested_filters, data)
        for source in source_filters:
            if not isinstance(source, Mapping):
                continue
            for key in _FILTER_FIELD_NAMES:
                if key not in source:
                    continue
                raw_value = source.get(key)
                if key in {"rpm_filter", "dshot_bidir"}:
                    value = _coerce_bool(raw_value)
                elif key == "rpm_filter_weights":
                    value = _coerce_rpm_weights(raw_value)
                elif key in _ENUM_CONTEXT_FIELD_NAMES:
                    value = _coerce_enum(raw_value)
                elif key in _FLOAT_CONTEXT_FIELD_NAMES:
                    value = _coerce_float(raw_value)
                else:
                    value = _coerce_int(raw_value)
                if value is not None:
                    filter_values[key] = value

        axis_pid: dict[str, BetaflightAxisPid] = {}
        for axis in _AXES:
            blk = nested_pid.get(axis) if isinstance(nested_pid, Mapping) else {}
            if not isinstance(blk, Mapping):
                blk = {}
            axis_pid_values: dict[str, int | None] = {}
            for comp in _PID_COMPONENTS:
                raw_v = blk.get(comp)
                val = _coerce_int(raw_v)
                if val is not None:
                    axis_pid_values[comp] = val
            axis_pid[axis] = BetaflightAxisPid(**axis_pid_values)

        for key, (axis, comp) in _ALT_PID_KEYS.items():
            if key not in data:
                continue
            val = _coerce_int(data.get(key))
            if val is None:
                continue
            current = axis_pid[axis]
            axis_pid[axis] = BetaflightAxisPid(
                p=val if comp == "p" else current.p,
                i=val if comp == "i" else current.i,
                d=val if comp == "d" else current.d,
                ff=val if comp == "ff" else current.ff,
            )

        d_min_values: dict[str, int] = {}
        for key in ("roll", "pitch", "yaw", "boost_gain", "advance"):
            val = _coerce_int(nested_d_min.get(key))
            if val is not None:
                d_min_values[key] = val
        for key, mapped in _D_MIN_FIELD_MAP.items():
            if key not in data:
                continue
            val = _coerce_int(data.get(key))
            if val is not None:
                d_min_values[mapped] = val

        rpm_cfg = BetaflightRpmFilterConfig(
            harmonics=_coerce_int(filter_values.get("rpm_filter_harmonics")),
            min_hz=_coerce_int(filter_values.get("rpm_filter_min_hz")),
            max_hz=_coerce_int(filter_values.get("rpm_filter_max_hz")),
            fade_range_hz=_coerce_int(filter_values.get("rpm_filter_fade_range_hz")),
            q=_coerce_int(filter_values.get("rpm_filter_q")),
            weights=_coerce_rpm_weights(filter_values.get("rpm_filter_weights")),
            enabled=_coerce_bool(filter_values.get("rpm_filter")),
        )
        dyn_idle_cfg = BetaflightDynamicIdleConfig(
            dyn_idle_min_rpm=_coerce_int(filter_values.get("dyn_idle_min_rpm")),
            transient_throttle_limit=_coerce_int(filter_values.get("transient_throttle_limit")),
        )
        fw_source = {**nested_meta, **(data if isinstance(data, Mapping) else {})}
        support = fw_source.get("betaflight_support")
        support_class = None
        if isinstance(support, Mapping):
            support_class = (
                support.get("classification")
                or support.get("status")
                or support.get("support_classification")
            )
        if support_class is None:
            support_class = fw_source.get("support_classification")

        firmware = BetaflightFirmwareMetadata(
            firmware_name=(fw_source.get("firmware_name") or fw_source.get("firmware")),
            firmware_version=(
                fw_source.get("firmware_version")
                or fw_source.get("betaflight_version")
                or fw_source.get("version")
            ),
            betaflight_major=_coerce_int(fw_source.get("betaflight_major")),
            betaflight_minor=_coerce_int(fw_source.get("betaflight_minor")),
            betaflight_patch=_coerce_int(fw_source.get("betaflight_patch")),
            support_classification=str(support_class) if support_class is not None else None,
        )
        return cls(
            pid=BetaflightPidConfig(
                roll=axis_pid["roll"],
                pitch=axis_pid["pitch"],
                yaw=axis_pid["yaw"],
            ),
            d_min=BetaflightDMinConfig(**d_min_values),
            filters=BetaflightFilterConfig(
                values={
                    key: value
                    for key, value in filter_values.items()
                    if key
                    not in {
                        "rpm_filter_harmonics",
                        "rpm_filter_min_hz",
                        "rpm_filter_max_hz",
                        "rpm_filter_fade_range_hz",
                        "rpm_filter_q",
                        "rpm_filter_weights",
                        "rpm_filter",
                        "dyn_idle_min_rpm",
                        "transient_throttle_limit",
                    }
                },
                rpm_filter=rpm_cfg,
                dynamic_idle=dyn_idle_cfg,
            ),
            firmware=firmware,
            meta={
                key: value
                for key, value in nested_meta.items()
                if key
                not in {
                    "firmware_name",
                    "firmware",
                    "firmware_version",
                    "betaflight_version",
                    "betaflight_major",
                    "betaflight_minor",
                    "betaflight_patch",
                    "betaflight_support",
                    "support_classification",
                }
            },
        )

    def to_baseline_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        filters = self.filters.to_dict()
        if filters:
            out["filters"] = filters
        pid = self.pid.to_dict()
        if pid:
            out["pid"] = pid
        d_min = self.d_min.to_dict()
        if d_min:
            out["d_min"] = d_min
        firmware_meta = self.firmware.to_dict()
        meta = dict(self.meta)
        meta.update(firmware_meta)
        if meta:
            out["meta"] = meta
        return out

    def to_nested_dict(self) -> dict[str, Any]:
        return self.to_baseline_dict()
