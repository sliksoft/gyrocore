"""Safe-tune clamp stage (WU10). Consumes AbsoluteTuneProposal + MechanicalSafetyResult."""

from __future__ import annotations

from typing import Any, Mapping

from gyrocore.autotune.absolute import (
    AbsoluteAxis,
    AbsoluteFilters,
    AbsoluteTune,
    AbsoluteTuneProposal,
)
from gyrocore.autotune.current_tune import TuneValue, ValueSource
from gyrocore.autotune.merge import MERGE_REQUIRES_REVIEW
from gyrocore.betaflight.simplified_tuning import AXES
from gyrocore.safety.clamps import (
    DEFAULT_MAX_DELTA,
    apply_safety_autotune,
    apply_thermal_if_needed,
    apply_to_baseline,
    record_numeric_clamps,
    scale_max_delta,
)
from gyrocore.safety.results import MechanicalSafetyResult, SafeTuneCandidate, make_safe_tune_candidate
from gyrocore.safety.types import STAGE_SAFE_TUNE, SafetyCheck, SafetyVerdict, StageBypassError

_FILTER_MAP = (
    ("dterm", "lpf1_dyn_min_hz", "dterm_lpf1_dyn_min_hz"),
    ("dterm", "lpf1_dyn_max_hz", "dterm_lpf1_dyn_max_hz"),
    ("dterm", "lpf1_static_hz", "dterm_lpf1_static_hz"),
    ("dterm", "lpf2_static_hz", "dterm_lpf2_static_hz"),
    ("gyro", "lpf1_dyn_min_hz", "gyro_lpf1_dyn_min_hz"),
    ("gyro", "lpf1_dyn_max_hz", "gyro_lpf1_dyn_max_hz"),
    ("gyro", "lpf1_static_hz", "gyro_lpf1_static_hz"),
    ("gyro", "lpf2_static_hz", "gyro_lpf2_static_hz"),
)

_PID_COMPS = (("p", "p"), ("i", "i"), ("d", "d"), ("f", "ff"), ("d_max", "d_max"))


def _tv_num(tv: TuneValue) -> float | None:
    if tv is None or not tv.present or tv.value is None:
        return None
    try:
        return float(tv.value)
    except (TypeError, ValueError):
        return None


def absolute_tune_to_config(tune: AbsoluteTune) -> tuple[dict[str, Any], tuple[str, ...]]:
    missing: list[str] = []
    pid: dict[str, Any] = {}
    for axis in AXES:
        ax = tune.axis(axis)
        block: dict[str, Any] = {}
        for gc, donor in _PID_COMPS:
            num = _tv_num(getattr(ax, gc))
            if num is None:
                missing.append(f"{axis}.{gc}")
            else:
                block[donor] = num
        pid[axis] = block
    filters: dict[str, Any] = {}
    for prefix, field, donor_key in _FILTER_MAP:
        obj = tune.dterm if prefix == "dterm" else tune.gyro
        num = _tv_num(getattr(obj, field))
        if num is None:
            missing.append(f"{prefix}.{field}")
        else:
            filters[donor_key] = num
    return {"pid": pid, "filters": filters}, tuple(missing)


def _clamped_tv(original: TuneValue, new_val: float) -> TuneValue:
    rounded = int(round(new_val))
    return TuneValue(
        original.name,
        rounded,
        ValueSource.INFERRED,
        "safe_tune_clamp",
        original.raw,
        original.note,
    )


def config_to_absolute_tune(template: AbsoluteTune, config: Mapping[str, Any]) -> AbsoluteTune:
    pid = config.get("pid") if isinstance(config.get("pid"), Mapping) else {}
    filt = config.get("filters") if isinstance(config.get("filters"), Mapping) else {}

    def axis_from(name: str, src: AbsoluteAxis) -> AbsoluteAxis:
        block = pid.get(name) if isinstance(pid.get(name), Mapping) else {}
        vals = {}
        for gc, donor in _PID_COMPS:
            orig = getattr(src, gc)
            if donor in block and isinstance(block[donor], (int, float)):
                vals[gc] = _clamped_tv(orig, float(block[donor]))
            else:
                vals[gc] = orig
        return AbsoluteAxis(vals["p"], vals["i"], vals["d"], vals["f"], vals["d_max"])

    def filters_from(prefix: str, src: AbsoluteFilters) -> AbsoluteFilters:
        mapping = {field: donor for p, field, donor in _FILTER_MAP if p == prefix}

        def pick(field: str) -> TuneValue:
            orig = getattr(src, field)
            donor = mapping[field]
            if donor in filt and isinstance(filt[donor], (int, float)):
                return _clamped_tv(orig, float(filt[donor]))
            return orig

        return AbsoluteFilters(
            pick("lpf1_dyn_min_hz"),
            pick("lpf1_dyn_max_hz"),
            pick("lpf1_static_hz"),
            pick("lpf2_static_hz"),
        )

    return AbsoluteTune(
        sliders=template.sliders,
        roll=axis_from("roll", template.roll),
        pitch=axis_from("pitch", template.pitch),
        yaw=axis_from("yaw", template.yaw),
        dterm=filters_from("dterm", template.dterm),
        gyro=filters_from("gyro", template.gyro),
        active_pid_profile=template.active_pid_profile,
        current_tune=template.current_tune,
        warnings=template.warnings,
        sources_used=template.sources_used + ("safe_tune_clamp",),
    )


def _confidence_score(analysis: Mapping[str, Any] | None) -> float | None:
    if not isinstance(analysis, Mapping):
        return None
    conf = analysis.get("confidence")
    if isinstance(conf, Mapping):
        try:
            return float(conf.get("score"))
        except (TypeError, ValueError):
            return None
    if isinstance(conf, (int, float)) and not isinstance(conf, bool):
        return float(conf)
    return None


def clamp_safe_tune(
    proposal: AbsoluteTuneProposal,
    mechanical: MechanicalSafetyResult,
    *,
    analysis: Mapping[str, Any] | None = None,
    hardware: Mapping[str, Any] | None = None,
) -> SafeTuneCandidate:
    """Apply donor step/hard/thermal clamps. Always non-actionable."""
    if not isinstance(mechanical, MechanicalSafetyResult):
        raise StageBypassError("clamp_safe_tune requires MechanicalSafetyResult")
    if not isinstance(proposal, AbsoluteTuneProposal):
        raise TypeError("clamp_safe_tune requires AbsoluteTuneProposal")

    checks: list[SafetyCheck] = []
    blocked: list[str] = []
    warnings: list[str] = list(proposal.warnings)
    provenance = {
        "stage": STAGE_SAFE_TUNE,
        "donor": [
            "tuning_safe_v2.apply_to_baseline",
            "tuning_safe_v2.apply_safety",
            "tuning_safety_policy.clamp_targets_to_baseline_thermal",
        ],
        "gyrocore_bridges": [
            "d_max_uses_d_step_cap",
            "zero_hz_filter_off_preserved",
            "zero_pid_yaw_d_preserved",
            "firmware_pid_gain_ceilings",
        ],
    }

    current_config, current_missing = absolute_tune_to_config(proposal.current)
    critical_missing = tuple(
        m for m in current_missing if not m.endswith(".d_max")
    )
    # d_max missing is still fail-closed when the proposal wants to change it
    if critical_missing:
        blocked.append("missing_required_pid_or_filter_baseline:" + ",".join(critical_missing))

    proposed_config = None
    if proposal.proposed is not None:
        proposed_config, _ = absolute_tune_to_config(proposal.proposed)
    else:
        blocked.append("malformed_or_empty_proposal")

    if proposal.status == MERGE_REQUIRES_REVIEW or proposal.review_reasons:
        blocked.append("unresolved_merge_requires_review")
    if proposal.status == "blocked" or proposal.blocked_reasons:
        for reason in proposal.blocked_reasons:
            blocked.append(str(reason))
        if "proposal_blocked" not in blocked:
            blocked.append("proposal_blocked")

    if mechanical.status is SafetyVerdict.BLOCK:
        blocked.append("mechanical_hard_block")

    scale = mechanical.max_delta_scale
    max_delta = scale_max_delta(DEFAULT_MAX_DELTA, scale)
    checks.append(
        SafetyCheck(
            rule_id="safe_tune.max_delta_scale",
            verdict=SafetyVerdict.BLOCK if scale <= 0.0 and mechanical.status is SafetyVerdict.BLOCK else SafetyVerdict.PASS,
            message="mechanical max_delta_scale",
            before=1.0,
            after=scale,
        )
    )

    if blocked:
        return make_safe_tune_candidate(
            status=SafetyVerdict.BLOCK,
            proposal=proposal,
            mechanical=mechanical,
            current_config=current_config,
            proposed_config=proposed_config,
            clamped_config=None,
            clamped_tune=None,
            max_delta_used=max_delta,
            clamp_ids=tuple(),
            checks=tuple(checks),
            blocked_reasons=tuple(dict.fromkeys(blocked)),
            warnings=tuple(dict.fromkeys(warnings)),
            provenance=provenance,
        )

    assert proposed_config is not None
    stepped = apply_to_baseline(current_config, proposed_config, max_delta)
    checks.extend(record_numeric_clamps(proposed_config, stepped, rule_prefix="safe_tune.step"))

    conf = _confidence_score(analysis)
    after_safety, safety_ids = apply_safety_autotune(
        stepped,
        hardware=hardware,
        confidence=conf,
        baseline=current_config,
    )
    checks.extend(record_numeric_clamps(stepped, after_safety, rule_prefix="safe_tune.hard"))
    for sid in safety_ids:
        checks.append(
            SafetyCheck(
                rule_id=f"safe_tune.hard.{sid}",
                verdict=SafetyVerdict.WARN,
                message=sid,
            )
        )

    thermal_cfg, thermal_ids = apply_thermal_if_needed(after_safety, current_config, analysis)
    checks.extend(record_numeric_clamps(after_safety, thermal_cfg, rule_prefix="safe_tune.thermal"))
    for tid in thermal_ids:
        checks.append(
            SafetyCheck(
                rule_id=f"safe_tune.thermal.{tid}",
                verdict=SafetyVerdict.WARN,
                message=tid,
            )
        )

    clamp_ids = tuple(
        c.rule_id for c in checks if c.verdict is not SafetyVerdict.PASS and c.before != c.after
    )
    clamped_tune = config_to_absolute_tune(proposal.proposed, thermal_cfg)
    status = SafetyVerdict.WARN if clamp_ids or mechanical.status is SafetyVerdict.WARN else SafetyVerdict.PASS
    if mechanical.status is SafetyVerdict.WARN:
        warnings.append("mechanical_warning_scale_applied")
    return make_safe_tune_candidate(
        status=status,
        proposal=proposal,
        mechanical=mechanical,
        current_config=current_config,
        proposed_config=proposed_config,
        clamped_config=thermal_cfg,
        clamped_tune=clamped_tune,
        max_delta_used=max_delta,
        clamp_ids=clamp_ids,
        checks=tuple(checks),
        blocked_reasons=(),
        warnings=tuple(dict.fromkeys(warnings)),
        provenance=provenance,
    )


__all__ = [
    "absolute_tune_to_config",
    "clamp_safe_tune",
    "config_to_absolute_tune",
]
