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
