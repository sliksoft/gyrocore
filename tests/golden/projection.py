"""Extract parity-relevant DOMAIN fields from a legacy analyze response."""

from __future__ import annotations

from typing import Any, Mapping

from tests.golden.normalize import normalize_cli_text, normalize_string_list


_TRANSPORT_KEYS = frozenset(
    {
        "session_id",
        "job_id",
        "user_id",
        "created_at",
        "updated_at",
        "cache",
        "analysis_cache",
        "pipeline_timings",
        "urls",
        "ownership",
    }
)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _dig(mapping: Mapping[str, Any] | None, *keys: str) -> Any:
    cur: Any = mapping
    for key in keys:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _authoritative_cli(response: Mapping[str, Any]) -> str:
    tuning = _as_dict(response.get("tuning"))
    # Prefer top-level tuning.cli / generated_cli; never decision-engine CLI.
    for key in ("cli", "generated_cli", "cli_text", "paste_ready_cli"):
        if key in tuning and tuning.get(key) not in (None, "", []):
            return normalize_cli_text(tuning.get(key))
    # Some payloads nest under effective / final.
    for nest in ("effective_final_tune", "final_tune", "v2"):
        block = _as_dict(tuning.get(nest))
        for key in ("cli", "generated_cli", "cli_lines"):
            if key in block and block.get(key) not in (None, "", []):
                return normalize_cli_text(block.get(key))
    return ""


def _problem_projection(response: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    problems = response.get("problems")
    rows: list[Any] = []
    if isinstance(problems, Mapping):
        rows = _as_list(problems.get("problems"))
    elif isinstance(problems, list):
        rows = problems
    else:
        tuning = _as_dict(response.get("tuning"))
        rows = _as_list(tuning.get("detected_problems"))

    types: list[str] = []
    severities: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        ptype = str(row.get("type") or row.get("id") or row.get("name") or "").strip()
        if not ptype:
            continue
        types.append(ptype)
        sev = str(row.get("severity") or row.get("level") or "").strip().lower()
        if sev:
            severities[ptype] = sev
    return normalize_string_list(types), severities


def _mechanical_projection(response: Mapping[str, Any]) -> dict[str, Any]:
    safety = _as_dict(response.get("tuning_output_safety"))
    mech = _as_dict(safety.get("mechanical"))
    if not mech:
        mech = _as_dict(response.get("mechanical_safety"))
    return {
        "status": str(
            mech.get("severity")
            or mech.get("recommended_action")
            or mech.get("mechanical_outcome")
            or ""
        ),
        "mechanical_block": bool(mech.get("mechanical_block")),
        "mechanical_limited": bool(mech.get("mechanical_limited")),
        "mechanical_caution": bool(mech.get("mechanical_caution")),
        "mechanical_outcome": str(mech.get("mechanical_outcome") or ""),
        "reasons": normalize_string_list(mech.get("reasons")),
        "blocking_reasons": normalize_string_list(mech.get("blocking_reasons")),
        "limited_reasons": normalize_string_list(mech.get("limited_reasons")),
    }


def _output_safety_projection(response: Mapping[str, Any]) -> dict[str, Any]:
    safety = _as_dict(response.get("tuning_output_safety"))
    return {
        "status": str(safety.get("status") or ""),
        "cli_actionable": bool(safety.get("cli_actionable")) if "cli_actionable" in safety else None,
        "cli_availability": str(safety.get("cli_availability") or ""),
        "blocking_reasons": normalize_string_list(safety.get("blocking_reasons")),
        "hard_block_reasons": normalize_string_list(safety.get("hard_block_reasons")),
        "diagnostic_reasons": normalize_string_list(safety.get("diagnostic_reasons")),
        "reasons": normalize_string_list(safety.get("reasons")),
        "present": bool(safety),
    }


def _tuning_decision_projection(response: Mapping[str, Any]) -> dict[str, Any]:
    decision = _as_dict(response.get("tuning_decision"))
    if not decision:
        decision = _as_dict(response.get("decision"))
    return {
        "mode": str(decision.get("mode") or decision.get("strategy") or ""),
        "status": str(decision.get("status") or ""),
    }


def _pid_filter_summaries(response: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    tuning = _as_dict(response.get("tuning"))
    pid = _as_dict(tuning.get("pid"))
    filters = _as_dict(tuning.get("filters"))
    # Keep compact categorical/numeric summaries only.
    pid_summary = {
        k: pid.get(k)
        for k in sorted(pid.keys())
        if k in {"roll", "pitch", "yaw"} or k.startswith(("p_", "i_", "d_", "f_"))
    }
    filter_summary = {
        k: filters.get(k)
        for k in sorted(filters.keys())
        if any(
            token in k
            for token in (
                "gyro_lpf",
                "dterm_lpf",
                "dyn_notch",
                "rpm_filter",
                "motor_poles",
            )
        )
    }
    return pid_summary, filter_summary


def _metrics_projection(response: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _as_dict(response.get("metrics"))
    if not metrics:
        analysis = _as_dict(response.get("analysis"))
        metrics = _as_dict(analysis.get("metrics"))
    keep_keys = (
        "noise",
        "resonance",
        "propwash",
        "motor",
        "tracking",
        "response",
        "d_effectiveness",
    )
    out: dict[str, Any] = {}
    for key in keep_keys:
        if key in metrics:
            out[key] = metrics.get(key)
    return out


def _resonance_projection(response: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _metrics_projection(response)
    res = _as_dict(metrics.get("resonance"))
    analysis = _as_dict(response.get("analysis"))
    signal = _as_dict(analysis.get("signal"))
    return {
        "dominant_hz": res.get("dominant_hz"),
        "severity": res.get("severity"),
        "resonance_v2_hz": signal.get("resonance_v2_hz") or analysis.get("resonance_v2_hz"),
    }


def _erpm_projection(response: Mapping[str, Any]) -> dict[str, Any]:
    erpm = _as_dict(response.get("erpm_analysis"))
    if not erpm:
        analysis = _as_dict(response.get("analysis"))
        erpm = _as_dict(analysis.get("erpm_analysis"))
    return {
        "dominant_frequency": erpm.get("dominant_frequency"),
        "erpm_sample_coverage": erpm.get("erpm_sample_coverage"),
        "motor_poles": erpm.get("motor_poles"),
        "pole_pairs": erpm.get("pole_pairs"),
        "erpm_scale_assumption": erpm.get("erpm_scale_assumption"),
    }


def _result_view_projection(response: Mapping[str, Any]) -> dict[str, Any]:
    rv = _as_dict(response.get("result_view"))
    hero = _as_dict(rv.get("hero"))
    cards = _as_dict(rv.get("cards"))
    return {
        "hero": {
            "title": str(hero.get("title") or ""),
            "tone": str(hero.get("tone") or ""),
        },
        "card_statuses": {
            name: str(_as_dict(card).get("status") or "")
            for name, card in cards.items()
            if isinstance(card, Mapping)
        },
    }


def _flight_selection(response: Mapping[str, Any]) -> dict[str, Any]:
    meta = _as_dict(response.get("meta"))
    summary = _as_dict(response.get("summary"))
    analysis = _as_dict(response.get("analysis"))
    return {
        "selected_flight_index": (
            meta.get("selected_flight_index")
            if meta.get("selected_flight_index") is not None
            else summary.get("selected_flight_index")
            if summary.get("selected_flight_index") is not None
            else analysis.get("selected_flight_index")
        ),
        "recommended_flight_index": meta.get("recommended_flight_index"),
        "flight_count": meta.get("flight_count") or summary.get("flight_count"),
        "flight_selection_mode": str(
            meta.get("flight_selection_mode") or summary.get("flight_selection_mode") or ""
        ),
        "selected_embedded_log_index": meta.get("selected_embedded_log_index"),
    }


def strip_transport_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Remove known nondeterministic transport/SaaS keys from a shallow mapping."""
    return {k: v for k, v in payload.items() if k not in _TRANSPORT_KEYS}


def extract_domain_projection(
    response: Mapping[str, Any] | None,
    *,
    ai_disabled: bool = True,
    oracle_entrypoint: str = "backend.routes.analyze._build_response",
) -> dict[str, Any]:
    """
    Build the canonical DOMAIN projection used for golden parity.

    Transport/SaaS/AI-prose fields are omitted by design.
    """
    if not isinstance(response, Mapping):
        raise ValueError("legacy response must be a mapping")

    problem_types, problem_severities = _problem_projection(response)
    pid_summary, filter_summary = _pid_filter_summaries(response)
    flight = _flight_selection(response)
    quality_status = str(
        response.get("quality_status")
        or _dig(_as_dict(response.get("quality")), "status")
        or ""
    )
    grade = str(
        response.get("grade")
        or _dig(_as_dict(response.get("summary")), "grade")
        or _dig(_as_dict(response.get("quality")), "grade")
        or ""
    )
    score = response.get("run_score")
    if score is None:
        score = _dig(_as_dict(response.get("summary")), "score")
    if score is None:
        score = response.get("score")

    tuning = _as_dict(response.get("tuning"))
    projection: dict[str, Any] = {
        "schema_version": 1,
        "oracle_entrypoint": oracle_entrypoint,
        "ai_disabled": bool(ai_disabled),
        "analysis_status": str(response.get("status") or ""),
        "valid_log": bool(
            _dig(_as_dict(response.get("summary")), "valid_log")
            if _dig(_as_dict(response.get("summary")), "valid_log") is not None
            else response.get("valid_log")
        )
        if (
            _dig(_as_dict(response.get("summary")), "valid_log") is not None
            or response.get("valid_log") is not None
        )
        else None,
        "selected_flight_index": flight["selected_flight_index"],
        "recommended_flight_index": flight["recommended_flight_index"],
        "selected_embedded_log_index": flight["selected_embedded_log_index"],
        "flight_count": flight["flight_count"],
        "flight_selection_mode": flight["flight_selection_mode"],
        "quality_status": quality_status,
        "quality_grade": grade,
        "quality_score": score,
        "problem_types": problem_types,
        "problem_severities": problem_severities,
        "metrics": _metrics_projection(response),
        "resonance": _resonance_projection(response),
        "erpm": _erpm_projection(response),
        "tuning_mode": str(
            tuning.get("mode")
            or _dig(_as_dict(response.get("strategy")), "mode")
            or ""
        ),
        "pid_summary": pid_summary,
        "filter_summary": filter_summary,
        "mechanical_safety": _mechanical_projection(response),
        "tuning_output_safety": _output_safety_projection(response),
        "authoritative_cli": _authoritative_cli(response),
        "tuning_decision": _tuning_decision_projection(response),
        "result_view": _result_view_projection(response),
    }
    return projection


def project_from_run_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """
    Partial DOMAIN projection from the 75mm whoop run_snapshot.json shape.

    Used when a live BBL is unavailable (BLOCKED_REAL_BBL_FIXTURE). This freezes
    snapshot-derived domain fields only — not a substitute for live oracle BBL runs.
    """
    problems = _as_dict(snapshot.get("analysis_problems"))
    problem_rows = _as_list(problems.get("problems"))
    problem_types = normalize_string_list(
        [
            str(row.get("type") or "")
            for row in problem_rows
            if isinstance(row, Mapping) and row.get("type")
        ]
    )
    severities = {
        str(row.get("type")): str(row.get("severity") or "").lower()
        for row in problem_rows
        if isinstance(row, Mapping) and row.get("type")
    }
    cli = normalize_cli_text(snapshot.get("final_tune_cli"))
    support = _as_dict(snapshot.get("support_matrix_policy_before"))
    return {
        "schema_version": 1,
        "oracle_entrypoint": "run_snapshot.json",
        "ai_disabled": True,
        "analysis_status": "snapshot",
        "valid_log": None,
        "selected_flight_index": None,
        "recommended_flight_index": None,
        "selected_embedded_log_index": None,
        "flight_count": None,
        "flight_selection_mode": "",
        "quality_status": "",
        "quality_grade": "",
        "quality_score": None,
        "problem_types": problem_types,
        "problem_severities": severities,
        "metrics": _as_dict(snapshot.get("analysis_metrics")),
        "resonance": _as_dict(_as_dict(snapshot.get("analysis_metrics")).get("resonance")),
        "erpm": {},
        "tuning_mode": "",
        "pid_summary": _as_dict(_as_dict(snapshot.get("current_tune_baseline")).get("pid")),
        "filter_summary": _as_dict(_as_dict(snapshot.get("current_tune_baseline")).get("filters")),
        "mechanical_safety": {
            "status": "",
            "mechanical_block": False,
            "mechanical_limited": False,
            "mechanical_caution": False,
            "mechanical_outcome": "",
            "reasons": [],
            "blocking_reasons": [],
            "limited_reasons": [],
        },
        "tuning_output_safety": {
            "status": "snapshot_partial",
            "cli_actionable": bool(support.get("paste_ready_eligible"))
            if "paste_ready_eligible" in support
            else False,
            "cli_availability": str(support.get("backend_effective_support_level") or ""),
            "blocking_reasons": normalize_string_list(
                support.get("support_downgrade_reasons")
            ),
            "hard_block_reasons": [],
            "diagnostic_reasons": [],
            "reasons": normalize_string_list(support.get("support_matrix_warnings")),
            "present": True,
            "snapshot_partial": True,
        },
        "authoritative_cli": cli,
        "tuning_decision": {"mode": "", "status": ""},
        "result_view": {"hero": {"title": "", "tone": ""}, "card_statuses": {}},
        "real_bbl_status": "BLOCKED_REAL_BBL_FIXTURE",
        "analysis_noise_level": snapshot.get("analysis_noise_level"),
    }
