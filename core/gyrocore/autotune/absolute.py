"""Current absolute tune + non-actionable global AbsoluteTuneProposal (WU9).

Pipeline::

    WU8 per-axis recommendations
            → GyroCore global-slider merge (not Betaflight)
            → firmware simplified-tuning mapping
            → AbsoluteTuneProposal  (actionable = False)

This module does **not** run mechanical safety, safe-tune clamps,
``tuning_output_safety``, CLI generation, MSP, or FC writes.

Current-tune sources reuse WU8 :func:`extract_current_tune` and WU2
:func:`parse_cli_profile_blocks` / :func:`header_pairs`. No extra CLI parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Mapping

from gyrocore.autotune.current_tune import (
    CurrentTune,
    TuneValue,
    ValueSource,
    extract_current_tune,
)
from gyrocore.autotune.engine import (
    REQUIRED_DOWNSTREAM_STAGES,
    AutotuneRecommendationResult,
    RecommendationStatus,
)
from gyrocore.autotune.merge import (
    MERGE_REQUIRES_REVIEW,
    GlobalSliderMerge,
    merge_autotune_sliders,
)
from gyrocore.betaflight.cli_profile import parse_cli_profile_blocks
from gyrocore.betaflight.simplified_tuning import (
    AXES,
    FIRMWARE_PROVENANCE,
    PID_SIMPLIFIED_TUNING_OFF,
    AxisPid,
    FilterSet,
    GyroConfigState,
    PidProfileState,
    SimplifiedSliders,
    SliderValidity,
    apply_simplified_tuning,
    sliders_outside_cli_range,
    validate_simplified_tuning,
)
from gyrocore.chirp.sysconfig import header_pairs, js_parse_int

PROPOSAL_KIND = "gyrocore_absolute_tune_proposal"
NON_ACTIONABLE_NOTICE = (
    "AbsoluteTuneProposal only. Not a flight-controller tune: it has not passed mechanical safety, "
    "safe-tune clamps or tuning_output_safety, and GyroCore provides no apply/MSP/CLI path for it."
)

_ON_OFF = {"OFF": 0, "ON": 1, "0": 0, "1": 1}
_PIDS_MODE = {"OFF": 0, "RP": 1, "RPY": 2, "0": 0, "1": 1, "2": 2}

# Firmware CLI names, plus WU2's older ``simplified_dmax_gain`` alias (read-only).
_EXTRA_SLIDER_KEYS = (
    ("d_max_gain", ("simplified_d_max_gain", "simplified_dmax_gain")),
    ("pitch_pi_gain", ("simplified_pitch_pi_gain",)),
    ("pitch_d_gain", ("simplified_pitch_d_gain", "simplified_roll_pitch_ratio")),
    ("gyro_filter_multiplier", ("simplified_gyro_filter_multiplier",)),
)
_GYRO_FILTER_ON = ("simplified_gyro_filter",)
_DTERM_FILTER_ON = ("simplified_dterm_filter",)

_PID_KEYS = {
    "roll": {
        "p": ("p_roll", "roll_p"),
        "i": ("i_roll", "roll_i"),
        "d": ("d_roll", "roll_d"),
    },
    "pitch": {
        "p": ("p_pitch", "pitch_p"),
        "i": ("i_pitch", "pitch_i"),
        "d": ("d_pitch", "pitch_d"),
    },
    "yaw": {
        "p": ("p_yaw", "yaw_p"),
        "i": ("i_yaw", "yaw_i"),
        "d": ("d_yaw", "yaw_d"),
    },
}
_FF_KEYS = {
    "roll": ("f_roll", "ff_roll", "roll_ff", "roll_f"),
    "pitch": ("f_pitch", "ff_pitch", "pitch_ff", "pitch_f"),
    "yaw": ("f_yaw", "ff_yaw", "yaw_ff", "yaw_f"),
}
_DMAX_KEYS = {
    "roll": ("d_max_roll", "d_min_roll"),
    "pitch": ("d_max_pitch", "d_min_pitch"),
    "yaw": ("d_max_yaw", "d_min_yaw"),
}
_DTERM_KEYS = (
    ("lpf1_dyn_min_hz", "dterm_lpf1_dyn_min_hz"),
    ("lpf1_dyn_max_hz", "dterm_lpf1_dyn_max_hz"),
    ("lpf1_static_hz", "dterm_lpf1_static_hz"),
    ("lpf2_static_hz", "dterm_lpf2_static_hz"),
)
_GYRO_KEYS = (
    ("lpf1_dyn_min_hz", "gyro_lpf1_dyn_min_hz"),
    ("lpf1_dyn_max_hz", "gyro_lpf1_dyn_max_hz"),
    ("lpf1_static_hz", "gyro_lpf1_static_hz"),
    ("lpf2_static_hz", "gyro_lpf2_static_hz"),
)


def _missing(name: str, note: str = "") -> TuneValue:
    return TuneValue(name, None, ValueSource.MISSING, "none", None, note)


def _int_tv(name: str, raw: Any, origin: str) -> TuneValue:
    if raw is None:
        return _missing(name, "absent")
    if isinstance(raw, bool):
        return TuneValue(name, int(raw), ValueSource.PARSED, origin, raw, "")
    if isinstance(raw, int):
        return TuneValue(name, raw, ValueSource.PARSED, origin, raw, "")
    text = str(raw).strip()
    parsed = js_parse_int(text)
    if parsed is None or (isinstance(parsed, float) and parsed != parsed):
        return TuneValue(name, None, ValueSource.MISSING, origin, raw, "unparseable")
    return TuneValue(name, int(parsed), ValueSource.PARSED, origin, raw, "")


def _enum_tv(name: str, raw: Any, origin: str, table: Mapping[str, int]) -> TuneValue:
    if raw is None:
        return _missing(name)
    if isinstance(raw, int):
        return TuneValue(name, raw, ValueSource.PARSED, origin, raw, "")
    key = str(raw).strip()
    if key in table:
        return TuneValue(name, table[key], ValueSource.PARSED, origin, raw, "")
    upper = key.upper()
    if upper in table:
        return TuneValue(name, table[upper], ValueSource.PARSED, origin, raw, "")
    parsed = js_parse_int(key)
    if parsed is not None and parsed == parsed:
        return TuneValue(name, int(parsed), ValueSource.PARSED, origin, raw, "")
    return TuneValue(name, None, ValueSource.MISSING, origin, raw, "unparseable")


def _first_present(cfg: Mapping[str, Any], keys: tuple[str, ...]) -> tuple[str, Any] | None:
    lower = {str(k).lower(): (k, v) for k, v in cfg.items()}
    for key in keys:
        hit = lower.get(key.lower())
        if hit is not None:
            return hit[0], hit[1]
    return None


@dataclass(frozen=True)
class AbsoluteAxis:
    p: TuneValue
    i: TuneValue
    d: TuneValue
    f: TuneValue
    d_max: TuneValue

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k).to_dict() for k in ("p", "i", "d", "f", "d_max")}

    def missing_fields(self) -> tuple[str, ...]:
        return tuple(n for n in ("p", "i", "d", "f", "d_max") if not getattr(self, n).present)


@dataclass(frozen=True)
class AbsoluteFilters:
    lpf1_dyn_min_hz: TuneValue
    lpf1_dyn_max_hz: TuneValue
    lpf1_static_hz: TuneValue
    lpf2_static_hz: TuneValue

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k).to_dict() for k in ("lpf1_dyn_min_hz", "lpf1_dyn_max_hz", "lpf1_static_hz", "lpf2_static_hz")}

    def as_filter_set_or_none(self) -> FilterSet | None:
        vals = []
        for n in ("lpf1_dyn_min_hz", "lpf1_dyn_max_hz", "lpf1_static_hz", "lpf2_static_hz"):
            tv = getattr(self, n)
            if not tv.present or tv.value is None:
                return None
            vals.append(int(tv.value))
        return FilterSet(*vals)


@dataclass(frozen=True)
class AbsoluteTune:
    """Current (or proposed) absolute PID/filter snapshot. Missing stays missing."""

    sliders: SimplifiedSliders
    roll: AbsoluteAxis
    pitch: AbsoluteAxis
    yaw: AbsoluteAxis
    dterm: AbsoluteFilters
    gyro: AbsoluteFilters
    active_pid_profile: TuneValue
    current_tune: CurrentTune | None
    warnings: tuple[str, ...] = ()
    sources_used: tuple[str, ...] = ()

    def axis(self, name: str) -> AbsoluteAxis:
        return {"roll": self.roll, "pitch": self.pitch, "yaw": self.yaw}[name]

    def to_pid_profile(self) -> PidProfileState | None:
        axes: list[AxisPid] = []
        for name in AXES:
            ax = self.axis(name)
            if ax.missing_fields():
                return None
            axes.append(AxisPid(int(ax.p.value), int(ax.i.value), int(ax.d.value), int(ax.f.value), int(ax.d_max.value)))
        dterm = self.dterm.as_filter_set_or_none()
        if dterm is None:
            return None
        return PidProfileState(axes[0], axes[1], axes[2], dterm, self.sliders)

    def to_gyro(self) -> GyroConfigState | None:
        filt = self.gyro.as_filter_set_or_none()
        if filt is None:
            return None
        return GyroConfigState(filt, self.sliders)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sliders": self.sliders.to_dict(),
            "roll": self.roll.to_dict(),
            "pitch": self.pitch.to_dict(),
            "yaw": self.yaw.to_dict(),
            "dterm": self.dterm.to_dict(),
            "gyro": self.gyro.to_dict(),
            "active_pid_profile": self.active_pid_profile.to_dict(),
            "warnings": list(self.warnings),
            "sources_used": list(self.sources_used),
        }


def _tv_or_missing(tv: TuneValue | None, name: str, component: str) -> TuneValue:
    if tv is None or not tv.present or tv.value is None:
        return _missing(f"{name}.{component}", "not in BBL header or CLI")
    raw = tv.value
    if isinstance(raw, tuple) and len(raw) >= {"p": 1, "i": 2, "d": 3}[component]:
        idx = {"p": 0, "i": 1, "d": 2}[component]
        return TuneValue(f"{name}.{component}", int(raw[idx]), tv.source, tv.origin, tv.raw, tv.note)
    return _missing(f"{name}.{component}", "not in BBL header or CLI")


def _pick_header_or_cli(
    header_cfg: Mapping[str, Any],
    cli_cfg: Mapping[str, Any],
    keys: tuple[str, ...],
    name: str,
    *,
    enum: Mapping[str, int] | None = None,
) -> TuneValue:
    h = _first_present(header_cfg, keys)
    c = _first_present(cli_cfg, keys)
    parse = (lambda raw, origin: _enum_tv(name, raw, origin, enum)) if enum else (lambda raw, origin: _int_tv(name, raw, origin))
    htv = parse(h[1], f"bbl_header:{h[0]}") if h else None
    ctv = parse(c[1], f"cli:{c[0]}") if c else None
    if htv is not None and htv.present:
        return htv
    if ctv is not None and ctv.present:
        return ctv
    return htv or ctv or _missing(name)


def extract_absolute_tune(
    *,
    headers: bytes | str | Mapping[str, Any] | None = None,
    cli_dump: str | None = None,
    log_index: int = 0,
    current_tune: CurrentTune | None = None,
) -> AbsoluteTune:
    """Build the current absolute PID/filter baseline. Missing values stay missing."""
    tune = current_tune if current_tune is not None else extract_current_tune(
        headers=headers, cli_dump=cli_dump, log_index=log_index
    )
    header_cfg: dict[str, Any] = dict(header_pairs(headers, log_index=log_index)) if headers is not None else {}
    cli_cfg: dict[str, Any] = {}
    warnings = list(tune.warnings)
    if cli_dump is not None and str(cli_dump).strip():
        blocks = parse_cli_profile_blocks(str(cli_dump))
        cli_cfg = dict(blocks.get("active_profile_config") or {})
        rate = dict(blocks.get("active_rateprofile_config") or {})
        for k, v in rate.items():
            cli_cfg.setdefault(k, v)
        warnings += [
            f"cli:{w}"
            for w in (blocks.get("warnings") or [])
            if "ambiguous" in w and f"cli:{w}" not in warnings
        ]

    extra: dict[str, TuneValue] = {}
    for field_name, keys in _EXTRA_SLIDER_KEYS:
        extra[field_name] = _pick_header_or_cli(header_cfg, cli_cfg, keys, field_name)
    extra["gyro_filter"] = _pick_header_or_cli(header_cfg, cli_cfg, _GYRO_FILTER_ON, "gyro_filter", enum=_ON_OFF)
    extra["dterm_filter"] = tune.simplified_dterm_filter if tune.simplified_dterm_filter.present else _pick_header_or_cli(
        header_cfg, cli_cfg, _DTERM_FILTER_ON, "dterm_filter", enum=_ON_OFF
    )

    def slider_int(name: str) -> int | None:
        tv = tune.sliders.get(name)
        if tv is not None and tv.present and tv.value is not None:
            try:
                return int(tv.value)
            except (TypeError, ValueError):
                return None
        return None

    def extra_int(name: str) -> int | None:
        tv = extra[name]
        return int(tv.value) if tv.present and tv.value is not None else None

    sliders = SimplifiedSliders(
        pids_mode=int(tune.simplified_pids_mode.value) if tune.simplified_pids_mode.present else None,
        master_multiplier=slider_int("master_multiplier"),
        i_gain=slider_int("i_gain"),
        d_gain=slider_int("d_gain"),
        pi_gain=slider_int("pi_gain"),
        d_max_gain=extra_int("d_max_gain"),
        feedforward_gain=slider_int("feedforward_gain"),
        pitch_d_gain=extra_int("pitch_d_gain"),
        pitch_pi_gain=extra_int("pitch_pi_gain"),
        dterm_filter=int(tune.simplified_dterm_filter.value) if tune.simplified_dterm_filter.present else extra_int("dterm_filter"),
        dterm_filter_multiplier=slider_int("dterm_filter_multiplier"),
        gyro_filter=extra_int("gyro_filter"),
        gyro_filter_multiplier=extra_int("gyro_filter_multiplier"),
    )

    axes: dict[str, AbsoluteAxis] = {}
    for name in AXES:
        pid_tv = tune.pids.get(name)
        axes[name] = AbsoluteAxis(
            p=_tv_or_missing(pid_tv, name, "p") if pid_tv and pid_tv.present else _pick_header_or_cli(header_cfg, cli_cfg, _PID_KEYS[name]["p"], f"{name}.p"),
            i=_tv_or_missing(pid_tv, name, "i") if pid_tv and pid_tv.present else _pick_header_or_cli(header_cfg, cli_cfg, _PID_KEYS[name]["i"], f"{name}.i"),
            d=_tv_or_missing(pid_tv, name, "d") if pid_tv and pid_tv.present else _pick_header_or_cli(header_cfg, cli_cfg, _PID_KEYS[name]["d"], f"{name}.d"),
            f=_pick_header_or_cli(header_cfg, cli_cfg, _FF_KEYS[name], f"{name}.f"),
            d_max=_pick_header_or_cli(header_cfg, cli_cfg, _DMAX_KEYS[name], f"{name}.d_max"),
        )

    dterm = AbsoluteFilters(**{py: _pick_header_or_cli(header_cfg, cli_cfg, (cli,), f"dterm.{py}") for py, cli in _DTERM_KEYS})
    gyro = AbsoluteFilters(**{py: _pick_header_or_cli(header_cfg, cli_cfg, (cli,), f"gyro.{py}") for py, cli in _GYRO_KEYS})
    for n in sliders.missing_for_pids() + sliders.missing_for_dterm() + sliders.missing_for_gyro():
        warnings.append(f"slider_missing:{n}")
    return AbsoluteTune(
        sliders=sliders,
        roll=axes["roll"],
        pitch=axes["pitch"],
        yaw=axes["yaw"],
        dterm=dterm,
        gyro=gyro,
        active_pid_profile=tune.active_pid_profile,
        current_tune=tune,
        warnings=tuple(dict.fromkeys(warnings)),
        sources_used=tune.sources_used,
    )


def _axis_from_pid(name: str, pid: AxisPid) -> AbsoluteAxis:
    def tv(comp: str, value: int) -> TuneValue:
        return TuneValue(f"{name}.{comp}", value, ValueSource.INFERRED, "firmware:applySimplifiedTuning", value, "mapped from sliders")

    return AbsoluteAxis(tv("p", pid.p), tv("i", pid.i), tv("d", pid.d), tv("f", pid.f), tv("d_max", pid.d_max))


def _filters_from_set(prefix: str, filt: FilterSet) -> AbsoluteFilters:
    def tv(comp: str, value: int) -> TuneValue:
        return TuneValue(f"{prefix}.{comp}", value, ValueSource.INFERRED, "firmware:applySimplifiedTuning", value, "mapped from sliders")

    return AbsoluteFilters(
        tv("lpf1_dyn_min_hz", filt.lpf1_dyn_min_hz),
        tv("lpf1_dyn_max_hz", filt.lpf1_dyn_max_hz),
        tv("lpf1_static_hz", filt.lpf1_static_hz),
        tv("lpf2_static_hz", filt.lpf2_static_hz),
    )


def _int_or_none(tv: TuneValue) -> int | None:
    return int(tv.value) if tv.present and tv.value is not None else None


def _delta(current: TuneValue, proposed: TuneValue) -> dict[str, Any] | None:
    if not current.present or not proposed.present:
        return None
    return {"current": current.value, "proposed": proposed.value, "delta": proposed.value - current.value}


def _validity_for(tune: AbsoluteTune) -> SliderValidity:
    skipped: list[str] = []
    profile = tune.to_pid_profile()
    gyro = tune.to_gyro()
    if profile is None:
        skipped.append("current_pid_or_dterm_incomplete")
    if gyro is None:
        skipped.append("current_gyro_incomplete")
    if profile is None or gyro is None:
        dummy_profile = profile
        dummy_gyro = gyro
        if dummy_profile is not None and dummy_gyro is None:
            dummy_gyro = GyroConfigState(FilterSet(0, 0, 0, 0), tune.sliders)
            result = validate_simplified_tuning(dummy_profile, dummy_gyro)
            return SliderValidity(
                result.pids_valid,
                False,
                result.dterm_valid,
                result.pid_mismatches,
                (),
                result.dterm_mismatches,
                tuple(skipped) + result.skipped_reasons,
            )
        if dummy_gyro is not None and dummy_profile is None:
            dummy_profile = PidProfileState(
                AxisPid(0, 0, 0, 0, 0),
                AxisPid(0, 0, 0, 0, 0),
                AxisPid(0, 0, 0, 0, 0),
                FilterSet(0, 0, 0, 0),
                tune.sliders,
            )
            result = validate_simplified_tuning(dummy_profile, dummy_gyro)
            return SliderValidity(
                False,
                result.gyro_valid,
                False,
                (),
                result.gyro_mismatches,
                (),
                tuple(skipped) + result.skipped_reasons,
            )
        return SliderValidity(False, False, False, (), (), (), tuple(skipped))
    result = validate_simplified_tuning(profile, gyro)
    if skipped:
        return replace(result, skipped_reasons=result.skipped_reasons + tuple(skipped))
    return result


def _placeholder_filters(current: AbsoluteFilters) -> FilterSet:
    """Firmware skip-if-zero: missing Hz must not become a default; treat as 0 (leave unscaled)."""
    return FilterSet(
        _int_or_none(current.lpf1_dyn_min_hz) or 0,
        _int_or_none(current.lpf1_dyn_max_hz) or 0,
        _int_or_none(current.lpf1_static_hz) or 0,
        _int_or_none(current.lpf2_static_hz) or 0,
    )


@dataclass(frozen=True)
class AbsoluteTuneProposal:
    """Non-actionable global tune proposal. There is deliberately no CLI/MSP method."""

    status: str
    current: AbsoluteTune
    merge: GlobalSliderMerge
    per_axis_recommendations: dict[str, dict[str, int] | None]
    proposed: AbsoluteTune | None
    current_validity: SliderValidity
    proposed_validity: SliderValidity | None
    deltas: dict[str, Any]
    warnings: tuple[str, ...] = ()
    blocked_reasons: tuple[str, ...] = ()
    review_reasons: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)

    kind: str = PROPOSAL_KIND
    actionable: bool = field(default=False, init=False)
    required_downstream_stages: tuple[str, ...] = field(default=REQUIRED_DOWNSTREAM_STAGES, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status,
            "actionable": False,
            "non_actionable_notice": NON_ACTIONABLE_NOTICE,
            "required_downstream_stages": list(self.required_downstream_stages),
            "current_global_sliders": self.current.sliders.to_dict(),
            "per_axis_wu8_recommendations": self.per_axis_recommendations,
            "merged_global_sliders": self.merge.proposed_sliders,
            "merge": self.merge.to_dict(),
            "current_absolute": self.current.to_dict(),
            "proposed_absolute": self.proposed.to_dict() if self.proposed else None,
            "deltas": self.deltas,
            "slider_validity": {
                "current": self.current_validity.to_dict(),
                "proposed": self.proposed_validity.to_dict() if self.proposed_validity else None,
            },
            "warnings": list(self.warnings),
            "blocked_reasons": list(self.blocked_reasons),
            "review_reasons": list(self.review_reasons),
            "provenance": dict(self.provenance),
        }


def propose_absolute_tune(
    recommendation: AutotuneRecommendationResult,
    *,
    headers: bytes | str | Mapping[str, Any] | None = None,
    cli_dump: str | None = None,
) -> AbsoluteTuneProposal:
    """WU8 recommendations → merge → firmware mapping. Never actionable."""
    current = extract_absolute_tune(
        headers=headers,
        cli_dump=cli_dump,
        current_tune=recommendation.current_tune,
    )
    merge = merge_autotune_sliders(recommendation.axes, current.sliders)
    per_axis = {rec.axis_name: rec.proposed_sliders_unvalidated for rec in recommendation.axes.values()}
    warnings = list(current.warnings) + list(recommendation.warnings)
    blocked = list(recommendation.blocked_reasons)
    current_validity = _validity_for(current)
    provenance = {
        "firmware": dict(FIRMWARE_PROVENANCE),
        "autotune": dict(recommendation.provenance),
        "merge_policy": merge.policy_id,
        "merge_kind": merge.policy_kind,
    }

    if merge.status == MERGE_REQUIRES_REVIEW:
        return AbsoluteTuneProposal(
            status=MERGE_REQUIRES_REVIEW,
            current=current,
            merge=merge,
            per_axis_recommendations=per_axis,
            proposed=None,
            current_validity=current_validity,
            proposed_validity=None,
            deltas={},
            warnings=tuple(dict.fromkeys(warnings)),
            blocked_reasons=tuple(dict.fromkeys(blocked)),
            review_reasons=merge.review_reasons,
            provenance=provenance,
        )

    merged_sliders = merge.simplified
    assert merged_sliders is not None
    mapping_block: list[str] = []
    if merged_sliders.pids_mode == PID_SIMPLIFIED_TUNING_OFF:
        mapping_block.append("simplified_pids_mode_off")
    if merged_sliders.missing_for_pids():
        mapping_block.append("proposed_pid_sliders_incomplete:" + ",".join(merged_sliders.missing_for_pids()))
    if merged_sliders.missing_for_dterm():
        mapping_block.append("proposed_dterm_sliders_incomplete:" + ",".join(merged_sliders.missing_for_dterm()))
    cli_out = sliders_outside_cli_range(merged_sliders)
    if cli_out:
        warnings.append("proposed_sliders_outside_cli_minmax:" + ",".join(cli_out))

    if mapping_block:
        return AbsoluteTuneProposal(
            status="blocked",
            current=current,
            merge=merge,
            per_axis_recommendations=per_axis,
            proposed=None,
            current_validity=current_validity,
            proposed_validity=None,
            deltas={},
            warnings=tuple(dict.fromkeys(warnings)),
            blocked_reasons=tuple(dict.fromkeys(blocked + mapping_block)),
            provenance=provenance,
        )

    seed_dterm = _placeholder_filters(current.dterm)
    seed_gyro = _placeholder_filters(current.gyro)
    if current.dterm.as_filter_set_or_none() is None:
        warnings.append("proposed_dterm_hz_from_present_or_zero_missing_not_defaulted")
    if current.gyro.as_filter_set_or_none() is None:
        warnings.append("proposed_gyro_hz_from_present_or_zero_missing_not_defaulted")

    seed_profile = PidProfileState(
        AxisPid(0, 0, 0, 0, 0),
        AxisPid(0, 0, 0, 0, 0),
        AxisPid(0, 0, 0, 0, 0),
        seed_dterm,
        merged_sliders,
    )
    seed_gyro_state = GyroConfigState(seed_gyro, merged_sliders)
    mapped_profile, mapped_gyro = apply_simplified_tuning(seed_profile, seed_gyro_state)
    proposed = AbsoluteTune(
        sliders=merged_sliders,
        roll=_axis_from_pid("roll", mapped_profile.roll),
        pitch=_axis_from_pid("pitch", mapped_profile.pitch),
        yaw=_axis_from_pid("yaw", mapped_profile.yaw),
        dterm=_filters_from_set("dterm", mapped_profile.dterm),
        gyro=_filters_from_set("gyro", mapped_gyro.filters),
        active_pid_profile=current.active_pid_profile,
        current_tune=current.current_tune,
        warnings=(),
        sources_used=("firmware_simplified_tuning",) + current.sources_used,
    )
    proposed_validity = validate_simplified_tuning(mapped_profile, mapped_gyro)
    deltas: dict[str, Any] = {}
    for name in AXES:
        cur_ax, prop_ax = current.axis(name), proposed.axis(name)
        for comp in ("p", "i", "d", "f", "d_max"):
            item = _delta(getattr(cur_ax, comp), getattr(prop_ax, comp))
            if item:
                deltas[f"{name}.{comp}"] = item
    for prefix, cur_f, prop_f in (("dterm", current.dterm, proposed.dterm), ("gyro", current.gyro, proposed.gyro)):
        for comp in ("lpf1_dyn_min_hz", "lpf1_dyn_max_hz", "lpf1_static_hz", "lpf2_static_hz"):
            item = _delta(getattr(cur_f, comp), getattr(prop_f, comp))
            if item:
                deltas[f"{prefix}.{comp}"] = item

    if blocked:
        status = "blocked"
    elif warnings or recommendation.status is RecommendationStatus.PROPOSED_WITH_WARNINGS:
        status = "proposed_with_warnings"
    else:
        status = "proposed"
    return AbsoluteTuneProposal(
        status=status,
        current=current,
        merge=merge,
        per_axis_recommendations=per_axis,
        proposed=proposed,
        current_validity=current_validity,
        proposed_validity=proposed_validity,
        deltas=deltas,
        warnings=tuple(dict.fromkeys(warnings)),
        blocked_reasons=tuple(dict.fromkeys(blocked)),
        provenance=provenance,
    )


__all__ = [
    "AbsoluteAxis",
    "AbsoluteFilters",
    "AbsoluteTune",
    "AbsoluteTuneProposal",
    "NON_ACTIONABLE_NOTICE",
    "PROPOSAL_KIND",
    "extract_absolute_tune",
    "propose_absolute_tune",
]
