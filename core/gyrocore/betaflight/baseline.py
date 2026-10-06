"""
Resolve the baseline used for "current tune" deltas (export_display, Advanced Analysis).

Preference:
1. Parsed uploaded Betaflight CLI/diff (session ``uploaded_cli_tune``)
2. ``cli_baseline_config`` from the v2 integration pipeline
3. Blackbox header tuning (``parsed_tuning`` filters) + ``current_pid`` from the package
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

_EXPORT_FILTER_KEYS_BASELINE = (
    "gyro_lpf1_static_hz",
    "gyro_lpf1_dyn_min_hz",
    "gyro_lpf1_dyn_max_hz",
    "gyro_lpf2_static_hz",
    "dterm_lpf1_dyn_min_hz",
    "dterm_lpf1_dyn_max_hz",
    "dterm_lpf2_static_hz",
)


def is_structurally_valid_baseline_slice(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    f = obj.get("filters")
    p = obj.get("pid")
    if isinstance(f, dict) and f:
        return True
    if not isinstance(p, dict) or not p:
        return False
    for ax in ("roll", "pitch", "yaw"):
        blk = p.get(ax)
        if isinstance(blk, dict) and blk:
            return True
    for k in ("p_adjust", "d_adjust", "ff_adjust"):
        if k in p:
            return True
    return False


def _axis_pid_from_current_pid(cur: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {"roll": {}, "pitch": {}, "yaw": {}}
    for ax in ("roll", "pitch", "yaw"):
        blk = cur.get(ax)
        if not isinstance(blk, dict):
            continue
        for comp in ("p", "i", "d", "ff"):
            if comp not in blk:
                continue
            try:
                out[ax][comp] = int(round(float(blk[comp])))
            except (TypeError, ValueError):
                continue
    return out


def _axis_pid_has_any_component(pid: Mapping[str, Any]) -> bool:
    for ax in ("roll", "pitch", "yaw"):
        blk = pid.get(ax)
        if not isinstance(blk, dict):
            continue
        for comp in ("p", "i", "d", "ff"):
            if comp in blk:
                return True
    return False


def _axis_pid_slice_has_any_numeric(ublk: Any) -> bool:
    if not isinstance(ublk, dict):
        return False
    for comp in ("p", "i", "d", "ff"):
        if comp not in ublk:
            continue
        try:
            int(round(float(ublk[comp])))
        except (TypeError, ValueError):
            continue
        return True
    return False


def _merge_upload_pid_with_runtime(
    upload_pid: Mapping[str, Any] | None,
    runtime_pid: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Merge uploaded CLI PID with runtime (header) PID.

    Per axis: if the upload slice lists at least one numeric P/I/D/FF value, only
    those uploaded components are used (missing keys are **not** filled from the
    blackbox header, so e.g. absent ``d_yaw`` in CLI does not inherit an unrelated
    header yaw D). If the upload slice is empty for that axis, the whole axis is
    taken from *runtime_pid* (filters-only CLI + header PIDs).
    """
    up = upload_pid if isinstance(upload_pid, Mapping) else {}
    rt = runtime_pid if isinstance(runtime_pid, Mapping) else {}
    out: dict[str, Any] = {"roll": {}, "pitch": {}, "yaw": {}}
    for ax in ("roll", "pitch", "yaw"):
        ublk = up.get(ax) if isinstance(up.get(ax), Mapping) else {}
        rblk = rt.get(ax) if isinstance(rt.get(ax), Mapping) else {}
        merged: dict[str, int] = {}
        if _axis_pid_slice_has_any_numeric(ublk):
            if isinstance(ublk, dict):
                for comp in ("p", "i", "d", "ff"):
                    if comp not in ublk:
                        continue
                    try:
                        merged[comp] = int(round(float(ublk[comp])))
                    except (TypeError, ValueError):
                        continue
            out[ax] = merged
            continue
        if isinstance(ublk, dict):
            for comp in ("p", "i", "d", "ff"):
                if comp not in ublk:
                    continue
                try:
                    merged[comp] = int(round(float(ublk[comp])))
                except (TypeError, ValueError):
                    continue
        if isinstance(rblk, dict):
            for comp in ("p", "i", "d", "ff"):
                if comp in merged:
                    continue
                if comp not in rblk:
                    continue
                try:
                    merged[comp] = int(round(float(rblk[comp])))
                except (TypeError, ValueError):
                    continue
        out[ax] = merged
    return out


def primary_axis_pid_for_tuning_package(
    session: Mapping[str, Any] | None,
    tuning_profile: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Prefer PID values from an uploaded Betaflight CLI dump; otherwise blackbox header profile.

    Returned dict is suitable for :func:`backend.services.tuning_engine_v2.ensure_pid_complete`.
    """
    sess = session if isinstance(session, dict) else None
    if sess:
        up = sess.get("uploaded_cli_tune")
        if isinstance(up, dict) and str(up.get("source") or "") == "uploaded_cli":
            p = up.get("pid")
            if isinstance(p, dict) and _axis_pid_has_any_component(p):
                return copy.deepcopy(p)
    prof = tuning_profile if isinstance(tuning_profile, dict) else None
    if prof:
        raw = prof.get("pid")
        if isinstance(raw, dict):
            return copy.deepcopy(raw)
    return None


def _filters_from_parsed_headers(parsed_tuning: Mapping[str, Any] | None) -> dict[str, int]:
    if not isinstance(parsed_tuning, dict):
        return {}
    filt = parsed_tuning.get("filters")
    if not isinstance(filt, dict):
        return {}
    out: dict[str, int] = {}
    for key in _EXPORT_FILTER_KEYS_BASELINE:
        if key not in filt:
            continue
        raw = filt[key]
        if raw is None:
            continue
        try:
            out[key] = int(round(float(raw)))
        except (TypeError, ValueError):
            continue
    return out


def effective_current_tune_baseline(
    session: Mapping[str, Any] | None,
    tuning_pkg: Mapping[str, Any],
    parsed_tuning: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], str]:
    """
    Return ``({"filters": dict, "pid": dict}, source_tag)`` for delta comparisons.

    *source_tag*: ``uploaded_cli`` | ``cli_baseline_config`` | ``header_and_current_pid``
    """
    sess = session if isinstance(session, dict) else None

    if sess:
        up = sess.get("uploaded_cli_tune")
        if isinstance(up, dict) and str(up.get("source") or "") == "uploaded_cli":
            f = up.get("filters")
            p = up.get("pid")
            if isinstance(f, dict) and isinstance(p, dict):
                cur = (
                    tuning_pkg.get("current_pid")
                    if isinstance(tuning_pkg, dict)
                    else None
                )
                merged_pid = _merge_upload_pid_with_runtime(
                    p,
                    cur if isinstance(cur, Mapping) else None,
                )
                cand = {"filters": dict(f), "pid": merged_pid}
                if is_structurally_valid_baseline_slice(cand):
                    return cand, "uploaded_cli"

    cli_b = tuning_pkg.get("cli_baseline_config") if isinstance(tuning_pkg, dict) else None
    if isinstance(cli_b, dict):
        f = cli_b.get("filters")
        p = cli_b.get("pid")
        if isinstance(f, dict) and isinstance(p, dict):
            cand = {"filters": dict(f), "pid": copy.deepcopy(p)}
            if is_structurally_valid_baseline_slice(cand):
                return cand, "cli_baseline_config"

    cur = tuning_pkg.get("current_pid") if isinstance(tuning_pkg, dict) else None
    pf = _filters_from_parsed_headers(parsed_tuning)
    pp: dict[str, Any] = {}
    if isinstance(cur, dict):
        pp = _axis_pid_from_current_pid(cur)
    return (
        {"filters": pf, "pid": pp},
        "header_and_current_pid",
    )


_HELD_CURRENT_CONFIG_FILTER_KEYS = (
    "dyn_notch_count",
    "dyn_notch_max_hz",
    "rpm_filter_harmonics",
    "motor_poles",
    "gyro_lpf1_static_hz",
    "gyro_lpf1_dyn_min_hz",
    "gyro_lpf1_dyn_max_hz",
    "gyro_lpf2_static_hz",
    "dterm_lpf1_static_hz",
    "dterm_lpf1_dyn_min_hz",
    "dterm_lpf1_dyn_max_hz",
    "dterm_lpf2_static_hz",
)


def _held_config_scalar(value: Any) -> int | float | str | bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        rounded = float(value)
        if rounded != rounded:
            return None
        if abs(rounded - round(rounded)) < 1e-6:
            return int(round(rounded))
        return rounded
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def build_held_current_config(
    base_filt: Mapping[str, Any] | None,
    final_f: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Unchanged filter keys vs uploaded baseline for Safe CLI held/current display."""
    base = base_filt if isinstance(base_filt, Mapping) else {}
    final = final_f if isinstance(final_f, Mapping) else {}
    held_filters: dict[str, int | float | str | bool] = {}
    for key in _HELD_CURRENT_CONFIG_FILTER_KEYS:
        if key not in base or key not in final:
            continue
        base_v = _held_config_scalar(base.get(key))
        final_v = _held_config_scalar(final.get(key))
        if base_v is None or final_v is None:
            continue
        if base_v == final_v:
            held_filters[key] = final_v
    held_lines = [f"# {key} = {value}" for key, value in sorted(held_filters.items())]
    return {
        "filters": held_filters,
        "lines": held_lines,
        "authority": "uploaded_cli_baseline",
    }
