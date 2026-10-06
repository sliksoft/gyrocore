"""Real-log validation registry for support-claim proof.

This module reads the repo-local validation manifest and returns scoped status
metadata. It never runs tuning logic and never contributes CLI lines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MANIFEST_PATH = REPO_ROOT / "tests/fixtures/real_validation_manifest.json"

REAL_VALIDATION_SOURCES = {"real_bbl", "analyzed_csv", "run_jsonl", "saved_pipeline_output"}
ALLOWED_STATUSES = {"pass", "partial", "fail", "blocked_no_fixtures", "not_run"}
PROOF_READY_PROFILE_STATES = {"resolved", "single_profile"}


def load_real_validation_manifest(path: Path | None = None) -> dict[str, Any]:
    manifest_path = path or DEFAULT_MANIFEST_PATH
    try:
        with manifest_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {
            "validation_status": "blocked_no_fixtures",
            "fixtures": [],
            "blockers": ["real_validation_manifest_missing"],
            "required_fixtures": _required_fixture_list(),
        }
    if not isinstance(data, dict):
        return {
            "validation_status": "blocked_no_fixtures",
            "fixtures": [],
            "blockers": ["real_validation_manifest_invalid"],
            "required_fixtures": _required_fixture_list(),
        }
    return data


def _required_fixture_list() -> list[str]:
    return [
        "At least one sanitized real_bbl or analyzed_csv/run_jsonl fixture for Betaflight 4.5.x",
        "Matching diff-all CLI dump for the same flight/session",
        "Board target and manufacturer metadata when firmware_plus_target proof is claimed",
        "Expected P/D/FF/filter/RPM/CLI/support directions",
        "At least one representative clean/race or non-whoop fixture before broad production full support",
    ]


def _fixture_scope_matches(fixture: dict[str, Any], scope: str | None) -> bool:
    if not scope:
        return True
    firmware_scope = str(fixture.get("firmware_scope") or fixture.get("defaults_profile_used") or "")
    return firmware_scope == scope


def _fixture_paths(fixture: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in (
        "bbl_file",
        "cli_dump_file",
        "cli_dump_path",
        "analyzed_metrics_path",
        "run_jsonl_path",
        "saved_pipeline_output_path",
    ):
        value = fixture.get(key)
        if value:
            paths.append(str(value))
    return paths


def _fixture_expected_support(fixture: dict[str, Any]) -> dict[str, Any]:
    expected = fixture.get("expected_support")
    if isinstance(expected, dict):
        return expected
    expected = fixture.get("expected")
    return expected if isinstance(expected, dict) else {}


def _fixture_status(fixture: dict[str, Any]) -> str:
    status = str(fixture.get("validation_status") or fixture.get("status") or "not_run")
    return status if status in ALLOWED_STATUSES else "not_run"


def _fixture_proof_blockers(fixture: dict[str, Any]) -> list[str]:
    blockers = _as_string_list(fixture.get("blockers"))
    blockers.extend(_as_string_list(fixture.get("failure_reasons")))
    expected = _fixture_expected_support(fixture)
    profile_state = str(
        fixture.get("profile_isolation_expected")
        or expected.get("profile_isolation_expected")
        or expected.get("profile_isolation_status")
        or ""
    )
    if profile_state and profile_state not in PROOF_READY_PROFILE_STATES:
        blockers.append("profile_isolation_not_proof_ready")
    support_proven = expected.get("support_claim_proven")
    if support_proven is False and _fixture_status(fixture) == "pass":
        blockers.append("fixture_expected_support_not_proven")
    return list(dict.fromkeys(str(b) for b in blockers if str(b).strip()))


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if value is None:
        return []
    return [str(value)] if str(value).strip() else []


def resolve_real_log_validation_status(
    effective_config_summary: dict[str, Any] | None = None,
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return scoped real-log validation status for support proof."""
    summary = effective_config_summary if isinstance(effective_config_summary, dict) else {}
    explicit = summary.get("real_log_validation")
    if isinstance(explicit, dict):
        status = str(explicit.get("validation_status") or explicit.get("status") or "not_run")
        if status not in ALLOWED_STATUSES:
            status = "not_run"
        out = dict(explicit)
        out["validation_status"] = status
        out.setdefault("fixture_ids", [])
        out.setdefault("blockers", [] if status in {"pass", "partial"} else [f"real_log_validation_{status}"])
        return out

    data = manifest if isinstance(manifest, dict) else load_real_validation_manifest()
    fixtures = data.get("fixtures") if isinstance(data.get("fixtures"), list) else []
    scope = str(summary.get("defaults_profile_used") or "")
    real_fixtures: list[dict[str, Any]] = []
    synthetic_count = 0
    missing_paths: list[str] = []
    invalid_fixtures: list[str] = []
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            continue
        source_type = str(fixture.get("source_type") or fixture.get("artifact_source") or "")
        if source_type == "synthetic":
            synthetic_count += 1
            continue
        if source_type not in REAL_VALIDATION_SOURCES:
            continue
        if not _fixture_scope_matches(fixture, scope):
            continue
        fixture_id = str(fixture.get("id") or fixture.get("fixture_id") or "unknown_fixture")
        paths = _fixture_paths(fixture)
        if not paths:
            invalid_fixtures.append(fixture_id)
        for path_value in paths:
            candidate = REPO_ROOT / path_value
            if not candidate.exists():
                missing_paths.append(path_value)
        real_fixtures.append(fixture)

    if missing_paths or invalid_fixtures:
        return {
            "validation_status": "fail",
            "scope": scope or None,
            "fixture_ids": [str(f.get("id") or f.get("fixture_id")) for f in real_fixtures],
            "blockers": list(
                dict.fromkeys(
                    (["real_validation_fixture_path_missing"] if missing_paths else [])
                    + (["real_validation_fixture_paths_missing"] if invalid_fixtures else [])
                )
            ),
            "missing_paths": missing_paths,
            "invalid_fixture_ids": invalid_fixtures,
            "synthetic_fixture_count": synthetic_count,
            "required_fixtures": _required_fixture_list(),
        }
    if not real_fixtures:
        return {
            "validation_status": "blocked_no_fixtures",
            "scope": scope or None,
            "fixture_ids": [],
            "blockers": ["real_log_validation_blocked_no_fixtures"],
            "synthetic_fixture_count": synthetic_count,
            "required_fixtures": _required_fixture_list(),
        }

    passed = [
        f
        for f in real_fixtures
        if _fixture_status(f) == "pass" and not _fixture_proof_blockers(f)
    ]
    partial = [
        f
        for f in real_fixtures
        if _fixture_status(f) == "partial" and not _fixture_proof_blockers(f)
    ]
    failed = [
        f
        for f in real_fixtures
        if _fixture_status(f) == "fail" or _fixture_proof_blockers(f)
    ]
    if failed:
        status = "fail"
    elif passed and len(passed) == len(real_fixtures):
        status = "pass"
    elif passed or partial:
        status = "partial"
    else:
        status = "not_run"
    accepted_partials = [f for f in partial if bool(f.get("accepted_partial"))]
    accepted_scope = None
    if accepted_partials:
        accepted_scope = accepted_partials[0].get("accepted_scope") or {
            "firmware_scope": accepted_partials[0].get("firmware_scope"),
            "fixture_id": accepted_partials[0].get("id") or accepted_partials[0].get("fixture_id"),
        }
    blockers = [] if status in {"pass", "partial"} else [f"real_log_validation_{status}"]
    if failed:
        for fixture in failed:
            blockers.extend(_fixture_proof_blockers(fixture))
    return {
        "validation_status": status,
        "scope": scope or None,
        "fixture_ids": [str(f.get("id") or f.get("fixture_id")) for f in real_fixtures],
        "accepted_partial": bool(accepted_partials),
        "accepted_scope": accepted_scope,
        "blockers": list(dict.fromkeys(blockers)),
        "synthetic_fixture_count": synthetic_count,
        "required_fixtures": _required_fixture_list(),
    }


__all__ = [
    "ALLOWED_STATUSES",
    "DEFAULT_MANIFEST_PATH",
    "REAL_VALIDATION_SOURCES",
    "PROOF_READY_PROFILE_STATES",
    "load_real_validation_manifest",
    "resolve_real_log_validation_status",
]
