"""Autotune recommendation entry point: system-ID -> gate -> recommendGains -> result.

    ChirpSystemIdResult (WU7, validity-gated)
            |  axis usable?            no -> blocked (system-ID gate codes)
            v
    CurrentTune (BBL header / CLI)
            |  sliders explicit & applicable?   no -> blocked (tune codes)
            v
    recommend_gains (exact upstream port)
            v
    AutotuneRecommendationResult  — NON-ACTIONABLE

The result is the *first* stage of the GyroCore tuning chain. It is never a
flight-controller tune: no MSP, no CLI, no apply path exists here, and every
result states which stages are still required::

    autotune recommendation -> mechanical safety -> safe-tune / clamps
        -> tuning_output_safety -> actionable CLI / apply

Gate policy (``docs/upstream/AUTOTUNE_RECOMMENDATION_PARITY.md`` §6):

- blocking: any failed WU7 blocking gate on the axis; no transfer function;
  system-ID error; a slider missing / unparseable / zero (upstream would
  silently substitute 100); ``simplified_pids_mode`` OFF (sliders do not
  drive the PIDs; upstream's own apply would fail firmware validation); yaw
  while ``simplified_pids_mode`` is RP (sliders do not reach yaw)
- warnings only: WU7 warning gates, upstream outcome flags (target margin
  unreachable / gain held, per-pass clamp, sensitivity bound binding or
  unreachable, slider clamp), GyroCore rate differing from Autotune's rate,
  ``simplified_dterm_filter`` OFF, unknown ``simplified_pids_mode``
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from gyrocore.chirp.extraction import AXIS_NAMES
from gyrocore.chirp.pipeline import ChirpAxisResult, ChirpSystemIdResult, identify_chirp_system
from gyrocore.chirp.sysconfig import read_bbl_header_text

from .current_tune import CurrentTune, extract_current_tune
from .recommend import PHASE_MARGIN_PRESETS, CurrentSliders, GainRecommendation, build_gains, recommend_gains

RECOMMENDATION_KIND = "betaflight_autotune_slider_recommendation"
NON_ACTIONABLE_NOTICE = (
    "Autotune recommendation only. Not a flight-controller tune: it has not passed mechanical safety, "
    "safe-tune clamps or tuning_output_safety, and GyroCore provides no apply/MSP/CLI path for it."
)
REQUIRED_DOWNSTREAM_STAGES = ("mechanical_safety", "safe_tune_clamps", "tuning_output_safety", "actionable_cli_or_apply")
RATE_MATCH_REL_TOL = 1e-9

UPSTREAM_PROVENANCE: dict[str, Any] = {
    "configurator_commit": "a38c4a797a86a580106162653db92af7e14be787",
    "reference_functions": [
        "spectral_analysis.ts:recommendGains",
        "spectral_analysis.ts:extractMetrics",
        "spectral_analysis.ts:computeGainScales",
        "spectral_analysis.ts:buildProposedSliders",
        "spectral_analysis.ts:findOpenLoopCrossover",
        "spectral_analysis.ts:findTargetCrossover",
        "spectral_analysis.ts:peakSensitivityAtGain",
        "spectral_analysis.ts:scanSensitivity",
        "spectral_analysis.ts:robustGain",
        "spectral_analysis.ts:findMaxAchievablePhaseMargin",
        "spectral_analysis.ts:estimateLoopDelayMs",
        "spectral_analysis.ts:findBandwidth",
        "spectral_analysis.ts:findResonantPeak",
        "spectral_analysis.ts:computeLowFreqError",
        "spectral_analysis.ts:findNoiseFloor",
        "spectral_analysis.ts:computeMeanCoherence",
        "spectral_analysis.ts:resonanceBackoffs",
        "spectral_analysis.ts:gainClampLimitOf",
        "spectral_analysis.ts:integralScale",
        "useAutotune.ts:extractCurrentSliders",
        "useAutotune.ts:buildGains",
        "chirp_bbl_parser.ts:parseHeader",
    ],
    "not_ported": ["useAutotune.ts:applyGains", "GainRecommendation.vue:onApply"],
}


class RecommendationStatus(str, Enum):
    PROPOSED = "proposed"
    PROPOSED_WITH_WARNINGS = "proposed_with_warnings"
    BLOCKED = "blocked"


def _num(x: Any) -> Any:
    if isinstance(x, float) and not math.isfinite(x):
        return str(x)
    return x


def _jsonable(d: Mapping[str, Any]) -> dict[str, Any]:
    return {k: _num(v) for k, v in d.items()}


@dataclass(frozen=True)
class AxisRecommendation:
    """One axis. ``proposed_*`` are ``None`` whenever the axis is blocked."""

    axis: int
    status: RecommendationStatus
    blocked_reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    system_id: ChirpAxisResult | None
    recommendation: GainRecommendation | None
    current_sliders: CurrentSliders | None
    sample_rate_hz: float | None
    upstream_sample_rate_hz: float | None

    @property
    def axis_name(self) -> str:
        return AXIS_NAMES[self.axis]

    @property
    def blocked(self) -> bool:
        return self.status is RecommendationStatus.BLOCKED

    @property
    def proposed_sliders_unvalidated(self) -> dict[str, int] | None:
        """Rounded slider integers exactly as upstream ``proposed`` — NOT safe output."""
        if self.blocked or self.recommendation is None:
            return None
        return {k: int(v) for k, v in self.recommendation.proposed.items()}

    @property
    def proposed_raw(self) -> dict[str, dict[str, Any]] | None:
        """Per slider: current, scale, raw ``current*scale*100``, slider clamp, rounded."""
        if self.blocked or self.recommendation is None:
            return None
        return {k: s.to_dict() for k, s in self.recommendation.sliders.items()}

    @property
    def scale_factors(self) -> dict[str, float] | None:
        """Raw (pre per-pass clamp) and final multipliers: P=pi, I=i, D=d, FF=ff, filter."""
        r = self.recommendation
        if r is None:
            return None
        s = r.scales
        return {
            "p_raw": s.robust_pi_scale,
            "p": s.pi_scale,
            "i_raw": s.raw_i_scale,
            "i": s.i_scale,
            "d_raw": s.d_scale,
            "d": s.d_scale,
            "ff_raw": s.raw_ff_scale,
            "ff": s.ff_scale,
            "dterm_filter_raw": s.raw_filter_scale,
            "dterm_filter": s.filter_scale,
        }

    def to_dict(self) -> dict[str, Any]:
        r = self.recommendation
        sid = self.system_id
        out: dict[str, Any] = {
            "axis": self.axis,
            "axis_name": self.axis_name,
            "status": self.status.value,
            "actionable": False,
            "blocked_reasons": list(self.blocked_reasons),
            "warnings": list(self.warnings),
            "sample_rate_hz": self.sample_rate_hz,
            "upstream_autotune_sample_rate_hz": self.upstream_sample_rate_hz,
            "current_sliders_used": self.current_sliders.to_dict() if self.current_sliders else None,
            "proposed_sliders_unvalidated": self.proposed_sliders_unvalidated,
            "proposed_raw": self.proposed_raw,
            "scale_factors": _jsonable(self.scale_factors) if self.scale_factors else None,
            "control_metrics": _jsonable(r.analysis()) if r is not None else None,
            "shaping_terms": _jsonable(r.shaping_terms()) if r is not None else None,
            "quality": sid.quality.to_dict() if sid is not None else None,
        }
        if r is not None and sid is not None:
            sens = sid.sensitivity.peak_db if sid.sensitivity is not None else math.nan
            out["upstream_gains_summary"] = _jsonable({k: v for k, v in build_gains(r, sens, sid.step_response).items() if k != "proposed"})
        return out


@dataclass(frozen=True)
class AutotuneRecommendationResult:
    """Non-actionable Autotune output. There is deliberately no method that yields CLI/MSP."""

    status: RecommendationStatus
    target_phase_margin_deg: float
    current_tune: CurrentTune | None
    axes: dict[int, AxisRecommendation]
    blocked_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    system_id_status: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    kind: str = RECOMMENDATION_KIND
    actionable: bool = field(default=False, init=False)
    required_downstream_stages: tuple[str, ...] = field(default=REQUIRED_DOWNSTREAM_STAGES, init=False)

    def axis(self, axis: int | str) -> AxisRecommendation | None:
        return self.axes.get(AXIS_NAMES.index(axis) if isinstance(axis, str) else axis)

    @property
    def recommended_axes(self) -> tuple[str, ...]:
        return tuple(a.axis_name for a in self.axes.values() if not a.blocked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "status": self.status.value,
            "actionable": False,
            "non_actionable_notice": NON_ACTIONABLE_NOTICE,
            "required_downstream_stages": list(self.required_downstream_stages),
            "target_phase_margin_deg": self.target_phase_margin_deg,
            "system_id_status": self.system_id_status,
            "current_tune": self.current_tune.to_dict() if self.current_tune else None,
            "axes": {AXIS_NAMES[k]: v.to_dict() for k, v in sorted(self.axes.items())},
            "blocked_reasons": list(self.blocked_reasons),
            "warnings": list(self.warnings),
            "provenance": dict(self.provenance),
        }


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


def _tune_gates(tune: CurrentTune, axis: int, allow_upstream_slider_defaults: bool) -> tuple[list[str], list[str]]:
    blocked: list[str] = []
    warnings: list[str] = []
    for name, reason in tune.upstream_substitutions().items():
        code = f"current_tune_{reason}:{name}"
        (warnings if allow_upstream_slider_defaults else blocked).append(code)
    mode = tune.simplified_pids_mode
    if mode.value is None:
        warnings.append("simplified_pids_mode_unknown")
    elif mode.value == 0:
        blocked.append("simplified_pids_mode_off")
    elif mode.value == 1 and axis == 2:
        blocked.append("yaw_not_under_slider_control")
    dterm = tune.simplified_dterm_filter
    if dterm.value is None:
        warnings.append("simplified_dterm_filter_unknown")
    elif dterm.value == 0:
        warnings.append("simplified_dterm_filter_off")
    return blocked, warnings


def _outcome_warnings(rec: GainRecommendation) -> list[str]:
    m, s = rec.metrics, rec.scales
    out: list[str] = []
    if not math.isfinite(m.target_crossover_hz):
        out.append("autotune:target_margin_unreachable_gain_held")
    if not math.isfinite(m.open_loop_crossover_hz):
        out.append("autotune:no_open_loop_crossover")
    if s.gain_clamped:
        out.append(f"autotune:gain_clamped_per_pass:{s.gain_clamp_limit:g}")
    if s.sensitivity_unreachable:
        out.append("autotune:sensitivity_bound_unreachable")
    elif s.sensitivity_binds:
        out.append("autotune:sensitivity_bound_binds")
    for key, sp in rec.sliders.items():
        if sp.clamped_by_slider_limit:
            out.append(f"autotune:slider_clamped:{key}")
    return out


def _rates_match(a: float | None, b: float | None) -> bool:
    return a is not None and b is not None and math.isclose(a, b, rel_tol=RATE_MATCH_REL_TOL)


def _validate_target(target_phase_margin_deg: float) -> float:
    pm = float(target_phase_margin_deg)
    if not math.isfinite(pm) or not 0 < pm < 180:
        raise ValueError(f"target_phase_margin_deg must be finite and in (0, 180): {target_phase_margin_deg!r}")
    return pm


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def recommend_from_system_id(
    system_id: ChirpSystemIdResult,
    current_tune: CurrentTune | None,
    *,
    target_phase_margin_deg: float = PHASE_MARGIN_PRESETS["NORMAL"],
    axes: Sequence[int | str] | None = None,
    allow_upstream_slider_defaults: bool = False,
) -> AutotuneRecommendationResult:
    """Gate a WU7 system-ID result and run the Autotune recommendation per axis.

    ``allow_upstream_slider_defaults`` reproduces upstream's ``|| 100`` slider
    substitution as a *warning* instead of a block (parity studies only).
    """
    pm = _validate_target(target_phase_margin_deg)
    global_blocked: list[str] = []
    global_warnings: list[str] = []
    if system_id.status == "error":
        global_blocked += [f"system_id_error:{e}" for e in system_id.errors] or ["system_id_error"]
    if not system_id.axes and not global_blocked:
        global_blocked.append("no_chirp_axes" if system_id.detected else "no_chirp_segments")
    if current_tune is None:
        global_blocked.append("current_tune_missing")
    else:
        global_warnings += [f"current_tune:{w}" for w in current_tune.warnings]

    wanted = None if axes is None else {AXIS_NAMES.index(a) if isinstance(a, str) else int(a) for a in axes}
    results: dict[int, AxisRecommendation] = {}
    for axis, sid in sorted(system_id.axes.items()):
        if wanted is not None and axis not in wanted:
            continue
        blocked: list[str] = list(global_blocked)
        warnings: list[str] = [f"system_id:{w}" for w in sid.quality.warnings] + list(sid.warnings)
        if sid.transfer_function is None:
            blocked.append("system_id:no_transfer_function")
        blocked += [f"system_id:{code}" for code in sid.quality.failed]
        sliders: CurrentSliders | None = None
        if current_tune is not None:
            tb, tw = _tune_gates(current_tune, axis, allow_upstream_slider_defaults)
            blocked += tb
            warnings += tw
            sliders = current_tune.upstream_current_sliders()
        rate = sid.effective_rate_hz
        if rate is not None and not _rates_match(rate, sid.upstream_sample_rate_hz):
            warnings.append("sample_rate_differs_from_upstream_autotune")

        rec: GainRecommendation | None = None
        system_id_usable = sid.transfer_function is not None and sid.quality.usable and system_id.status != "error"
        if system_id_usable and sliders is not None:
            rec = recommend_gains(sid.transfer_function, sliders, pm, open_loop=sid.open_loop)
            warnings += _outcome_warnings(rec)
        if blocked:
            status = RecommendationStatus.BLOCKED
        elif warnings:
            status = RecommendationStatus.PROPOSED_WITH_WARNINGS
        else:
            status = RecommendationStatus.PROPOSED
        results[axis] = AxisRecommendation(
            axis=axis,
            status=status,
            blocked_reasons=tuple(dict.fromkeys(blocked)),
            warnings=tuple(dict.fromkeys(warnings)),
            system_id=sid,
            recommendation=rec,
            current_sliders=sliders,
            sample_rate_hz=rate,
            upstream_sample_rate_hz=sid.upstream_sample_rate_hz,
        )

    open_axes = [r for r in results.values() if not r.blocked]
    if len({tuple(sorted((r.proposed_sliders_unvalidated or {}).items())) for r in open_axes}) > 1:
        global_warnings.append("per_axis_proposals_differ_sliders_are_global")
    if not results and not global_blocked:
        global_blocked.append("no_axes_selected")
    if global_blocked or not open_axes:
        status = RecommendationStatus.BLOCKED
    elif global_warnings or len(open_axes) < len(results) or any(r.warnings for r in open_axes):
        status = RecommendationStatus.PROPOSED_WITH_WARNINGS
    else:
        status = RecommendationStatus.PROPOSED
    return AutotuneRecommendationResult(
        status=status,
        target_phase_margin_deg=pm,
        current_tune=current_tune,
        axes=results,
        blocked_reasons=tuple(dict.fromkeys(global_blocked)),
        warnings=tuple(dict.fromkeys(global_warnings)),
        system_id_status=system_id.status,
        provenance={**UPSTREAM_PROVENANCE, "system_id": dict(system_id.provenance)},
    )


def recommend_autotune_from_bbl(
    path: str | Path,
    *,
    cli_dump: str | None = None,
    target_phase_margin_deg: float = PHASE_MARGIN_PRESETS["NORMAL"],
    log_index: int | None = None,
    config: Any = None,
    allow_upstream_slider_defaults: bool = False,
    **identify_kwargs: Any,
) -> AutotuneRecommendationResult:
    """BBL -> WU7 system ID -> current tune (same log's header + optional CLI) -> recommendation."""
    from gyrocore.decode import decode_bbl

    decoded = decode_bbl(path, log_index=log_index, config=config)
    index = decoded.decoded_embedded_log_index or 0
    headers = read_bbl_header_text(Path(path).read_bytes(), index)
    system_id = identify_chirp_system(csv_text=decoded.csv_text, headers=headers, log_index=index, **identify_kwargs)
    tune = extract_current_tune(headers=headers, cli_dump=cli_dump)
    return recommend_from_system_id(
        system_id,
        tune,
        target_phase_margin_deg=target_phase_margin_deg,
        allow_upstream_slider_defaults=allow_upstream_slider_defaults,
    )


__all__ = [
    "AutotuneRecommendationResult",
    "AxisRecommendation",
    "NON_ACTIONABLE_NOTICE",
    "RECOMMENDATION_KIND",
    "REQUIRED_DOWNSTREAM_STAGES",
    "RecommendationStatus",
    "UPSTREAM_PROVENANCE",
    "recommend_autotune_from_bbl",
    "recommend_from_system_id",
]
