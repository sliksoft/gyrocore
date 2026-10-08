"""WU0/WU10 safety invariants extended for WU11 CLI authorization."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from gyrocore.cli import authorize_cli
from gyrocore.cli.authorize import DENY_WARN_NOT_ACTIONABLE
from gyrocore.safety import SafetyVerdict, StageBypassError
from tests.core.cli.helpers import clean_analysis, pass_with_delta, pipeline, proposal, sliders
from tests.golden.safety import assert_safety_invariants, assert_wu11_cli_invariants

CORE = Path(__file__).resolve().parents[3] / "core" / "gyrocore"


def _projection(final):
    tos = final.output_safety.to_legacy_dict()
    return {
        "ai_disabled": True,
        "tuning_output_safety": {**tos, "present": True},
        "mechanical_safety": final.mechanical.to_legacy_dict(),
        "authoritative_cli": "",
        "decision_engine_cli_authoritative": False,
    }


def test_no_actionable_cli_without_tos_authorization():
    final = pipeline(sliders(100, slider_pi_gain=108))
    assert final.output_safety.cli_actionable is False
    assert final.actionable is False
    auth = authorize_cli(final)
    assert auth.authorized
    assert final.status is SafetyVerdict.PASS
    assert_safety_invariants(_projection(final))
    assert_wu11_cli_invariants(auth.to_dict())
    assert auth.bundle.safety_provenance["tuning_output_safety"]["status"] == "pass"


def test_mechanical_and_clamp_and_final_required():
    final = pass_with_delta()
    auth = authorize_cli(final)
    prov = auth.bundle.safety_provenance
    assert prov["mechanical"]["stage"] == "mechanical_safety"
    assert prov["clamps"]["status"] == "pass"
    assert prov["tuning_output_safety"]["stage"] == "tuning_output_safety"
    assert prov["cli_authorization"] == "authorize_cli"


def test_warn_is_not_actionable_invariant():
    final = pipeline(sliders(100, slider_pi_gain=200))
    assert final.status is SafetyVerdict.WARN
    auth = authorize_cli(final)
    assert auth.authorized is False
    assert DENY_WARN_NOT_ACTIONABLE in auth.preview.reasons
    assert_wu11_cli_invariants(auth.to_dict())


def test_block_exposes_no_actionable_cli():
    final = pipeline(analysis={**clean_analysis(), "ok": False})
    assert final.status is SafetyVerdict.BLOCK
    auth = authorize_cli(final)
    assert auth.bundle is None
    assert "apply_cli" not in auth.denial.to_dict()
    assert_wu11_cli_invariants(auth.to_dict())


def test_missing_state_fails_closed():
    try:
        authorize_cli(None)  # type: ignore[arg-type]
    except StageBypassError:
        pass
    else:
        raise AssertionError("missing final must fail closed")


def test_decision_engine_cli_cannot_become_authoritative():
    final = pass_with_delta()
    auth = authorize_cli(final)
    proj = _projection(final)
    proj["authoritative_cli"] = auth.bundle.apply_cli
    proj["decision_engine_cli_authoritative"] = False
    assert_safety_invariants(proj)
    for path in CORE.rglob("*.py"):
        if "analysis" in path.parts and path.name == "PROVENANCE.txt":
            continue
        text = path.read_text(encoding="utf-8")
        if "decision_engine_cli_authoritative" in text:
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign):
                    blob = ast.dump(node)
                    if "decision_engine_cli_authoritative" in blob and "True" in blob:
                        raise AssertionError(f"{path} assigns decision_engine_cli_authoritative True")


def test_stage_bypass_impossible():
    with pytest.raises(StageBypassError):
        authorize_cli(proposal(sliders(108)))  # type: ignore[arg-type]


def test_rollback_required_for_actionable_bundle():
    auth = authorize_cli(pass_with_delta())
    assert auth.bundle.rollback_cli
    assert_wu11_cli_invariants(auth.to_dict())


def test_public_cli_api_has_no_unauthorized_factory():
    import gyrocore.cli as pkg

    assert hasattr(pkg, "authorize_cli")
    assert "make_actionable_bundle" not in pkg.__all__
    assert not hasattr(pkg, "generate_cli")
