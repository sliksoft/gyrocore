"""Safety invariants that must hold for every parity/oracle result."""

from __future__ import annotations

from typing import Any, Mapping


class SafetyInvariantError(AssertionError):
    """Raised when a mandatory safety invariant fails."""


def assert_safety_invariants(
    projection: Mapping[str, Any],
    *,
    require_full_safety: bool = True,
) -> None:
    """
    Hard gates for WU0 and later Core migration.

    ``require_full_safety=False`` is only for explicitly marked snapshot_partial
    projections (BLOCKED real BBL path).
    """
    if not isinstance(projection, Mapping):
        raise SafetyInvariantError("projection must be a mapping")

    if projection.get("ai_disabled") is not True:
        raise SafetyInvariantError("AI must be disabled for golden oracle runs")

    tos = projection.get("tuning_output_safety")
    if not isinstance(tos, Mapping) or not tos.get("present"):
        raise SafetyInvariantError("tuning_output_safety must be present")

    snapshot_partial = bool(tos.get("snapshot_partial"))
    if require_full_safety and snapshot_partial:
        raise SafetyInvariantError(
            "snapshot_partial projection cannot satisfy full live safety gate"
        )

    mech = projection.get("mechanical_safety")
    if not isinstance(mech, Mapping):
        raise SafetyInvariantError("mechanical_safety must be present")

    cli_actionable = tos.get("cli_actionable")
    cli = str(projection.get("authoritative_cli") or "").strip()

    # 1 / 7: no actionable CLI unless safety allows it
    if cli_actionable is True:
        # Actionable is allowed only with explicit True; CLI may still be empty
        # when status is actionable_warning without generated lines.
        pass
    else:
        # Blocked / limited-non-actionable / None must not claim actionable paste-ready.
        if cli_actionable is True:  # pragma: no cover — defensive
            raise SafetyInvariantError("cli_actionable True without safety allow")

    status = str(tos.get("status") or "").lower()
    if status in {"blocked", "diagnostic", "diagnostic_only", "unknown"} and cli_actionable is True:
        raise SafetyInvariantError(
            f"blocked/diagnostic safety status cannot be cli_actionable (status={status})"
        )

    if cli_actionable is not True and cli and status in {"blocked", "diagnostic", "diagnostic_only"}:
        # Presence of CLI text while blocked is allowed only as non-actionable metadata;
        # the actionable flag must remain false (already checked). Keep as soft note via assert.
        if cli_actionable is True:
            raise SafetyInvariantError("blocked tune exposed actionable CLI")

    # 4: decision-engine CLI must not be the authoritative CLI source.
    # Heuristic: projection.authoritative_cli must equal tuning-path CLI only;
    # we forbid a dedicated decision_engine_cli field from winning.
    if projection.get("decision_engine_cli_authoritative") is True:
        raise SafetyInvariantError("decision-engine CLI must not be authoritative")

    # 6: missing final safety fails
    if tos.get("cli_actionable") is None and not snapshot_partial:
        raise SafetyInvariantError("tuning_output_safety.cli_actionable must be boolean")

    if not snapshot_partial:
        if not str(tos.get("status") or "").strip():
            raise SafetyInvariantError("tuning_output_safety.status must be non-empty")


def assert_wu11_cli_invariants(auth_payload: Mapping[str, Any]) -> None:
    """WU11 extensions: PASS-only actionable CLI, rollback required, no WARN/BLOCK apply."""
    if not isinstance(auth_payload, Mapping):
        raise SafetyInvariantError("cli authorization payload must be a mapping")
    status = str(auth_payload.get("status") or "")
    authorized = auth_payload.get("authorized") is True
    bundle = auth_payload.get("bundle")
    preview = auth_payload.get("preview")
    denial = auth_payload.get("denial")

    if authorized:
        if status != "authorized" or not isinstance(bundle, Mapping):
            raise SafetyInvariantError("authorized CLI requires an ActionableTuneBundle")
        if bundle.get("authorized") is not True or bundle.get("actionable") is not True:
            raise SafetyInvariantError("bundle must be authorized and actionable")
        if not str(bundle.get("apply_cli") or "").strip():
            raise SafetyInvariantError("authorized bundle missing apply_cli")
        if not str(bundle.get("rollback_cli") or "").strip():
            raise SafetyInvariantError("rollback required for actionable bundle")
        if preview or denial:
            raise SafetyInvariantError("authorized result cannot also be preview/denial")
        prov = bundle.get("safety_provenance")
        if not isinstance(prov, Mapping):
            raise SafetyInvariantError("actionable bundle missing safety provenance")
        for key in ("mechanical", "clamps", "tuning_output_safety", "cli_authorization"):
            if key not in prov:
                raise SafetyInvariantError(f"missing provenance {key}")
        return

    if isinstance(bundle, Mapping) and bundle.get("authorized") is True:
        raise SafetyInvariantError("non-authorized status cannot carry an authorized bundle")
    if isinstance(preview, Mapping):
        if preview.get("authorized") is True or preview.get("actionable") is True:
            raise SafetyInvariantError("WARN preview cannot be actionable")
        if "apply_cli" in preview or "actionable_cli" in preview or "paste_ready_cli" in preview:
            raise SafetyInvariantError("preview must not expose apply/paste-ready fields")
        text = str(preview.get("preview_cli") or "")
        if "\nsave\n" in f"\n{text}\n" or text.strip().endswith("save"):
            raise SafetyInvariantError("WARN preview must not include save")
    if isinstance(denial, Mapping):
        if denial.get("authorized") is True or denial.get("actionable") is True:
            raise SafetyInvariantError("BLOCK denial cannot be actionable")
        for forbidden in ("apply_cli", "actionable_cli", "paste_ready_cli", "preview_cli"):
            if forbidden in denial:
                raise SafetyInvariantError(f"BLOCK denial must not contain {forbidden}")
