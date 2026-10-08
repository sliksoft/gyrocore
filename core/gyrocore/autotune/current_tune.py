"""Current tune / profile state consumed by Betaflight Autotune, with provenance.

Upstream consumers (immutable, ``third_party/betaflight/configurator``):

- ``chirp_bbl_parser.ts`` ``parseHeader``: ``simplified_master_multiplier``,
  ``simplified_pi_gain``, ``simplified_i_gain``, ``simplified_d_gain``,
  ``simplified_feedforward_gain``, ``simplified_dterm_filter_multiplier``
  (``Number.parseInt``, default 100) and ``rollPID`` / ``pitchPID`` / ``yawPID``
  (``split(",").map(Number)``, default ``[0, 0, 0]``)
- ``useAutotune.ts`` ``extractCurrentSliders``: ``(value || 100) / 100`` — the
  only tune input ``recommendGains`` reads; ``0`` and ``NaN`` also become 100
- ``GainRecommendation.vue``: displays ``rollPID`` / ``pitchPID`` / ``yawPID``
  (not used by the math)

Sources, in priority order:

1. the BBL ``H`` header of the analysed log (the tune that produced the
   measured response) — read with :func:`gyrocore.chirp.sysconfig.header_pairs`
2. a CLI ``dump``/``diff`` — read with the WU2 parsers
   (:func:`~gyrocore.betaflight.cli_profile.parse_cli_profile_blocks`,
   :func:`~gyrocore.betaflight.cli_profile.parse_cli_baseline_with_profile_isolation`,
   :func:`~gyrocore.betaflight.cli_profile.resolve_cli_profile_context`)

Every value records whether it was parsed, defaulted, inferred or is missing;
nothing absent is silently replaced. The upstream ``|| 100`` substitution is
available only through :meth:`CurrentTune.upstream_current_sliders` and is
reported per slider.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from gyrocore.betaflight.cli_profile import (
    parse_cli_baseline_with_profile_isolation,
    parse_cli_profile_blocks,
    resolve_cli_profile_context,
)
from gyrocore.chirp.sysconfig import header_pairs, js_parse_int

from .recommend import CurrentSliders

AXES = ("roll", "pitch", "yaw")

SLIDER_HEADER_KEYS: tuple[tuple[str, str], ...] = (
    ("master_multiplier", "simplified_master_multiplier"),
    ("pi_gain", "simplified_pi_gain"),
    ("i_gain", "simplified_i_gain"),
    ("d_gain", "simplified_d_gain"),
    ("feedforward_gain", "simplified_feedforward_gain"),
    ("dterm_filter_multiplier", "simplified_dterm_filter_multiplier"),
)
UPSTREAM_SLIDER_DEFAULT = 100

# Betaflight TUNING_SLIDERS_MODE / ON-OFF lookup tables (cli/settings.c lookupTable*)
SIMPLIFIED_PIDS_MODES = {0: "OFF", 1: "RP", 2: "RPY"}
_PIDS_MODE_BY_NAME = {v: k for k, v in SIMPLIFIED_PIDS_MODES.items()}
_ON_OFF_BY_NAME = {"OFF": 0, "ON": 1}


class ValueSource(str, Enum):
    PARSED = "parsed"
    DEFAULTED = "defaulted"
    INFERRED = "inferred"
    MISSING = "missing"


@dataclass(frozen=True)
class TuneValue:
    name: str
    value: Any
    source: ValueSource
    origin: str
    raw: Any = None
    note: str = ""

    @property
    def present(self) -> bool:
        return self.source in (ValueSource.PARSED, ValueSource.INFERRED)

    def to_dict(self) -> dict[str, Any]:
        value = list(self.value) if isinstance(self.value, tuple) else self.value
        if isinstance(value, float) and not math.isfinite(value):
            value = str(value)
        return {
            "name": self.name,
            "value": value,
            "source": self.source.value,
            "origin": self.origin,
            "raw": self.raw,
            "note": self.note,
        }


def _missing(name: str, note: str = "") -> TuneValue:
    return TuneValue(name, None, ValueSource.MISSING, "none", None, note)


@dataclass(frozen=True)
class CurrentTune:
    """Tune state for Autotune. Slider values are firmware integers (100 = 1.0x)."""

    sliders: dict[str, TuneValue]
    pids: dict[str, TuneValue]
    simplified_pids_mode: TuneValue
    simplified_dterm_filter: TuneValue
    active_pid_profile: TuneValue
    ff_weight: TuneValue = field(default_factory=lambda: _missing("ff_weight"))
    warnings: tuple[str, ...] = ()
    conflicts: tuple[dict[str, Any], ...] = ()
    sources_used: tuple[str, ...] = ()

    # -- upstream view -------------------------------------------------------

    def upstream_slider_value(self, name: str) -> int:
        """``sysConfig.simplified_* || 100`` as ``extractCurrentSliders`` sees it."""
        v = self.sliders[name].value
        if v is None or (isinstance(v, float) and math.isnan(v)) or v == 0:
            return UPSTREAM_SLIDER_DEFAULT
        return int(v)

    def upstream_current_sliders(self) -> CurrentSliders:
        """Exactly ``extractCurrentSliders(sysConfig)`` (defaults and ``|| 100`` applied)."""
        return CurrentSliders(**{name: self.upstream_slider_value(name) / 100 for name, _ in SLIDER_HEADER_KEYS})

    def upstream_slider_inputs(self) -> dict[str, TuneValue]:
        """Slider integers upstream feeds ``recommendGains``; ``|| 100`` substitutions are ``DEFAULTED``."""
        out: dict[str, TuneValue] = {}
        substituted = self.upstream_substitutions()
        for name, _ in SLIDER_HEADER_KEYS:
            tv = self.sliders[name]
            if name in substituted:
                out[name] = TuneValue(
                    name,
                    UPSTREAM_SLIDER_DEFAULT,
                    ValueSource.DEFAULTED,
                    "upstream:useAutotune.extractCurrentSliders(|| 100)",
                    tv.raw,
                    f"current value {substituted[name]}",
                )
            else:
                out[name] = tv
        return out

    def upstream_substitutions(self) -> dict[str, str]:
        """Sliders where upstream would substitute 100, with the reason."""
        out: dict[str, str] = {}
        for name, _ in SLIDER_HEADER_KEYS:
            tv = self.sliders[name]
            if tv.value is None:
                out[name] = "missing"
            elif isinstance(tv.value, float) and math.isnan(tv.value):
                out[name] = "unparseable"
            elif tv.value == 0:
                out[name] = "zero"
        return out

    # -- GyroCore view -------------------------------------------------------

    @property
    def missing_sliders(self) -> tuple[str, ...]:
        return tuple(name for name, _ in SLIDER_HEADER_KEYS if self.sliders[name].source is ValueSource.MISSING)

    @property
    def sliders_complete(self) -> bool:
        return not self.upstream_substitutions()

    def to_dict(self) -> dict[str, Any]:
        return {
            "sliders": {k: v.to_dict() for k, v in self.sliders.items()},
            "pids": {k: v.to_dict() for k, v in self.pids.items()},
            "simplified_pids_mode": self.simplified_pids_mode.to_dict(),
            "simplified_dterm_filter": self.simplified_dterm_filter.to_dict(),
            "active_pid_profile": self.active_pid_profile.to_dict(),
            "ff_weight": self.ff_weight.to_dict(),
            "upstream_current_sliders": self.upstream_current_sliders().to_dict(),
            "upstream_slider_inputs": {k: v.to_dict() for k, v in self.upstream_slider_inputs().items()},
            "upstream_substitutions": self.upstream_substitutions(),
            "sliders_complete": self.sliders_complete,
            "warnings": list(self.warnings),
            "conflicts": list(self.conflicts),
            "sources_used": list(self.sources_used),
        }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _js_number(text: str) -> float:
    """``Number(text)`` for one CSV element (``""`` -> 0, junk -> NaN)."""
    s = str(text).strip()
    if s == "":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return math.nan


def _slider_from_raw(name: str, raw: Any, origin: str) -> TuneValue:
    parsed = js_parse_int(raw)
    if parsed is None:
        return TuneValue(name, math.nan, ValueSource.PARSED, origin, raw, "not an integer (upstream NaN -> 100)")
    return TuneValue(name, parsed, ValueSource.PARSED, origin, raw)


def _mode_from_raw(name: str, raw: Any, origin: str, names: Mapping[str, int]) -> TuneValue:
    text = str(raw).strip().strip('"').upper()
    if text in names:
        return TuneValue(name, names[text], ValueSource.PARSED, origin, raw)
    parsed = js_parse_int(text)
    if parsed is None:
        return TuneValue(name, None, ValueSource.MISSING, origin, raw, "unrecognized value")
    return TuneValue(name, parsed, ValueSource.PARSED, origin, raw)


def _from_headers(source: bytes | str | Mapping[str, Any], log_index: int) -> dict[str, TuneValue]:
    out: dict[str, TuneValue] = {}
    for key, raw in header_pairs(source, log_index=log_index):
        origin = f"bbl_header:{key}"
        for name, header_key in SLIDER_HEADER_KEYS:
            if key == header_key:
                out[f"slider:{name}"] = _slider_from_raw(name, raw, origin)
        if key in ("rollpid", "pitchpid", "yawpid"):
            axis = key[:-3]
            values = tuple(_js_number(p) for p in str(raw).split(","))
            out[f"pid:{axis}"] = TuneValue(axis, values, ValueSource.PARSED, f"bbl_header:{axis}PID", raw, "[P, I, D]")
        elif key == "ff_weight":
            out["ff_weight"] = TuneValue("ff_weight", tuple(_js_number(p) for p in str(raw).split(",")), ValueSource.PARSED, origin, raw)
        elif key == "simplified_pids_mode":
            out["simplified_pids_mode"] = _mode_from_raw(key, raw, origin, _PIDS_MODE_BY_NAME)
        elif key == "simplified_dterm_filter":
            out["simplified_dterm_filter"] = _mode_from_raw(key, raw, origin, _ON_OFF_BY_NAME)
    return out


def _from_cli(cli_dump: str, bbl_metadata: Mapping[str, Any] | None) -> tuple[dict[str, TuneValue], list[str], TuneValue]:
    out: dict[str, TuneValue] = {}
    warnings: list[str] = []
    blocks = parse_cli_profile_blocks(cli_dump)
    ctx = resolve_cli_profile_context(cli_dump, bbl_metadata=bbl_metadata)
    active = blocks.get("active_pid_profile")
    has_profile_blocks = bool(ctx.get("profile_blocks"))
    # parse_cli_profile_blocks reports "high" for a snippet with no profile blocks at all;
    # the context resolver reports "unknown" there, which is the honest answer.
    confidence = str((blocks.get("profile_confidence") if has_profile_blocks else ctx.get("active_profile_confidence")) or "unknown")
    source = ValueSource.PARSED if confidence == "high" else ValueSource.INFERRED
    if confidence != "high":
        warnings.append(f"cli_active_profile_{confidence}")
    if active is not None and has_profile_blocks:
        profile_tv = TuneValue("active_pid_profile", int(active), source, "cli:profile", None, f"confidence={confidence}")
    elif active is not None:
        profile_tv = TuneValue(
            "active_pid_profile", int(active), ValueSource.INFERRED, "cli:no_profile_blocks", None, "single-profile dump assumed"
        )
    else:
        profile_tv = _missing("active_pid_profile", "no profile marker in CLI")
    cfg: Mapping[str, Any] = blocks.get("active_profile_config") or {}
    where = f"cli:profile{active}" if (active is not None and has_profile_blocks) else "cli:global"
    for name, key in SLIDER_HEADER_KEYS:
        if key in cfg:
            tv = _slider_from_raw(name, cfg[key], f"{where}:{key}")
            out[f"slider:{name}"] = TuneValue(tv.name, tv.value, source, tv.origin, tv.raw, tv.note)
    if "simplified_pids_mode" in cfg:
        tv = _mode_from_raw("simplified_pids_mode", cfg["simplified_pids_mode"], f"{where}:simplified_pids_mode", _PIDS_MODE_BY_NAME)
        out["simplified_pids_mode"] = TuneValue(tv.name, tv.value, source if tv.present else tv.source, tv.origin, tv.raw, tv.note)
    if "simplified_dterm_filter" in cfg:
        tv = _mode_from_raw("simplified_dterm_filter", cfg["simplified_dterm_filter"], f"{where}:simplified_dterm_filter", _ON_OFF_BY_NAME)
        out["simplified_dterm_filter"] = TuneValue(tv.name, tv.value, source if tv.present else tv.source, tv.origin, tv.raw, tv.note)
    baseline = parse_cli_baseline_with_profile_isolation(cli_dump, bbl_metadata=bbl_metadata)
    for axis in AXES:
        comp = (baseline.get("pid") or {}).get(axis) or {}
        if all(c in comp for c in ("p", "i", "d")):
            out[f"pid:{axis}"] = TuneValue(
                axis, (float(comp["p"]), float(comp["i"]), float(comp["d"])), source, f"{where}:{axis}_pid", None, "[P, I, D]"
            )
    return out, warnings, profile_tv


def extract_current_tune(
    *,
    headers: bytes | str | Mapping[str, Any] | None = None,
    cli_dump: str | None = None,
    log_index: int = 0,
) -> CurrentTune:
    """Resolve the tune Autotune needs from a BBL header and/or a CLI dump.

    The BBL header wins (it describes the flight that was measured); CLI values
    fill gaps, and any disagreement is reported in ``conflicts``.
    """
    warnings: list[str] = []
    sources: list[str] = []
    hdr = _from_headers(headers, log_index) if headers is not None else {}
    if headers is not None:
        sources.append("bbl_header")
    cli: dict[str, TuneValue] = {}
    profile_tv = _missing("active_pid_profile", "Betaflight BBL headers do not log the PID profile index")
    if cli_dump is not None and str(cli_dump).strip():
        cli, cli_warn, profile_tv = _from_cli(str(cli_dump), None)
        warnings += cli_warn
        sources.append("cli_dump")

    conflicts: list[dict[str, Any]] = []

    def pick(key: str, name: str, note: str) -> TuneValue:
        h, c = hdr.get(key), cli.get(key)
        if h is not None and c is not None and h.value != c.value:
            if not (isinstance(h.value, float) and isinstance(c.value, float) and math.isnan(h.value) and math.isnan(c.value)):
                conflicts.append({"key": key, "bbl_header": h.to_dict()["value"], "cli": c.to_dict()["value"], "used": "bbl_header"})
                warnings.append(f"bbl_cli_mismatch:{key}")
        if h is not None:
            return h
        if c is not None:
            return c
        return _missing(name, note)

    sliders = {name: pick(f"slider:{name}", name, f"no {hk} in BBL header or CLI") for name, hk in SLIDER_HEADER_KEYS}
    pids = {axis: pick(f"pid:{axis}", axis, f"no {axis}PID in BBL header or {axis} PIDs in CLI") for axis in AXES}
    pids_mode = pick("simplified_pids_mode", "simplified_pids_mode", "not logged / not in CLI")
    dterm_mode = pick("simplified_dterm_filter", "simplified_dterm_filter", "not logged / not in CLI")

    for name, _ in SLIDER_HEADER_KEYS:
        if sliders[name].source is ValueSource.MISSING:
            warnings.append(f"slider_missing:{name}")
    return CurrentTune(
        sliders=sliders,
        pids=pids,
        simplified_pids_mode=pids_mode,
        simplified_dterm_filter=dterm_mode,
        active_pid_profile=profile_tv,
        ff_weight=hdr.get("ff_weight") or _missing("ff_weight", "not in BBL header"),
        warnings=tuple(dict.fromkeys(warnings)),
        conflicts=tuple(conflicts),
        sources_used=tuple(sources),
    )


def current_tune_from_sliders(values: Mapping[str, Any], *, origin: str = "caller") -> CurrentTune:
    """Build a :class:`CurrentTune` from explicit slider integers (keys as in ``SLIDER_HEADER_KEYS``)."""
    sliders = {}
    for name, header_key in SLIDER_HEADER_KEYS:
        raw = values.get(name, values.get(header_key))
        sliders[name] = _missing(name, "not supplied") if raw is None else _slider_from_raw(name, raw, f"{origin}:{name}")
    return CurrentTune(
        sliders=sliders,
        pids={axis: _missing(axis, "not supplied") for axis in AXES},
        simplified_pids_mode=_missing("simplified_pids_mode", "not supplied"),
        simplified_dterm_filter=_missing("simplified_dterm_filter", "not supplied"),
        active_pid_profile=_missing("active_pid_profile", "not supplied"),
        sources_used=(origin,),
    )


__all__ = [
    "AXES",
    "CurrentTune",
    "SIMPLIFIED_PIDS_MODES",
    "SLIDER_HEADER_KEYS",
    "TuneValue",
    "UPSTREAM_SLIDER_DEFAULT",
    "ValueSource",
    "current_tune_from_sliders",
    "extract_current_tune",
]
