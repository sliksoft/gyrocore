"""WU8 units: current-tune provenance, gate policy, non-actionable result model."""

from __future__ import annotations

import ast
import gzip
import inspect
import json
import math
from pathlib import Path

import numpy as np
import pytest

import gyrocore.autotune as autotune
from gyrocore.autotune import (
    NON_ACTIONABLE_NOTICE,
    REQUIRED_DOWNSTREAM_STAGES,
    UPSTREAM_PROVENANCE,
    AutotuneRecommendationResult,
    CurrentSliders,
    RecommendationStatus,
    ValueSource,
    current_tune_from_sliders,
    extract_current_tune,
    recommend_from_system_id,
    recommend_gains,
)
from gyrocore.chirp import identify_chirp_system
from gyrocore.chirp.pipeline import ChirpSystemIdResult
from gyrocore.chirp.sysconfig import header_pairs, parse_chirp_sysconfig
from gyrocore.chirp.system_id import TransferFunction

ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "tests" / "fixtures" / "autotune" / "wu8"
BBL_CASES = {c["case_id"]: c for c in json.loads((FIX / "bbl_cases.json").read_text())["cases"]}
REF = json.loads(gzip.decompress((FIX / "upstream_autotune_reference.json.gz").read_bytes()))

NOMINAL_HEADERS = BBL_CASES["nominal_three_axis"]["headers"]

CLI_DIFF = """# diff all
# Betaflight / STM32F7X2 (S7X2) 4.5.1
profile 0
set p_roll = 40
set i_roll = 70
set d_roll = 28
set simplified_pids_mode = RPY
set simplified_pi_gain = 110
set simplified_d_gain = 90
profile 1
set p_roll = 60
set simplified_pi_gain = 130
set simplified_pids_mode = OFF
# restore original profile selection
profile 0
rateprofile 0
"""


def h_lines(headers: dict[str, str]) -> str:
    return "".join(f"H {k}:{v}\n" for k, v in headers.items())


# ---------------------------------------------------------------------------
# header_pairs refactor (WU7 parse_chirp_sysconfig must be unchanged)
# ---------------------------------------------------------------------------


def test_header_pairs_sources_agree_and_sysconfig_unchanged():
    text = h_lines(NOMINAL_HEADERS)
    from_text = header_pairs(text)
    from_map = header_pairs(NOMINAL_HEADERS)
    assert dict(from_text) == dict(from_map)
    assert dict(from_text)["rollpid"] == "45,80,30"
    assert dict(from_text)["simplified_pi_gain"] == "100"
    a, b = parse_chirp_sysconfig(text), parse_chirp_sysconfig(NOMINAL_HEADERS)
    assert a == b
    assert a.looptime == 250 and a.pid_process_denom == 4


# ---------------------------------------------------------------------------
# Current tune extraction / provenance
# ---------------------------------------------------------------------------


def test_bbl_header_tune_is_parsed_with_origin():
    t = extract_current_tune(headers=h_lines(NOMINAL_HEADERS))
    assert t.sliders_complete and not t.missing_sliders
    for name, tv in t.sliders.items():
        assert tv.source is ValueSource.PARSED and tv.value == 100 and tv.origin.startswith("bbl_header:simplified_")
    assert t.pids["roll"].value == (45.0, 80.0, 30.0) and t.pids["roll"].source is ValueSource.PARSED
    assert t.simplified_pids_mode.value == 2 and t.simplified_dterm_filter.value == 1
    assert t.active_pid_profile.source is ValueSource.MISSING
    assert "PID profile index" in t.active_pid_profile.note
    assert t.upstream_current_sliders() == CurrentSliders(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
    assert all(tv.source is ValueSource.PARSED for tv in t.upstream_slider_inputs().values())


def test_missing_tune_is_not_invented():
    t = extract_current_tune(headers={"looptime": "250"})
    assert set(t.missing_sliders) == {n for n, _ in autotune.SLIDER_HEADER_KEYS}
    assert all(tv.value is None for tv in t.sliders.values())
    assert all(t.pids[a].source is ValueSource.MISSING for a in autotune.AXES)
    assert t.upstream_substitutions() == {n: "missing" for n, _ in autotune.SLIDER_HEADER_KEYS}
    inputs = t.upstream_slider_inputs()
    assert all(tv.source is ValueSource.DEFAULTED and tv.value == 100 for tv in inputs.values())
    assert any(w.startswith("slider_missing:") for w in t.warnings)


def test_zero_and_unparseable_sliders_flagged():
    hdr = dict(NOMINAL_HEADERS, simplified_feedforward_gain="0", simplified_i_gain="abc")
    t = extract_current_tune(headers=hdr)
    assert t.upstream_substitutions() == {"feedforward_gain": "zero", "i_gain": "unparseable"}
    assert math.isnan(t.sliders["i_gain"].value)
    # upstream: (0 || 100) / 100 and (NaN || 100) / 100
    assert t.upstream_current_sliders().feedforward_gain == 1.0
    assert t.upstream_current_sliders().i_gain == 1.0


def test_js_parse_int_semantics_for_sliders():
    hdr = dict(NOMINAL_HEADERS, simplified_pi_gain="120.7", simplified_d_gain=" 85abc")
    t = extract_current_tune(headers=hdr)
    assert t.sliders["pi_gain"].value == 120  # Number.parseInt truncates
    assert t.sliders["d_gain"].value == 85


def test_cli_fallback_uses_wu2_active_profile_isolation():
    t = extract_current_tune(cli_dump=CLI_DIFF)
    assert t.sliders["pi_gain"].value == 110  # profile 0, not profile 1's 130
    assert t.sliders["pi_gain"].origin == "cli:profile0:simplified_pi_gain"
    assert t.sliders["d_gain"].value == 90
    assert t.sliders["i_gain"].source is ValueSource.MISSING  # a diff omits defaults: not invented
    assert t.simplified_pids_mode.value == 2
    assert t.active_pid_profile.value == 0 and t.active_pid_profile.source is ValueSource.PARSED
    assert t.pids["roll"].value == (40.0, 70.0, 28.0)
    assert "cli_dump" in t.sources_used


def test_bbl_header_wins_over_cli_and_conflict_is_reported():
    t = extract_current_tune(headers=NOMINAL_HEADERS, cli_dump=CLI_DIFF)
    assert t.sliders["pi_gain"].value == 100 and t.sliders["pi_gain"].origin.startswith("bbl_header")
    assert any(c["key"] == "slider:pi_gain" and c["cli"] == 110 and c["used"] == "bbl_header" for c in t.conflicts)
    assert "bbl_cli_mismatch:slider:pi_gain" in t.warnings


def test_ambiguous_cli_profile_is_inferred_not_parsed():
    cli = "set simplified_pi_gain = 105\nset simplified_pids_mode = RPY\n"
    t = extract_current_tune(cli_dump=cli)
    assert t.sliders["pi_gain"].value == 105
    assert t.sliders["pi_gain"].source is ValueSource.INFERRED
    assert "cli_active_profile_unknown" in t.warnings
    assert t.active_pid_profile.source is ValueSource.INFERRED

    two_blocks = "profile 0\nset simplified_pi_gain = 105\nprofile 1\nset simplified_pi_gain = 120\n"
    t = extract_current_tune(cli_dump=two_blocks)
    assert t.sliders["pi_gain"].value == 120 and t.sliders["pi_gain"].source is ValueSource.INFERRED
    assert "cli_active_profile_ambiguous" in t.warnings


def test_current_tune_from_sliders():
    t = current_tune_from_sliders({"pi_gain": 120, "simplified_i_gain": 90})
    assert t.sliders["pi_gain"].value == 120 and t.sliders["i_gain"].value == 90
    assert t.sliders["d_gain"].source is ValueSource.MISSING


# ---------------------------------------------------------------------------
# Gate policy on a reference transfer function (no decoder needed)
# ---------------------------------------------------------------------------


def _tf(case_id="nominal") -> TransferFunction:
    c = next(c for c in REF["synthetic"] if c["case_id"] == case_id)
    ut = c["transferFunction"]
    a = lambda k: np.array([float(v) for v in ut[k]])  # noqa: E731
    return TransferFunction(a("frequencies"), a("magnitude"), a("phase"), a("coherence"), a("hReal"), a("hImag"), 0, 0, 0.0)


def test_recommend_gains_rejects_nothing_but_engine_validates_target():
    rec = recommend_gains(_tf(), CurrentSliders(), 60)
    assert rec.proposed["slider_pi_gain"] > 0
    with pytest.raises(ValueError):
        autotune.engine._validate_target(0)
    with pytest.raises(ValueError):
        autotune.engine._validate_target(float("nan"))
    with pytest.raises(ValueError):
        autotune.engine._validate_target(180)


def _fake_system_id(**kw):
    """A WU7 result for an empty log (no CHIRP data) — exercises the global gates."""
    return identify_chirp_system(csv_text="loopIteration,time\n0,0\n1,125\n", headers=h_lines(NOMINAL_HEADERS), **kw)


def test_no_chirp_data_blocks_with_reason():
    sid = _fake_system_id()
    assert isinstance(sid, ChirpSystemIdResult)
    res = recommend_from_system_id(sid, extract_current_tune(headers=NOMINAL_HEADERS))
    assert res.status is RecommendationStatus.BLOCKED
    assert res.blocked_reasons and not res.axes
    assert res.actionable is False


def test_missing_current_tune_blocks():
    res = recommend_from_system_id(_fake_system_id(), None)
    assert "current_tune_missing" in res.blocked_reasons


# ---------------------------------------------------------------------------
# Non-actionable result model
# ---------------------------------------------------------------------------


def test_result_is_structurally_non_actionable():
    fields = {f.name: f for f in AutotuneRecommendationResult.__dataclass_fields__.values()}
    assert fields["actionable"].init is False and fields["actionable"].default is False
    assert fields["required_downstream_stages"].init is False
    assert REQUIRED_DOWNSTREAM_STAGES == ("mechanical_safety", "safe_tune_clamps", "tuning_output_safety", "actionable_cli_or_apply")
    with pytest.raises(TypeError):
        AutotuneRecommendationResult(status=RecommendationStatus.BLOCKED, target_phase_margin_deg=60, current_tune=None, axes={}, actionable=True)
    res = recommend_from_system_id(_fake_system_id(), None)
    d = res.to_dict()
    assert d["actionable"] is False and d["non_actionable_notice"] == NON_ACTIONABLE_NOTICE
    assert d["required_downstream_stages"] == list(REQUIRED_DOWNSTREAM_STAGES)
    json.dumps(d)
    assert "applyGains" in " ".join(UPSTREAM_PROVENANCE["not_ported"])


def test_autotune_package_has_no_apply_msp_or_cli_output_path():
    pkg = Path(autotune.__file__).parent
    forbidden_calls = {"MSP_SET_SIMPLIFIED_TUNING", "MSP_EEPROM_WRITE", "MSP_SET_PID", "sendMsp", "send_msp", "serial", "write_eeprom"}
    for src in pkg.glob("*.py"):
        text = src.read_text()
        tree = ast.parse(text)
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not (names & forbidden_calls), (src.name, names & forbidden_calls)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                s = node.value.lstrip()
                assert not s.startswith("set simplified_"), (src.name, s)
                assert "save\n" not in s
        imports = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imports |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not any(m.split(".")[0] in {"serial", "fastapi", "redis", "sqlalchemy", "aerotuner", "requests"} for m in imports), imports
    public = [n for n in dir(AutotuneRecommendationResult) if not n.startswith("_")]
    assert not [n for n in public if any(w in n.lower() for w in ("apply", "cli", "msp", "write", "paste"))]
    for cls in (autotune.AxisRecommendation,):
        assert not [n for n in dir(cls) if not n.startswith("_") and any(w in n.lower() for w in ("apply", "cli", "msp", "write", "paste"))]
    assert "def apply" not in inspect.getsource(autotune.engine)
