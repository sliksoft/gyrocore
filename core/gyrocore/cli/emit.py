"""Deterministic Betaflight CLI text (WU11). No serial/MSP."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from gyrocore.autotune.absolute import AbsoluteTune
from gyrocore.autotune.current_tune import TuneValue
from gyrocore.cli.settings import (
    ALLOWED_CLI_KEYS,
    CANONICAL_SET_ORDER,
    CLI_RANGES,
    DTERM_FILTER_CLI_KEYS,
    GYRO_FILTER_CLI_KEYS,
    PID_CLI_KEYS,
    PID_PROFILE_MAX,
    SAVE_COMMAND,
)
from gyrocore.safety.safe_tune import absolute_tune_to_config

_SET_RE = re.compile(r"^\s*set\s+([a-zA-Z0-9_]+)\s*=\s*(.+?)\s*$", re.IGNORECASE)
_PROFILE_RE = re.compile(r"^\s*profile\s+(\d+)\s*$", re.IGNORECASE)

PREVIEW_BANNER = (
    "# GyroCore CLI PREVIEW — not paste-ready, not authorized, no save. WU11 WARN path."
)


def _tv_int(tv: TuneValue) -> int | None:
    if tv is None or not tv.present or tv.value is None:
        return None
    try:
        return int(tv.value)
    except (TypeError, ValueError):
        return None


def flatten_absolute_tune(tune: AbsoluteTune) -> dict[str, int]:
    """Map an AbsoluteTune onto 2026.6.2 CLI keys. Missing fields are omitted."""
    out: dict[str, int] = {}
    for axis, comp, key in PID_CLI_KEYS:
        ax = tune.axis(axis)
        field = "f" if comp == "ff" else comp
        num = _tv_int(getattr(ax, field))
        if num is not None:
            out[key] = num
    for field, key in GYRO_FILTER_CLI_KEYS:
        num = _tv_int(getattr(tune.gyro, field))
        if num is not None:
            out[key] = num
    for field, key in DTERM_FILTER_CLI_KEYS:
        num = _tv_int(getattr(tune.dterm, field))
        if num is not None:
            out[key] = num
    return out


def required_pid_keys() -> tuple[str, ...]:
    return tuple(key for _a, comp, key in PID_CLI_KEYS if comp != "d_max") + tuple(
        key for _f, key in DTERM_FILTER_CLI_KEYS + GYRO_FILTER_CLI_KEYS
    )


def profile_index(tune: AbsoluteTune) -> int | None:
    raw = _tv_int(tune.active_pid_profile)
    if raw is None:
        return None
    if raw < 0 or raw > PID_PROFILE_MAX:
        return None
    return raw


def diff_settings(current: Mapping[str, int], target: Mapping[str, int]) -> tuple[dict[str, int], dict[str, int], tuple[str, ...]]:
    """Return (changed current→target, unchanged target keys, missing-baseline keys)."""
    changed: dict[str, int] = {}
    unchanged: list[str] = []
    missing: list[str] = []
    for key in CANONICAL_SET_ORDER:
        if key not in target:
            continue
        if key not in current:
            missing.append(key)
            continue
        if int(current[key]) != int(target[key]):
            changed[key] = int(target[key])
        else:
            unchanged.append(key)
    return changed, tuple(unchanged), tuple(missing)


def format_set_line(key: str, value: int) -> str:
    if key not in ALLOWED_CLI_KEYS:
        raise ValueError(f"unsupported_cli_key:{key}")
    lo, hi = CLI_RANGES[key]
    iv = int(value)
    if iv < lo or iv > hi:
        raise ValueError(f"cli_value_out_of_range:{key}={iv}")
    return f"set {key} = {iv}"


def render_cli(
    *,
    profile: int | None,
    settings: Mapping[str, int],
    include_save: bool,
    header_lines: tuple[str, ...] = (),
) -> str:
    lines = list(header_lines)
    if profile is not None:
        if profile < 0 or profile > PID_PROFILE_MAX:
            raise ValueError(f"pid_profile_out_of_range:{profile}")
        lines.append(f"profile {profile}")
    for key in CANONICAL_SET_ORDER:
        if key in settings:
            lines.append(format_set_line(key, int(settings[key])))
    if include_save and (profile is not None or settings):
        lines.append(SAVE_COMMAND)
    return "\n".join(lines) + ("\n" if lines else "")


def bundle_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_authorized_cli(text: str) -> dict[str, Any]:
    """Parse GyroCore-emitted CLI into profile + settings. Ignores comments and save."""
    settings: dict[str, int] = {}
    profile: int | None = None
    saw_save = False
    for raw in str(text or "").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if s.lower() == SAVE_COMMAND:
            saw_save = True
            continue
        pm = _PROFILE_RE.match(s)
        if pm:
            profile = int(pm.group(1))
            continue
        sm = _SET_RE.match(s)
        if not sm:
            continue
        key = sm.group(1).strip().lower()
        if key not in ALLOWED_CLI_KEYS:
            continue
        try:
            settings[key] = int(round(float(sm.group(2).strip())))
        except (TypeError, ValueError):
            continue
    return {"profile": profile, "settings": settings, "save": saw_save}


def overlay_settings(base: Mapping[str, int], cli_text: str) -> dict[str, int]:
    parsed = parse_authorized_cli(cli_text)
    out = {str(k): int(v) for k, v in base.items()}
    out.update(parsed["settings"])
    return out


def tune_config_snapshot(tune: AbsoluteTune) -> dict[str, Any]:
    cfg, missing = absolute_tune_to_config(tune)
    return {"config": cfg, "missing": missing, "flat": flatten_absolute_tune(tune)}


__all__ = [
    "PREVIEW_BANNER",
    "bundle_hash",
    "diff_settings",
    "flatten_absolute_tune",
    "format_set_line",
    "overlay_settings",
    "parse_authorized_cli",
    "profile_index",
    "render_cli",
    "required_pid_keys",
    "tune_config_snapshot",
]
