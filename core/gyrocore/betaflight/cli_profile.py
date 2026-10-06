"""Resolve active Betaflight profile/rateprofile metadata from CLI dumps."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_PROFILE_RE = re.compile(r"^\s*profile\s+(\d+)\s*$", re.IGNORECASE)
_RATEPROFILE_RE = re.compile(r"^\s*rateprofile\s+(\d+)\s*$", re.IGNORECASE)
_SET_NAME_RE = re.compile(r"^\s*set\s+(pid_profile_name|rate_profile_name)\s*=\s*(.+?)\s*$", re.IGNORECASE)
_RESTORE_PROFILE_RE = re.compile(r"restore\s+original\s+profile\s+selection\s*:\s*(\d+)", re.IGNORECASE)
_RESTORE_RATE_RE = re.compile(r"restore\s+original\s+rateprofile\s+selection\s*:\s*(\d+)", re.IGNORECASE)


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _first_int(meta: Mapping[str, Any], keys: tuple[str, ...]) -> int | None:
    for key in keys:
        if key in meta:
            value = _int_or_none(meta.get(key))
            if value is not None:
                return value
    return None


def resolve_cli_profile_context(
    cli_dump: str | None,
    *,
    bbl_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve active profile/rateprofile with confidence and warnings.

    This helper does not alter parsed CLI values. It only reports whether the
    flat parser's "last block wins" behavior looks trustworthy enough.
    """
    text = str(cli_dump or "")
    meta = bbl_metadata if isinstance(bbl_metadata, Mapping) else {}
    profile_blocks: list[int] = []
    rateprofile_blocks: list[int] = []
    names: dict[str, str] = {}
    restore_profile: int | None = None
    restore_rateprofile: int | None = None

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        rp = _RESTORE_PROFILE_RE.search(s)
        if rp:
            restore_profile = _int_or_none(rp.group(1))
        rr = _RESTORE_RATE_RE.search(s)
        if rr:
            restore_rateprofile = _int_or_none(rr.group(1))
        pm = _PROFILE_RE.match(s)
        if pm:
            value = _int_or_none(pm.group(1))
            if value is not None:
                profile_blocks.append(value)
            continue
        rm = _RATEPROFILE_RE.match(s)
        if rm:
            value = _int_or_none(rm.group(1))
            if value is not None:
                rateprofile_blocks.append(value)
            continue
        sm = _SET_NAME_RE.match(s)
        if sm:
            names[sm.group(1).lower()] = sm.group(2).strip().strip('"').strip("'")

    bbl_profile = _first_int(meta, ("active_profile", "pid_profile", "profile"))
    bbl_rateprofile = _first_int(
        meta,
        ("active_rateprofile", "rate_profile", "rateprofile"),
    )
    warnings: list[str] = []

    def _resolve(
        blocks: list[int],
        restore_value: int | None,
        bbl_value: int | None,
        label: str,
    ) -> tuple[int | None, str]:
        if bbl_value is not None:
            if blocks and bbl_value not in blocks:
                warnings.append(f"{label}_bbl_hint_not_in_cli_blocks")
                return bbl_value, "ambiguous"
            return bbl_value, "high"
        if restore_value is not None:
            if blocks and restore_value not in blocks:
                warnings.append(f"{label}_restore_hint_not_in_cli_blocks")
                return restore_value, "ambiguous"
            return restore_value, "high"
        if not blocks:
            warnings.append(f"{label}_unknown")
            return None, "unknown"
        unique = list(dict.fromkeys(blocks))
        if len(unique) == 1:
            return unique[0], "high"
        # Betaflight dump/diff format: all profile blocks are listed in order, and the
        # final "profile N" / "rateprofile N" line at the end is the restore to the active
        # profile. When blocks[-1] also appeared earlier in the sequence, that final line
        # is the restore marker and gives us high confidence.
        if blocks[-1] in blocks[:-1]:
            return blocks[-1], "high"
        warnings.append(f"{label}_ambiguous_last_block_used")
        return blocks[-1], "ambiguous"

    active_profile, profile_conf = _resolve(
        profile_blocks,
        restore_profile,
        bbl_profile,
        "active_profile",
    )
    active_rateprofile, rate_conf = _resolve(
        rateprofile_blocks,
        restore_rateprofile,
        bbl_rateprofile,
        "active_rateprofile",
    )

    return {
        "active_profile": active_profile,
        "active_rateprofile": active_rateprofile,
        "active_profile_confidence": profile_conf,
        "active_rateprofile_confidence": rate_conf,
        "profile_blocks": profile_blocks,
        "rateprofile_blocks": rateprofile_blocks,
        "pid_profile_name": names.get("pid_profile_name"),
        "rate_profile_name": names.get("rate_profile_name"),
        "warnings": list(dict.fromkeys(warnings)),
    }


def parse_cli_profile_blocks(cli_text: str) -> dict[str, Any]:
    """Parse a ``diff all`` CLI dump into per-profile/rateprofile blocks.

    This is an additive helper. The existing :func:`resolve_cli_profile_context`
    and :func:`~gyrocore.betaflight.cli.parse_cli_dump` public APIs are
    unchanged.

    Returns
    -------
    dict with keys:
        global                  – keys that appear before any profile/rateprofile block
        pid_profiles            – {0: dict, 1: dict, 2: dict}  per-profile ``set`` values
        rateprofiles            – {0: dict, 1: dict, 2: dict}  per-rateprofile ``set`` values
        active_pid_profile      – int | None
        active_rateprofile      – int | None
        active_profile_config   – merged global + active pid_profile block (or last-wins)
        active_rateprofile_config – merged global + active rateprofile block
        profile_confidence      – "high" | "ambiguous" | "unknown"
        rateprofile_confidence  – "high" | "ambiguous" | "unknown"
        warnings                – list[str]
    """
    text = str(cli_text or "")
    _SET_RE = re.compile(r"^\s*set\s+(\S+)\s*=\s*(.+?)\s*$", re.IGNORECASE)

    global_block: dict[str, Any] = {}
    pid_profiles: dict[int, dict[str, Any]] = {}
    rateprofiles_blocks: dict[int, dict[str, Any]] = {}

    current_pid: int | None = None
    current_rate: int | None = None
    in_pid_block = False
    in_rate_block = False

    profile_blocks_seen: list[int] = []
    rateprofile_blocks_seen: list[int] = []
    restore_profile: int | None = None
    restore_rateprofile: int | None = None

    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue

        rp = _RESTORE_PROFILE_RE.search(s)
        if rp:
            restore_profile = _int_or_none(rp.group(1))
            continue
        rr = _RESTORE_RATE_RE.search(s)
        if rr:
            restore_rateprofile = _int_or_none(rr.group(1))
            continue

        pm = _PROFILE_RE.match(s)
        if pm:
            pid_num = _int_or_none(pm.group(1))
            if pid_num is not None:
                current_pid = pid_num
                current_rate = None
                in_pid_block = True
                in_rate_block = False
                if pid_num not in profile_blocks_seen:
                    profile_blocks_seen.append(pid_num)
                if pid_num not in pid_profiles:
                    pid_profiles[pid_num] = {}
            continue

        rm = _RATEPROFILE_RE.match(s)
        if rm:
            rate_num = _int_or_none(rm.group(1))
            if rate_num is not None:
                current_rate = rate_num
                current_pid = None
                in_rate_block = True
                in_pid_block = False
                if rate_num not in rateprofile_blocks_seen:
                    rateprofile_blocks_seen.append(rate_num)
                if rate_num not in rateprofiles_blocks:
                    rateprofiles_blocks[rate_num] = {}
            continue

        sm = _SET_RE.match(s)
        if sm:
            key = sm.group(1).lower()
            raw_val: Any = sm.group(2).strip()
            # Attempt numeric coercion
            try:
                if "." in raw_val:
                    raw_val = float(raw_val)
                else:
                    raw_val = int(raw_val)
            except (TypeError, ValueError):
                pass

            if in_pid_block and current_pid is not None:
                pid_profiles.setdefault(current_pid, {})[key] = raw_val
            elif in_rate_block and current_rate is not None:
                rateprofiles_blocks.setdefault(current_rate, {})[key] = raw_val
            else:
                global_block[key] = raw_val

    # Determine active profile using same logic as resolve_cli_profile_context
    profile_ctx = resolve_cli_profile_context(text)
    active_pid = profile_ctx["active_profile"]
    active_rate = profile_ctx["active_rateprofile"]
    profile_conf = profile_ctx["active_profile_confidence"]
    rate_conf = profile_ctx["active_rateprofile_confidence"]
    warnings = list(profile_ctx["warnings"])

    # If no profile blocks found, treat all global as single-profile (pid_profiles[0])
    if not pid_profiles and global_block:
        pid_profiles[0] = {}
        if active_pid is None:
            active_pid = 0
            profile_conf = "high"

    # Build active_profile_config: global merged with active profile block
    if active_pid is not None and active_pid in pid_profiles:
        active_profile_config: dict[str, Any] = {**global_block, **pid_profiles[active_pid]}
    elif active_pid is not None and profile_conf == "ambiguous":
        # Last-wins fallback: same as old behavior
        active_profile_config = dict(global_block)
        if profile_blocks_seen:
            last = profile_blocks_seen[-1]
            active_profile_config.update(pid_profiles.get(last, {}))
        if "profile_isolation_ambiguous_last_wins_used" not in warnings:
            warnings.append("profile_isolation_ambiguous_last_wins_used")
    else:
        active_profile_config = dict(global_block)

    # Build active_rateprofile_config: global merged with active rateprofile block
    if active_rate is not None and active_rate in rateprofiles_blocks:
        active_rateprofile_config: dict[str, Any] = {**global_block, **rateprofiles_blocks[active_rate]}
    else:
        active_rateprofile_config = dict(global_block)

    return {
        "global": global_block,
        "pid_profiles": pid_profiles,
        "rateprofiles": rateprofiles_blocks,
        "active_pid_profile": active_pid,
        "active_rateprofile": active_rate,
        "active_profile_config": active_profile_config,
        "active_rateprofile_config": active_rateprofile_config,
        "profile_confidence": profile_conf,
        "rateprofile_confidence": rate_conf,
        "warnings": warnings,
    }


_BARE_META_LINE_RE = re.compile(
    r"^(board_name|manufacturer_id)\s+\S+\s*$",
    re.IGNORECASE,
)


def parse_cli_baseline_with_profile_isolation(
    cli_text: str,
    *,
    bbl_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Parse CLI into a baseline dict (``parse_cli_dump`` shape) using active profile isolation.

    When the active PID profile is resolved with high confidence, PID values come from that
    profile block merged with global keys—not from inactive profiles or a trailing restore
    marker without ``set`` lines (last-wins bug on standard Betaflight dumps).

    When active rateprofile confidence is high, rate keys from inactive rateprofiles are
    excluded the same way.

    Falls back to flat :func:`~gyrocore.betaflight.cli.parse_cli_dump` last-wins when
    profile blocks are absent or confidence is not high.
    """
    from gyrocore.betaflight.cli import parse_cli_dump

    text = str(cli_text or "").strip()
    if not text:
        return parse_cli_dump(text)

    full = parse_cli_dump(text)
    blocks = parse_cli_profile_blocks(text)
    ctx = resolve_cli_profile_context(text, bbl_metadata=bbl_metadata)

    pid_profiles = blocks.get("pid_profiles") or {}
    rate_profiles = blocks.get("rateprofiles") or {}
    if not pid_profiles and not rate_profiles:
        return full

    profile_conf = str(ctx.get("active_profile_confidence") or "unknown")
    rate_conf = str(ctx.get("active_rateprofile_confidence") or "unknown")
    use_profile = profile_conf == "high" and ctx.get("active_profile") is not None
    use_rate = rate_conf == "high" and ctx.get("active_rateprofile") is not None

    if not use_profile and not use_rate:
        return full

    flat: dict[str, Any] = dict(blocks.get("global") or {})
    if use_profile:
        active_pid = int(ctx["active_profile"])
        flat.update(pid_profiles.get(active_pid) or {})
    if use_rate:
        active_rate = int(ctx["active_rateprofile"])
        flat.update(rate_profiles.get(active_rate) or {})

    header_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and _BARE_META_LINE_RE.match(line.strip())
    ]
    set_lines = [f"set {key} = {value}" for key, value in flat.items()]
    synthetic = "\n".join(header_lines + set_lines)
    isolated = parse_cli_dump(synthetic)

    meta = {**dict(full.get("meta") or {}), **dict(isolated.get("meta") or {})}
    if use_profile:
        meta["pid_profile"] = ctx.get("active_profile")
    if use_rate:
        meta["rate_profile"] = ctx.get("active_rateprofile")
    meta["profile_isolated_baseline"] = True
    meta["baseline_profile_confidence"] = profile_conf
    meta["baseline_rateprofile_confidence"] = rate_conf
    isolated["meta"] = meta
    isolated["_recognized_set_count"] = int(full.get("_recognized_set_count") or 0)
    return isolated


_OBS_PID_AXES = ("roll", "pitch", "yaw")
_OBS_FILTER_KEYS = (
    "dyn_idle_min_rpm",
    "feedforward_boost",
    "feedforward_smooth_factor",
    "feedforward_jitter_factor",
)
_OBS_SNAPSHOT_MAX_LEN = 480


def _pid_axis_snapshot(cfg: Mapping[str, Any]) -> dict[str, int]:
    snap: dict[str, int] = {}
    pid = cfg.get("pid") if isinstance(cfg.get("pid"), Mapping) else {}
    for axis in _OBS_PID_AXES:
        block = pid.get(axis) if isinstance(pid, Mapping) else None
        if not isinstance(block, Mapping):
            continue
        for comp, prefix in (("p", "p"), ("i", "i"), ("d", "d"), ("ff", "f")):
            val = block.get(comp)
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                snap[f"{prefix}_{axis}"] = int(round(float(val)))
    dmin = cfg.get("d_min") if isinstance(cfg.get("d_min"), Mapping) else {}
    for axis in _OBS_PID_AXES:
        val = dmin.get(axis) if isinstance(dmin, Mapping) else None
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            snap[f"d_min_{axis}"] = int(round(float(val)))
    return snap


def _filter_snapshot(cfg: Mapping[str, Any]) -> dict[str, int]:
    snap: dict[str, int] = {}
    filt = cfg.get("filters") if isinstance(cfg.get("filters"), Mapping) else {}
    for fk in _OBS_FILTER_KEYS:
        if fk in filt and isinstance(filt[fk], (int, float)) and not isinstance(filt[fk], bool):
            snap[fk] = int(round(float(filt[fk])))
    return snap


def pid_filter_baseline_key_snapshot(cfg: Mapping[str, Any]) -> dict[str, int]:
    """Top PID / FF / filter keys for baseline observability and regression tests."""
    snap = _pid_axis_snapshot(cfg)
    snap.update(_filter_snapshot(cfg))
    return snap


def _snapshot_to_obs_string(
    snap: Mapping[str, Any],
    *,
    max_len: int = _OBS_SNAPSHOT_MAX_LEN,
) -> str | None:
    if not snap:
        return None
    parts = [f"{k}={v}" for k, v in sorted(snap.items())]
    text = ",".join(parts)
    return text[:max_len] if len(text) > max_len else text


def active_profile_cli_selection_line(
    baseline_cfg: Mapping[str, Any] | None,
) -> str | None:
    """Return ``profile N`` for paste-ready CLI when baseline used profile isolation."""
    if not isinstance(baseline_cfg, Mapping):
        return None
    meta = baseline_cfg.get("meta")
    if not isinstance(meta, Mapping):
        return None
    if not meta.get("profile_isolated_baseline"):
        return None
    raw = meta.get("pid_profile")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        profile_num = int(raw)
    except (TypeError, ValueError):
        return None
    if profile_num < 0:
        return None
    return f"profile {profile_num}"


def build_profile_baseline_observability(
    cli_text: str,
    *,
    isolated_baseline: Mapping[str, Any],
    apply_baseline: Mapping[str, Any] | None = None,
    final_config: Mapping[str, Any] | None = None,
    targets: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Structured baseline-parse fields for tuning/safety observability events."""
    from gyrocore.betaflight.cli import parse_cli_dump

    text = str(cli_text or "")
    ctx = resolve_cli_profile_context(text)
    last_wins = parse_cli_dump(text)
    isolated_snap = pid_filter_baseline_key_snapshot(isolated_baseline)
    isolated_pid_snap = _pid_axis_snapshot(isolated_baseline)
    isolated_filter_snap = _filter_snapshot(isolated_baseline)
    apply_cfg = apply_baseline if apply_baseline is not None else isolated_baseline
    apply_snap = pid_filter_baseline_key_snapshot(apply_cfg)
    apply_pid_snap = _pid_axis_snapshot(apply_cfg)
    apply_filter_snap = _filter_snapshot(apply_cfg)
    last_wins_snap = pid_filter_baseline_key_snapshot(last_wins)

    i_targets_present = False
    dyn_idle_target_present = False
    if isinstance(targets, Mapping):
        tp = targets.get("pid")
        if isinstance(tp, Mapping):
            for axis in ("roll", "pitch", "yaw"):
                ax = tp.get(axis)
                if isinstance(ax, Mapping) and "i" in ax:
                    i_targets_present = True
                    break
        tf = targets.get("filters")
        if isinstance(tf, Mapping) and "dyn_idle_min_rpm" in tf:
            dyn_idle_target_present = True

    top_deltas: dict[str, str] = {}
    if isinstance(final_config, Mapping):
        final_snap = pid_filter_baseline_key_snapshot(final_config)
        for key, final_v in final_snap.items():
            base_v = apply_snap.get(key)
            if base_v is not None and final_v != base_v:
                top_deltas[key] = f"{base_v}->{final_v}"

    meta = (
        isolated_baseline.get("meta")
        if isinstance(isolated_baseline.get("meta"), Mapping)
        else {}
    )
    profile_isolated = bool(meta.get("profile_isolated_baseline"))

    fields: dict[str, Any] = {
        "active_profile": ctx.get("active_profile"),
        "active_rateprofile": ctx.get("active_rateprofile"),
        "baseline_parse_mode": "isolated" if profile_isolated else "last_wins",
        "profile_isolated_baseline_present": profile_isolated,
        "baseline_profile_confidence": meta.get("baseline_profile_confidence")
        or ctx.get("active_profile_confidence"),
        "last_wins_baseline_differs": isolated_snap != last_wins_snap,
        "isolated_baseline_snapshot": _snapshot_to_obs_string(isolated_snap),
        "apply_baseline_snapshot": _snapshot_to_obs_string(apply_snap),
        "isolated_baseline_pid_snapshot": _snapshot_to_obs_string(isolated_pid_snap),
        "apply_baseline_pid_snapshot": _snapshot_to_obs_string(apply_pid_snap),
        "isolated_baseline_filter_snapshot": _snapshot_to_obs_string(isolated_filter_snap),
        "apply_baseline_filter_snapshot": _snapshot_to_obs_string(apply_filter_snap),
        "top_final_deltas": _snapshot_to_obs_string(top_deltas),
        "i_targets_present": i_targets_present,
        "dyn_idle_target_present": dyn_idle_target_present,
    }
    return {k: v for k, v in fields.items() if v is not None}


__all__ = [
    "active_profile_cli_selection_line",
    "build_profile_baseline_observability",
    "parse_cli_baseline_with_profile_isolation",
    "parse_cli_profile_blocks",
    "pid_filter_baseline_key_snapshot",
    "resolve_cli_profile_context",
]
