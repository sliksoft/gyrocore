"""Invoke the existing AeroTuner analysis path as a read-only legacy oracle."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from tests.golden.paths import aerotuner_root, fixture_expected_path, fixture_input_dir
from tests.golden.projection import extract_domain_projection, project_from_run_snapshot
from tests.golden.safety import assert_safety_invariants


ORACLE_ENTRYPOINT = "backend.routes.analyze._build_response"


class LegacyOracleError(RuntimeError):
    pass


def _ensure_ai_disabled() -> None:
    """Force deterministic oracle runs (no OpenRouter / explanation polish)."""
    os.environ.pop("OPENROUTER_API_KEY", None)
    os.environ["GYROCORE_AI_EXPLANATIONS_ENABLED"] = "0"
    os.environ["GYROCORE_AI_PROVIDER"] = "disabled"
    # Keep advisor path from seeing a key even if process env was polluted.
    os.environ["AEROTUNER_BYPASS_ANALYSIS_CACHE"] = "1"


def _ensure_aerotuner_on_path() -> Path:
    root = aerotuner_root()
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    return root


def load_fixture_metadata(fixture_name: str) -> dict[str, Any]:
    path = fixture_input_dir(fixture_name) / "metadata.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixture_options(fixture_name: str) -> dict[str, Any]:
    path = fixture_input_dir(fixture_name) / "options.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_csv_rows(csv_path: Path) -> list[dict[str, Any]]:
    """Load golden CSV rows via AeroTuner's golden_pipeline helper (donor code)."""
    _ensure_aerotuner_on_path()
    from backend.test.validation.golden_pipeline import _load_csv_rows as load_rows

    rows = load_rows(csv_path)
    if not rows:
        raise LegacyOracleError(f"no CSV rows loaded from {csv_path}")
    return rows


def _default_hardware(options: Mapping[str, Any]) -> dict[str, Any]:
    _ensure_aerotuner_on_path()
    from backend.tests.hardware_gate_fixtures import complete_confirmed_hardware_for_gate

    hw_opts = options.get("hardware") if isinstance(options.get("hardware"), dict) else {}
    return complete_confirmed_hardware_for_gate(**hw_opts) if hw_opts else complete_confirmed_hardware_for_gate()


def _tuning_from_cli(cli_text: str | None) -> dict[str, Any]:
    _ensure_aerotuner_on_path()
    from backend.services.tuning_parser import empty_tuning_profile
    from backend.services.tuning_safe_v2 import parse_cli_dump

    if not cli_text or not str(cli_text).strip():
        return empty_tuning_profile()
    parsed = parse_cli_dump(cli_text)
    # parse_cli_dump returns structured baseline pieces; wrap into tuning profile shape.
    profile = empty_tuning_profile()
    if isinstance(parsed, dict):
        if isinstance(parsed.get("filters"), dict):
            profile["filters"] = dict(parsed["filters"])
        if isinstance(parsed.get("pid"), dict):
            profile["pid"] = dict(parsed["pid"])
        if isinstance(parsed.get("meta"), dict):
            profile["meta"] = dict(parsed["meta"])
        profile["cli_dump"] = cli_text
        profile["cli_baseline_config"] = {
            "filters": profile.get("filters") or {},
            "pid": profile.get("pid") or {},
        }
        profile["baseline_source"] = "uploaded_cli_dump_text"
    return profile


def run_legacy_build_response(
    *,
    samples: list[dict[str, Any]],
    cli_text: str | None = None,
    options: Mapping[str, Any] | None = None,
    firmware_meta: Mapping[str, str] | None = None,
    session_id: str = "gyrocore-wu0-oracle",
) -> dict[str, Any]:
    """Call AeroTuner ``_build_response`` with AI disabled."""
    _ensure_ai_disabled()
    _ensure_aerotuner_on_path()
    from backend.routes.analyze import _build_response

    opts = dict(options or {})
    user_inputs = dict(opts.get("user_inputs") or {})
    if "hardware" not in user_inputs:
        user_inputs["hardware"] = _default_hardware(opts)
    if "style" not in user_inputs:
        user_inputs["style"] = opts.get("style", "Freestyle")
    if "goals" not in user_inputs:
        user_inputs["goals"] = opts.get("goals", ["smooth"])

    tuning = _tuning_from_cli(cli_text)
    fw = dict(firmware_meta or opts.get("firmware_meta") or {})
    if not fw:
        fw = {"firmware": "Betaflight 4.5.0"}

    session: dict[str, Any] = {
        "user_inputs": user_inputs,
        "uploaded_cli_dump_text": cli_text if cli_text else None,
        "parsed": {
            "samples": samples,
            "tuning": tuning,
        },
    }
    if cli_text:
        session["uploaded_cli_dump_text"] = cli_text

    response = _build_response(
        session_id=session_id,
        samples=samples,
        raw_samples=samples,
        tuning=tuning,
        user_inputs=user_inputs,
        firmware_meta=fw,
        session=session,
        flight_count=1,
        selected_flight_index=0,
        recommended_flight_index=0,
        flight_selection_mode="auto",
    )
    if not isinstance(response, dict):
        raise LegacyOracleError(f"unexpected response type: {type(response)!r}")
    return response


def run_live_fixture_oracle(fixture_name: str) -> dict[str, Any]:
    """Execute live legacy oracle for a CSV(+optional CLI) fixture and project DOMAIN fields."""
    meta = load_fixture_metadata(fixture_name)
    if meta.get("oracle_mode") != "live_legacy":
        raise LegacyOracleError(
            f"fixture {fixture_name} is not live_legacy (mode={meta.get('oracle_mode')})"
        )
    if meta.get("real_bbl_status") == "BLOCKED_REAL_BBL_FIXTURE" and meta.get("input_kind") == "bbl":
        raise LegacyOracleError("BLOCKED_REAL_BBL_FIXTURE")

    _ensure_ai_disabled()
    inp = fixture_input_dir(fixture_name)
    options = load_fixture_options(fixture_name)

    csv_path = inp / "flight.csv"
    if not csv_path.is_file():
        bbl_path = inp / "flight.bbl"
        if bbl_path.is_file():
            raise LegacyOracleError(
                "BBL live decode path not enabled in WU0 harness; "
                "expected flight.csv or blocked BBL status"
            )
        raise LegacyOracleError(f"missing flight.csv for fixture {fixture_name}")

    samples = _load_csv_rows(csv_path)
    cli_path = inp / "cli.txt"
    cli_text = cli_path.read_text(encoding="utf-8") if cli_path.is_file() else None

    response = run_legacy_build_response(
        samples=samples,
        cli_text=cli_text,
        options=options,
        firmware_meta=options.get("firmware_meta"),
        session_id=f"oracle-{fixture_name}",
    )
    projection = extract_domain_projection(
        response,
        ai_disabled=True,
        oracle_entrypoint=ORACLE_ENTRYPOINT,
    )
    assert_safety_invariants(projection, require_full_safety=True)
    return projection


def run_snapshot_fixture_oracle(fixture_name: str) -> dict[str, Any]:
    """Project DOMAIN fields from a frozen run_snapshot (partial; BBL blocked)."""
    meta = load_fixture_metadata(fixture_name)
    if meta.get("oracle_mode") != "snapshot_partial":
        raise LegacyOracleError(
            f"fixture {fixture_name} is not snapshot_partial (mode={meta.get('oracle_mode')})"
        )
    snap_path = fixture_input_dir(fixture_name) / "run_snapshot.json"
    snapshot = json.loads(snap_path.read_text(encoding="utf-8"))
    projection = project_from_run_snapshot(snapshot)
    # Snapshot path is explicitly partial — do not require full live safety.
    assert_safety_invariants(projection, require_full_safety=False)
    return projection


def run_fixture_oracle(fixture_name: str) -> dict[str, Any]:
    meta = load_fixture_metadata(fixture_name)
    mode = meta.get("oracle_mode")
    if mode == "live_legacy":
        return run_live_fixture_oracle(fixture_name)
    if mode == "snapshot_partial":
        return run_snapshot_fixture_oracle(fixture_name)
    raise LegacyOracleError(f"unsupported oracle_mode={mode!r} for {fixture_name}")


def write_expected_golden(fixture_name: str, projection: Mapping[str, Any]) -> Path:
    out = fixture_expected_path(fixture_name)
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(projection, indent=2, sort_keys=True, default=str) + "\n"
    out.write_text(text, encoding="utf-8")
    return out


def load_expected_golden(fixture_name: str) -> dict[str, Any]:
    path = fixture_expected_path(fixture_name)
    if not path.is_file():
        raise FileNotFoundError(
            f"missing frozen golden for {fixture_name}: {path}. "
            "Run: python tools/update_legacy_golden.py"
        )
    return json.loads(path.read_text(encoding="utf-8"))


class NewCoreNotImplemented:
    """Placeholder for future GyroCore Core dual-runner side."""

    status = "NOT_IMPLEMENTED"

    def analyze(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError(
            "GyroCore Core analyze is NOT_IMPLEMENTED in WU0. "
            "Connect the real Core in a later work unit; do not stub it with the legacy oracle."
        )
