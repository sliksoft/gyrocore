"""Betaflight 2026.6.2 simplified-tuning mapping (firmware-faithful).

Upstream (vendored, immutable)::

    third_party/betaflight/firmware/src/main/config/simplified_tuning.c
    applySimplifiedTuningPids / DtermFilters / GyroFilters
    MSP_VALIDATE_SIMPLIFIED_TUNING in msp.c (extracted)

Integer semantics follow C: PID/FF use ``float`` then ``constrain(int)``
(truncation toward 0); filter Hz use integer ``default * multiplier / 100``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from struct import pack, unpack
from typing import Any

# firmware config/simplified_tuning.h
SIMPLIFIED_TUNING_PIDS_MIN = 0
SIMPLIFIED_TUNING_FILTERS_MIN = 10
SIMPLIFIED_TUNING_MAX = 200  # CLI minmax; MSP/uint8 can carry Autotune's 250
SIMPLIFIED_TUNING_DEFAULT = 100
SIMPLIFIED_TUNING_D_DEFAULT = 100

PID_SIMPLIFIED_TUNING_OFF = 0
PID_SIMPLIFIED_TUNING_RP = 1
PID_SIMPLIFIED_TUNING_RPY = 2

# flight/pid.h
PID_GAIN_MAX = 250
F_GAIN_MAX = 1000
PID_ROLL_DEFAULT = (45, 80, 30, 120, 0)
PID_PITCH_DEFAULT = (47, 84, 34, 125, 0)
PID_YAW_DEFAULT = (45, 80, 0, 120, 0)
D_MAX_DEFAULT = (40, 46, 0)
DTERM_LPF1_DYN_MIN_HZ_DEFAULT = 75
DTERM_LPF1_DYN_MAX_HZ_DEFAULT = 150
DTERM_LPF2_HZ_DEFAULT = 150

# sensors/gyro.h
LPF_MAX_HZ = 1000
DYN_LPF_MAX_HZ = 1000
GYRO_LPF1_DYN_MIN_HZ_DEFAULT = 250
GYRO_LPF1_DYN_MAX_HZ_DEFAULT = 500
GYRO_LPF2_HZ_DEFAULT = 500

AXES = ("roll", "pitch", "yaw")
FD_ROLL, FD_PITCH, FD_YAW = 0, 1, 2
PID_DEFAULTS = (PID_ROLL_DEFAULT, PID_PITCH_DEFAULT, PID_YAW_DEFAULT)

FIRMWARE_PROVENANCE = {
    "repository": "https://github.com/betaflight/betaflight",
    "version": "2026.6.2",
    "commit": "e0b7bb01b17b21351057e9ead2d1ab39dd44fa16",
    "functions": [
        "simplified_tuning.c:applySimplifiedTuning",
        "simplified_tuning.c:applySimplifiedTuningPids",
        "simplified_tuning.c:calculateNewPidValues",
        "simplified_tuning.c:applySimplifiedTuningDtermFilters",
        "simplified_tuning.c:calculateNewDTermFilterValues",
        "simplified_tuning.c:applySimplifiedTuningGyroFilters",
        "simplified_tuning.c:calculateNewGyroFilterValues",
        "msp.c:MSP_VALIDATE_SIMPLIFIED_TUNING",
        "common/maths.h:constrain",
    ],
}

AUTOTUNE_SLIDER_MIN = 25
AUTOTUNE_SLIDER_MAX = 250


def c_float(value: float | int) -> float:
    """IEEE-754 binary32, matching firmware ``float``."""
    return float(unpack("f", pack("f", float(value)))[0])


def _fadd(a: float, b: float) -> float:
    return c_float(c_float(a) + c_float(b))


def _fsub(a: float, b: float) -> float:
    return c_float(c_float(a) - c_float(b))


def _fmul(a: float, b: float) -> float:
    return c_float(c_float(a) * c_float(b))


def _fdiv(a: float, b: float) -> float:
    return c_float(c_float(a) / c_float(b))


def c_constrain(amt: float | int, low: int, high: int) -> int:
    """``constrain(int,int,int)`` after C float-to-int conversion (toward 0)."""
    truncated = int(c_float(amt) if isinstance(amt, float) else amt)
    if truncated < low:
        return low
    if truncated > high:
        return high
    return truncated


def c_scale_hz(default: int, multiplier: int, max_hz: int) -> int:
    """Integer ``default * multiplier / 100`` then constrain to ``[0, max_hz]``."""
    return c_constrain((int(default) * int(multiplier)) // 100, 0, max_hz)


@dataclass(frozen=True)
class AxisPid:
    p: int
    i: int
    d: int
    f: int
    d_max: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class FilterSet:
    lpf1_dyn_min_hz: int
    lpf1_dyn_max_hz: int
    lpf1_static_hz: int
    lpf2_static_hz: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass(frozen=True)
class SimplifiedSliders:
    """Firmware slider integers (100 = 1.0x). ``None`` means not supplied."""

    pids_mode: int | None = PID_SIMPLIFIED_TUNING_RPY
    master_multiplier: int | None = SIMPLIFIED_TUNING_DEFAULT
    i_gain: int | None = SIMPLIFIED_TUNING_DEFAULT
    d_gain: int | None = SIMPLIFIED_TUNING_D_DEFAULT
    pi_gain: int | None = SIMPLIFIED_TUNING_DEFAULT
    d_max_gain: int | None = SIMPLIFIED_TUNING_D_DEFAULT
    feedforward_gain: int | None = SIMPLIFIED_TUNING_DEFAULT
    pitch_d_gain: int | None = SIMPLIFIED_TUNING_DEFAULT
    pitch_pi_gain: int | None = SIMPLIFIED_TUNING_DEFAULT
    dterm_filter: int | None = 1
    dterm_filter_multiplier: int | None = SIMPLIFIED_TUNING_DEFAULT
    gyro_filter: int | None = 1
    gyro_filter_multiplier: int | None = SIMPLIFIED_TUNING_DEFAULT

    def missing_for_pids(self) -> tuple[str, ...]:
        names = (
            "pids_mode",
            "master_multiplier",
            "i_gain",
            "d_gain",
            "pi_gain",
            "d_max_gain",
            "feedforward_gain",
            "pitch_d_gain",
            "pitch_pi_gain",
        )
        return tuple(n for n in names if getattr(self, n) is None)

    def missing_for_dterm(self) -> tuple[str, ...]:
        return tuple(n for n in ("dterm_filter", "dterm_filter_multiplier") if getattr(self, n) is None)

    def missing_for_gyro(self) -> tuple[str, ...]:
        return tuple(n for n in ("gyro_filter", "gyro_filter_multiplier") if getattr(self, n) is None)

    def to_dict(self) -> dict[str, int | None]:
        return asdict(self)

    @classmethod
    def defaults(cls) -> "SimplifiedSliders":
        return cls()


@dataclass(frozen=True)
class PidProfileState:
    roll: AxisPid
    pitch: AxisPid
    yaw: AxisPid
    dterm: FilterSet
    sliders: SimplifiedSliders = field(default_factory=SimplifiedSliders)

    def axis(self, name: str) -> AxisPid:
        return {"roll": self.roll, "pitch": self.pitch, "yaw": self.yaw}[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            "roll": self.roll.to_dict(),
            "pitch": self.pitch.to_dict(),
            "yaw": self.yaw.to_dict(),
            "dterm": self.dterm.to_dict(),
            "sliders": self.sliders.to_dict(),
        }


@dataclass(frozen=True)
class GyroConfigState:
    filters: FilterSet
    sliders: SimplifiedSliders = field(default_factory=SimplifiedSliders)

    def to_dict(self) -> dict[str, Any]:
        return {"filters": self.filters.to_dict(), "sliders": self.sliders.to_dict()}


def firmware_default_pid_profile() -> PidProfileState:
    def axis(defaults: tuple[int, int, int, int, int], d_max: int) -> AxisPid:
        return AxisPid(defaults[0], defaults[1], defaults[2], defaults[3], d_max)

    return PidProfileState(
        roll=axis(PID_ROLL_DEFAULT, D_MAX_DEFAULT[0]),
        pitch=axis(PID_PITCH_DEFAULT, D_MAX_DEFAULT[1]),
        yaw=axis(PID_YAW_DEFAULT, D_MAX_DEFAULT[2]),
        dterm=FilterSet(
            DTERM_LPF1_DYN_MIN_HZ_DEFAULT,
            DTERM_LPF1_DYN_MAX_HZ_DEFAULT,
            DTERM_LPF1_DYN_MIN_HZ_DEFAULT,
            DTERM_LPF2_HZ_DEFAULT,
        ),
    )


def firmware_default_gyro() -> GyroConfigState:
    return GyroConfigState(
        FilterSet(
            GYRO_LPF1_DYN_MIN_HZ_DEFAULT,
            GYRO_LPF1_DYN_MAX_HZ_DEFAULT,
            GYRO_LPF1_DYN_MIN_HZ_DEFAULT,
            GYRO_LPF2_HZ_DEFAULT,
        )
    )


def _ratio(slider: int) -> float:
    """C ``uint8 / 100.0f``."""
    return _fdiv(c_float(slider), c_float(100.0))


def calculate_new_pid_values(profile: PidProfileState) -> PidProfileState:
    """``calculateNewPidValues`` — overwrites axes ``0 .. simplified_pids_mode``."""
    s = profile.sliders
    mode = int(s.pids_mode or 0)
    master = _ratio(int(s.master_multiplier))
    pi_gain = _ratio(int(s.pi_gain))
    d_gain = _ratio(int(s.d_gain))
    ff_gain = _ratio(int(s.feedforward_gain))
    i_gain = _ratio(int(s.i_gain))
    axes = [profile.roll, profile.pitch, profile.yaw]
    out: list[AxisPid] = []
    for axis in range(3):
        current = axes[axis]
        if axis > mode:
            out.append(current)
            continue
        pitch_d = _ratio(int(s.pitch_d_gain)) if axis == FD_PITCH else c_float(1.0)
        pitch_pi = _ratio(int(s.pitch_pi_gain)) if axis == FD_PITCH else c_float(1.0)
        default = PID_DEFAULTS[axis]
        p = c_constrain(_fmul(_fmul(_fmul(c_float(default[0]), master), pi_gain), pitch_pi), 0, PID_GAIN_MAX)
        i = c_constrain(_fmul(_fmul(_fmul(_fmul(c_float(default[1]), master), pi_gain), i_gain), pitch_pi), 0, PID_GAIN_MAX)
        d = c_constrain(_fmul(_fmul(_fmul(c_float(default[2]), master), d_gain), pitch_d), 0, PID_GAIN_MAX)
        f = c_constrain(_fmul(_fmul(_fmul(c_float(default[3]), master), pitch_pi), ff_gain), 0, F_GAIN_MAX)
        dmax_default = D_MAX_DEFAULT[axis]
        if dmax_default > 0:
            slider = _ratio(int(s.d_max_gain))
            # firmware: slider/100 + (1 - slider/100) * D / dMax   (* and / left-to-right)
            d_max_gain = _fadd(slider, _fdiv(_fmul(_fsub(c_float(1), slider), c_float(default[2])), c_float(dmax_default)))
        else:
            d_max_gain = c_float(1.0)
        d_max = c_constrain(
            _fmul(_fmul(_fmul(_fmul(c_float(dmax_default), master), d_gain), pitch_d), d_max_gain),
            0,
            PID_GAIN_MAX,
        )
        out.append(AxisPid(p, i, d, f, d_max))
    return replace(profile, roll=out[0], pitch=out[1], yaw=out[2])


def apply_simplified_tuning_pids(profile: PidProfileState) -> PidProfileState:
    if profile.sliders.pids_mode in (None, PID_SIMPLIFIED_TUNING_OFF):
        return profile
    return calculate_new_pid_values(profile)


def calculate_new_dterm_filter_values(profile: PidProfileState) -> PidProfileState:
    s = profile.sliders
    m = int(s.dterm_filter_multiplier)
    d = profile.dterm
    dyn_min, dyn_max, static1, static2 = d.lpf1_dyn_min_hz, d.lpf1_dyn_max_hz, d.lpf1_static_hz, d.lpf2_static_hz
    if dyn_min:
        dyn_min = c_scale_hz(DTERM_LPF1_DYN_MIN_HZ_DEFAULT, m, DYN_LPF_MAX_HZ)
        dyn_max = c_scale_hz(DTERM_LPF1_DYN_MAX_HZ_DEFAULT, m, DYN_LPF_MAX_HZ)
    if static1:
        static1 = c_scale_hz(DTERM_LPF1_DYN_MIN_HZ_DEFAULT, m, DYN_LPF_MAX_HZ)
    if static2:
        static2 = c_scale_hz(DTERM_LPF2_HZ_DEFAULT, m, LPF_MAX_HZ)
    return replace(profile, dterm=FilterSet(dyn_min, dyn_max, static1, static2))


def apply_simplified_tuning_dterm_filters(profile: PidProfileState) -> PidProfileState:
    if not profile.sliders.dterm_filter:
        return profile
    return calculate_new_dterm_filter_values(profile)


def calculate_new_gyro_filter_values(gyro: GyroConfigState) -> GyroConfigState:
    m = int(gyro.sliders.gyro_filter_multiplier)
    f = gyro.filters
    dyn_min, dyn_max, static1, static2 = f.lpf1_dyn_min_hz, f.lpf1_dyn_max_hz, f.lpf1_static_hz, f.lpf2_static_hz
    if dyn_min:
        dyn_min = c_scale_hz(GYRO_LPF1_DYN_MIN_HZ_DEFAULT, m, DYN_LPF_MAX_HZ)
        dyn_max = c_scale_hz(GYRO_LPF1_DYN_MAX_HZ_DEFAULT, m, DYN_LPF_MAX_HZ)
    if static1:
        static1 = c_scale_hz(GYRO_LPF1_DYN_MIN_HZ_DEFAULT, m, DYN_LPF_MAX_HZ)
    if static2:
        static2 = c_scale_hz(GYRO_LPF2_HZ_DEFAULT, m, LPF_MAX_HZ)
    return replace(gyro, filters=FilterSet(dyn_min, dyn_max, static1, static2))


def apply_simplified_tuning_gyro_filters(gyro: GyroConfigState) -> GyroConfigState:
    if not gyro.sliders.gyro_filter:
        return gyro
    return calculate_new_gyro_filter_values(gyro)


def apply_simplified_tuning(profile: PidProfileState, gyro: GyroConfigState) -> tuple[PidProfileState, GyroConfigState]:
    return apply_simplified_tuning_dterm_filters(apply_simplified_tuning_pids(profile)), apply_simplified_tuning_gyro_filters(gyro)


@dataclass(frozen=True)
class FieldMismatch:
    field: str
    current: int
    expected_from_sliders: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SliderValidity:
    """Firmware MSP_VALIDATE_SIMPLIFIED_TUNING equivalent, with per-field evidence."""

    pids_valid: bool
    gyro_valid: bool
    dterm_valid: bool
    pid_mismatches: tuple[FieldMismatch, ...] = ()
    gyro_mismatches: tuple[FieldMismatch, ...] = ()
    dterm_mismatches: tuple[FieldMismatch, ...] = ()
    skipped_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "slider_pids_valid": self.pids_valid,
            "slider_gyro_valid": self.gyro_valid,
            "slider_dterm_valid": self.dterm_valid,
            "pid_mismatches": [m.to_dict() for m in self.pid_mismatches],
            "gyro_mismatches": [m.to_dict() for m in self.gyro_mismatches],
            "dterm_mismatches": [m.to_dict() for m in self.dterm_mismatches],
            "skipped_reasons": list(self.skipped_reasons),
        }


def _pid_mismatches(current: PidProfileState, applied: PidProfileState) -> tuple[FieldMismatch, ...]:
    out: list[FieldMismatch] = []
    for name in AXES:
        c, a = current.axis(name), applied.axis(name)
        for field_name in ("p", "i", "d", "f", "d_max"):
            cv, av = getattr(c, field_name), getattr(a, field_name)
            if cv != av:
                out.append(FieldMismatch(f"{name}.{field_name}", cv, av))
    return tuple(out)


def _filter_mismatches(prefix: str, current: FilterSet, applied: FilterSet) -> tuple[FieldMismatch, ...]:
    out: list[FieldMismatch] = []
    for field_name in ("lpf1_dyn_min_hz", "lpf1_dyn_max_hz", "lpf1_static_hz", "lpf2_static_hz"):
        cv, av = getattr(current, field_name), getattr(applied, field_name)
        if cv != av:
            out.append(FieldMismatch(f"{prefix}.{field_name}", cv, av))
    return tuple(out)


def validate_simplified_tuning(profile: PidProfileState, gyro: GyroConfigState) -> SliderValidity:
    """Recompute from sliders and compare, matching MSP_VALIDATE_SIMPLIFIED_TUNING."""
    skipped: list[str] = []
    if profile.sliders.missing_for_pids():
        skipped.append("pids_sliders_incomplete:" + ",".join(profile.sliders.missing_for_pids()))
        pid_mis: tuple[FieldMismatch, ...] = ()
        pids_valid = False
    else:
        applied_pids = apply_simplified_tuning_pids(profile)
        pid_mis = _pid_mismatches(profile, applied_pids)
        pids_valid = not pid_mis

    if gyro.sliders.missing_for_gyro():
        skipped.append("gyro_sliders_incomplete:" + ",".join(gyro.sliders.missing_for_gyro()))
        gyro_mis: tuple[FieldMismatch, ...] = ()
        gyro_valid = False
    else:
        applied_gyro = apply_simplified_tuning_gyro_filters(gyro)
        gyro_mis = _filter_mismatches("gyro", gyro.filters, applied_gyro.filters)
        gyro_valid = not gyro_mis

    if profile.sliders.missing_for_dterm():
        skipped.append("dterm_sliders_incomplete:" + ",".join(profile.sliders.missing_for_dterm()))
        dterm_mis: tuple[FieldMismatch, ...] = ()
        dterm_valid = False
    else:
        applied_dterm = apply_simplified_tuning_dterm_filters(profile)
        dterm_mis = _filter_mismatches("dterm", profile.dterm, applied_dterm.dterm)
        dterm_valid = not dterm_mis

    return SliderValidity(pids_valid, gyro_valid, dterm_valid, pid_mis, gyro_mis, dterm_mis, tuple(skipped))


def sliders_outside_cli_range(sliders: SimplifiedSliders) -> tuple[str, ...]:
    """Warn when a slider fits uint8 / Autotune 25–250 but not CLI minmax 0/10–200."""
    out: list[str] = []
    pid_fields = (
        "master_multiplier",
        "i_gain",
        "d_gain",
        "pi_gain",
        "pitch_d_gain",
        "pitch_pi_gain",
    )
    for name in pid_fields:
        v = getattr(sliders, name)
        if v is not None and not (SIMPLIFIED_TUNING_PIDS_MIN <= v <= SIMPLIFIED_TUNING_MAX):
            out.append(name)
    for name in ("d_max_gain", "feedforward_gain"):
        v = getattr(sliders, name)
        if v is not None and not (0 <= v <= SIMPLIFIED_TUNING_MAX):
            out.append(name)
    for name in ("dterm_filter_multiplier", "gyro_filter_multiplier"):
        v = getattr(sliders, name)
        if v is not None and not (SIMPLIFIED_TUNING_FILTERS_MIN <= v <= SIMPLIFIED_TUNING_MAX):
            out.append(name)
    return tuple(out)


__all__ = [
    "AUTOTUNE_SLIDER_MAX",
    "AUTOTUNE_SLIDER_MIN",
    "AXES",
    "AxisPid",
    "D_MAX_DEFAULT",
    "FIRMWARE_PROVENANCE",
    "FilterSet",
    "GyroConfigState",
    "PID_DEFAULTS",
    "PID_GAIN_MAX",
    "PID_SIMPLIFIED_TUNING_OFF",
    "PID_SIMPLIFIED_TUNING_RP",
    "PID_SIMPLIFIED_TUNING_RPY",
    "PidProfileState",
    "SIMPLIFIED_TUNING_DEFAULT",
    "SIMPLIFIED_TUNING_MAX",
    "SimplifiedSliders",
    "SliderValidity",
    "apply_simplified_tuning",
    "apply_simplified_tuning_dterm_filters",
    "apply_simplified_tuning_gyro_filters",
    "apply_simplified_tuning_pids",
    "c_constrain",
    "c_float",
    "c_scale_hz",
    "firmware_default_gyro",
    "firmware_default_pid_profile",
    "sliders_outside_cli_range",
    "validate_simplified_tuning",
]
