"""Synthetic desktop demo payloads. Clearly labeled — not real flight logs."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from gyrocore.autotune import (
    AbsoluteTuneProposal,
    AutotuneRecommendationResult,
    AxisRecommendation,
    RecommendationStatus,
    extract_current_tune,
    propose_absolute_tune,
)
from gyrocore.cli import authorize_cli
from gyrocore.cli.emit import flatten_absolute_tune
from gyrocore.safety import SafetyVerdict, run_safety_pipeline

NOMINAL_CLI = """# Betaflight / STM32F7X2 2026.6.2
profile 0
set p_roll = 45
set i_roll = 80
set d_roll = 30
set f_roll = 120
set d_max_roll = 40
set p_pitch = 47
set i_pitch = 84
set d_pitch = 34
set f_pitch = 125
set d_max_pitch = 46
set p_yaw = 45
set i_yaw = 80
set d_yaw = 0
set f_yaw = 120
set d_max_yaw = 0
set dterm_lpf1_dyn_min_hz = 75
set dterm_lpf1_dyn_max_hz = 150
set dterm_lpf1_static_hz = 75
set dterm_lpf2_static_hz = 150
set gyro_lpf1_dyn_min_hz = 250
set gyro_lpf1_dyn_max_hz = 500
set gyro_lpf1_static_hz = 250
set gyro_lpf2_static_hz = 500
set simplified_pids_mode = RPY
set simplified_master_multiplier = 100
set simplified_pi_gain = 100
set simplified_i_gain = 100
set simplified_d_gain = 100
set simplified_d_max_gain = 100
set simplified_feedforward_gain = 100
set simplified_pitch_pi_gain = 100
set simplified_pitch_d_gain = 100
set simplified_dterm_filter = ON
set simplified_dterm_filter_multiplier = 100
set simplified_gyro_filter = ON
set simplified_gyro_filter_multiplier = 100
profile 0
"""

AUTOTUNE_KEYS = (
    "slider_master_multiplier",
    "slider_pi_gain",
    "slider_i_gain",
    "slider_d_gain",
    "slider_feedforward_gain",
    "slider_dterm_filter_multiplier",
)


@dataclass
class _StubGains:
    proposed: dict[str, int]


def _sliders(value: int = 100, **overrides: int) -> dict[str, int]:
    base = {k: value for k in AUTOTUNE_KEYS}
    base.update(overrides)
    return base


def _axis(axis: int, slider_map: dict[str, int] | None, *, blocked: bool = False) -> AxisRecommendation:
    return AxisRecommendation(
        axis=axis,
        status=RecommendationStatus.BLOCKED if blocked else RecommendationStatus.PROPOSED,
        blocked_reasons=("sysid_unusable",) if blocked else (),
        warnings=(),
        system_id=None,
        recommendation=None if blocked else _StubGains(slider_map or {}),
        current_sliders=None,
        sample_rate_hz=None,
        upstream_sample_rate_hz=None,
    )


def _recommendation(
    slider_map: dict[str, int] | None = None,
    *,
    cli: str = NOMINAL_CLI,
    axes_sliders: dict[int, dict[str, int]] | None = None,
    blocked_axis: int | None = None,
) -> AutotuneRecommendationResult:
    if axes_sliders is None:
        s = slider_map or _sliders(100)
        axes_sliders = {0: s, 1: s, 2: s}
    axes = []
    for ax in (0, 1, 2):
        blocked = blocked_axis == ax
        axes.append(_axis(ax, None if blocked else axes_sliders.get(ax, _sliders(100)), blocked=blocked))
    tune = extract_current_tune(cli_dump=cli)
    blocked_reasons = tuple(dict.fromkeys(r for a in axes for r in a.blocked_reasons))
    return AutotuneRecommendationResult(
        status=RecommendationStatus.BLOCKED if blocked_reasons else RecommendationStatus.PROPOSED,
        target_phase_margin_deg=60.0,
        current_tune=tune,
        axes={a.axis: a for a in axes},
        blocked_reasons=blocked_reasons,
        provenance={"demo": True},
    )


def _clean_analysis() -> dict[str, Any]:
    return {
        "ok": True,
        "quality": {"status": "ok", "score": 90},
        "confidence": {"score": 0.92, "label": "high"},
        "problems": {"problems": []},
        "metrics": {"noise": {"value": 90.0, "hf_ratio": 0.05, "level": "LOW"}},
        "motors": {"diagnostics": {"motors": [], "health": 100}},
        "resonance": {"severity": "low"},
        "spectral": {
            "summary": "demo_fft",
            "axes": {
                "roll": {"peaks": [{"hz": 120.0, "magnitude": 0.4}]},
                "pitch": {"peaks": [{"hz": 125.0, "magnitude": 0.35}]},
                "yaw": {"peaks": []},
            },
        },
        "step_response": {"ok": True, "demo": True},
        "d_effectiveness": {"ok": True, "demo": True},
        "erpm": {"ok": True, "demo": True},
        "saturation": {"ok": True, "level": "low"},
        "sample_rate_hz": 2000.0,
        "duration_s": 42.5,
    }


def _chirp_demo(*, available: bool = True) -> dict[str, Any]:
    if not available:
        return {
            "available": False,
            "reason": "no_chirp_segment_detected",
            "magnitude": [],
            "phase": [],
            "coherence": [],
        }
    freqs = [float(x) for x in range(20, 201, 10)]
    return {
        "available": True,
        "axis": "roll",
        "sample_rate_hz": 2000.0,
        "sample_rate_source": "header_logged_rate",
        "header_vs_timestamp": {"agree": True, "warning": None},
        "usable_frequency_hz": {"min": 20.0, "max": 200.0},
        "quality": "ok",
        "segment": {"start_s": 5.0, "end_s": 12.0},
        "magnitude": [{"hz": f, "db": -12.0 - (f / 40.0)} for f in freqs],
        "phase": [{"hz": f, "deg": -30.0 - (f / 5.0)} for f in freqs],
        "coherence": [{"hz": f, "value": max(0.2, 0.95 - f / 400.0)} for f in freqs],
        "warnings": [],
    }


def _axis_values(tune: Any) -> dict[str, dict[str, int | None]]:
    out: dict[str, dict[str, int | None]] = {}
    for name in ("roll", "pitch", "yaw"):
        ax = getattr(tune, name)
        out[name] = {
            "p": int(ax.p.value) if ax.p.present else None,
            "i": int(ax.i.value) if ax.i.present else None,
            "d": int(ax.d.value) if ax.d.present else None,
            "d_max": int(ax.d_max.value) if ax.d_max.present else None,
            "ff": int(ax.f.value) if ax.f.present else None,
        }
    return out


def _filters(tune: Any) -> dict[str, int | None]:
    flat = flatten_absolute_tune(tune)
    keys = [
        "gyro_lpf1_dyn_min_hz",
        "gyro_lpf1_dyn_max_hz",
        "gyro_lpf1_static_hz",
        "gyro_lpf2_static_hz",
        "dterm_lpf1_dyn_min_hz",
        "dterm_lpf1_dyn_max_hz",
        "dterm_lpf1_static_hz",
        "dterm_lpf2_static_hz",
    ]
    return {k: flat.get(k) for k in keys}


def build_workspace_payload(
    *,
    scenario: str,
    proposal: AbsoluteTuneProposal,
    analysis: dict[str, Any],
    chirp: dict[str, Any],
    demo: bool = True,
) -> dict[str, Any]:
    final = run_safety_pipeline(proposal, analysis=analysis)
    auth = authorize_cli(final)
    current = proposal.current
    original = proposal.proposed
    clamped = final.clamped_tune

    cli_section: dict[str, Any]
    if auth.bundle is not None:
        cli_section = {
            "state": "authorized",
            "authorized": True,
            "actionable": True,
            "label": "AUTHORIZED SAFE OUTPUT",
            "apply_cli": auth.bundle.apply_cli,
            "rollback_cli": auth.bundle.rollback_cli,
            "source_profile": auth.bundle.source_profile,
            "target_profile": auth.bundle.target_profile,
            "changed_settings": dict(auth.bundle.changed_settings),
            "bundle_id": auth.bundle.bundle_id,
            "firmware_provenance": dict(auth.bundle.firmware_provenance),
            "safety_provenance": dict(auth.bundle.safety_provenance),
            "warnings": list(auth.bundle.warnings),
        }
    elif auth.preview is not None:
        cli_section = {
            "state": "preview",
            "authorized": False,
            "actionable": False,
            "label": "WARN PREVIEW — NOT PASTE-READY",
            "preview_cli": auth.preview.preview_cli,
            "reasons": list(auth.preview.reasons),
            "changed_settings": dict(auth.preview.changed_settings),
        }
    else:
        denial = auth.denial
        cli_section = {
            "state": "denied",
            "authorized": False,
            "actionable": False,
            "label": "BLOCK — NO APPLY CLI",
            "blocked_reasons": list(denial.blocked_reasons) if denial else [],
            "diagnostic_values": dict(denial.diagnostic_values) if denial else {},
        }

    return {
        "kind": "gyrocore_desktop_workspace",
        "demo": demo,
        "demo_label": "SYNTHETIC / DEMO DATA — not a real flight blackbox" if demo else None,
        "scenario": scenario,
        "overview": {
            "craft": "Demo F7X2" if demo else None,
            "target": "STM32F7X2",
            "betaflight_version": "2026.6.2",
            "pid_profile": int(current.active_pid_profile.value)
            if current.active_pid_profile.present
            else None,
            "log_duration_s": analysis.get("duration_s"),
            "sample_rate_hz": analysis.get("sample_rate_hz"),
            "detected_issues": [
                p.get("type") or p.get("description")
                for p in ((analysis.get("problems") or {}).get("problems") or [])
                if isinstance(p, dict)
            ],
            "mechanical_safety": final.mechanical.status.value.upper(),
            "chirp_detected": bool(chirp.get("available")),
            "tune_recommendation": proposal.status,
            "cli_authorization": cli_section["state"].upper(),
            "final_safety": final.status.value.upper(),
        },
        "analysis": analysis,
        "chirp": chirp,
        "tune": {
            "merge_status": proposal.status,
            "review_reasons": list(proposal.review_reasons),
            "per_axis_recommendations": proposal.per_axis_recommendations,
            "merged_sliders": proposal.merge.proposed_sliders if proposal.merge else {},
            "merge": proposal.merge.to_dict() if proposal.merge else None,
            "current": {
                "axes": _axis_values(current),
                "filters": _filters(current),
                "sliders": current.sliders.to_dict(),
            },
            "wu8_autotune": {
                "note": "Per-axis Autotune slider recommendations (non-actionable)",
                "axes": proposal.per_axis_recommendations,
            },
            "wu9_absolute_proposal": {
                "axes": _axis_values(original) if original else None,
                "filters": _filters(original) if original else None,
                "sliders": original.sliders.to_dict() if original else None,
            },
            "wu10_safe_target": {
                "axes": _axis_values(clamped) if clamped else None,
                "filters": _filters(clamped) if clamped else None,
                "clamp_ids": list(final.candidate.clamp_ids),
                "status": final.status.value.upper(),
            },
        },
        "safety": {
            "mechanical": final.mechanical.to_dict(),
            "safe_tune": final.candidate.to_dict(),
            "tuning_output_safety": final.output_safety.to_dict(),
            "final": {
                "status": final.status.value.upper(),
                "actionable": False,
                "warnings": list(final.warnings),
                "blocked_reasons": list(final.blocked_reasons),
            },
        },
        "compare": {
            "current": {
                "axes": _axis_values(current),
                "filters": _filters(current),
                "flat": flatten_absolute_tune(current),
            },
            "final_safe": {
                "axes": _axis_values(clamped) if clamped else None,
                "filters": _filters(clamped) if clamped else None,
                "flat": flatten_absolute_tune(clamped) if clamped else {},
            },
        },
        "cli": cli_section,
        "blackbox": {
            "viewer": "third_party/betaflight/blackbox-log-viewer",
            "host": "apps/desktop/blackbox-host",
            "filename": f"demo_{scenario}.synthetic",
            "size_bytes": 0,
            "log_count": 1,
            "selected_log_index": 0,
            "fields_hint": [
                "gyroADC[0]",
                "gyroADC[1]",
                "gyroADC[2]",
                "axisP[0]",
                "axisI[0]",
                "axisD[0]",
                "motor[0]",
                "rcCommand[0]",
            ],
        },
        "controls": {
            "fc_apply_button": False,
            "msp": False,
            "serial": False,
            "copy_apply_cli": cli_section.get("authorized") is True,
            "copy_rollback_cli": cli_section.get("authorized") is True,
        },
    }


def run_demo(scenario: str) -> dict[str, Any]:
    scenario = (scenario or "pass").strip().lower()
    if scenario == "pass":
        rec = _recommendation(_sliders(100, slider_pi_gain=108))
        prop = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
        return build_workspace_payload(
            scenario=scenario, proposal=prop, analysis=_clean_analysis(), chirp=_chirp_demo(available=True)
        )
    if scenario == "warn":
        rec = _recommendation(_sliders(100, slider_pi_gain=200))
        prop = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
        return build_workspace_payload(
            scenario=scenario, proposal=prop, analysis=_clean_analysis(), chirp=_chirp_demo(available=True)
        )
    if scenario == "block":
        rec = _recommendation(_sliders(100))
        prop = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
        analysis = {**_clean_analysis(), "ok": False, "message": "no_usable_samples"}
        return build_workspace_payload(
            scenario=scenario, proposal=prop, analysis=analysis, chirp=_chirp_demo(available=False)
        )
    if scenario == "no_chirp":
        rec = _recommendation(_sliders(100, slider_pi_gain=108))
        prop = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
        return build_workspace_payload(
            scenario=scenario, proposal=prop, analysis=_clean_analysis(), chirp=_chirp_demo(available=False)
        )
    if scenario in {"merge", "merge_review"}:
        rec = _recommendation(
            axes_sliders={
                0: _sliders(110),
                1: _sliders(150),
                2: _sliders(100),
            }
        )
        prop = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
        return build_workspace_payload(
            scenario="merge_review", proposal=prop, analysis=_clean_analysis(), chirp=_chirp_demo(available=True)
        )
    if scenario == "no_autotune":
        rec = _recommendation(blocked_axis=0)
        prop = propose_absolute_tune(rec, cli_dump=NOMINAL_CLI)
        return build_workspace_payload(
            scenario=scenario, proposal=prop, analysis=_clean_analysis(), chirp=_chirp_demo(available=False)
        )
    raise ValueError(f"unknown_demo_scenario:{scenario}")


DEMO_SCENARIOS = ("pass", "warn", "block", "no_chirp", "merge_review", "no_autotune")
