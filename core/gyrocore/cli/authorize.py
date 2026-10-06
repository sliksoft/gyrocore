"""CLI authorization gate (WU11). Accepts only FinalSafeTuneResult."""

from __future__ import annotations

from typing import Any

from gyrocore.autotune.merge import MERGE_REQUIRES_REVIEW
from gyrocore.betaflight.simplified_tuning import FIRMWARE_PROVENANCE
from gyrocore.betaflight.version import classify_betaflight_version
from gyrocore.cli.emit import (
    PREVIEW_BANNER,
    bundle_hash,
    diff_settings,
    flatten_absolute_tune,
    overlay_settings,
    profile_index,
    render_cli,
    required_pid_keys,
)
from gyrocore.cli.results import (
    CliAuthorizationResult,
    make_actionable_bundle,
    make_denial,
    make_preview,
)
from gyrocore.cli.settings import CLI_RANGES, FIRMWARE_CLI_PROVENANCE
from gyrocore.safety.results import FinalSafeTuneResult
from gyrocore.safety.types import SafetyCheck, SafetyVerdict, StageBypassError

DENY_NOT_PASS = "final_safety_not_pass"
DENY_WARN_NOT_ACTIONABLE = "warn_is_not_actionable"
DENY_BLOCKED_REASONS = "blocked_or_review_reasons_present"
DENY_MERGE = "unresolved_merge_requires_review"
DENY_MISSING_TARGET = "missing_final_target"
DENY_MISSING_BASELINE = "missing_required_pid_or_filter_baseline"
DENY_PROFILE = "pid_profile_unknown_or_invalid"
DENY_UNSUPPORTED = "unsupported_betaflight_state"
DENY_RANGE = "target_values_outside_firmware_range"
DENY_ROLLBACK_INCOMPLETE = "rollback_baseline_incomplete"
DENY_MALFORMED = "malformed_final_safe_tune"
DENY_STAGES = "required_safety_stage_missing"


def _firmware_label(final: FinalSafeTuneResult) -> Any:
    prov = final.proposal.provenance if hasattr(final, "proposal") else {}
    fw = prov.get("firmware") if isinstance(prov, dict) else None
    if isinstance(fw, dict) and fw.get("version"):
        return fw.get("version")
    return FIRMWARE_PROVENANCE.get("version")


def _values_in_range(flat: dict[str, int]) -> tuple[str, ...]:
    bad: list[str] = []
    for key, value in flat.items():
        bounds = CLI_RANGES.get(key)
        if bounds is None:
            bad.append(f"unsupported_setting:{key}")
            continue
        lo, hi = bounds
        if value < lo or value > hi:
            bad.append(f"{key}_out_of_range")
    return tuple(bad)


def _safety_provenance(final: FinalSafeTuneResult) -> dict[str, Any]:
    return {
        "mechanical": final.mechanical.to_dict(),
        "clamps": {
            "clamp_ids": list(final.candidate.clamp_ids),
            "checks": [c.to_dict() for c in final.candidate.checks],
            "status": final.candidate.status.value,
        },
        "tuning_output_safety": final.output_safety.to_dict(),
        "final": {
            "status": final.status.value,
            "actionable_wu10": False,
            "blocked_reasons": list(final.blocked_reasons),
            "warnings": list(final.warnings),
        },
        "cli_authorization": "authorize_cli",
    }


def _deny(reasons: tuple[str, ...], final: FinalSafeTuneResult | None, extra: dict[str, Any] | None = None) -> CliAuthorizationResult:
    status = final.status.value if final is not None else "unknown"
    diagnostic: dict[str, Any] = dict(extra or {})
    if final is not None and final.clamped_tune is not None:
        diagnostic["diagnostic_target_only"] = flatten_absolute_tune(final.clamped_tune)
    return CliAuthorizationResult(
        status="denied",
        denial=make_denial(
            blocked_reasons=tuple(dict.fromkeys(reasons)),
            diagnostic_values=diagnostic,
            final_status=status,
        ),
    )


def authorize_cli(final: FinalSafeTuneResult) -> CliAuthorizationResult:
    """Authorize paste-ready CLI from a completed FinalSafeTuneResult only."""
    if not isinstance(final, FinalSafeTuneResult):
        raise StageBypassError("authorize_cli accepts only FinalSafeTuneResult")

    reasons: list[str] = []
    checks: list[SafetyCheck] = [
        SafetyCheck(rule_id="cli.final_present", verdict=SafetyVerdict.PASS, message="FinalSafeTuneResult"),
        SafetyCheck(rule_id="cli.mechanical_present", verdict=SafetyVerdict.PASS, message=final.mechanical.stage),
        SafetyCheck(rule_id="cli.clamp_present", verdict=SafetyVerdict.PASS, message=final.candidate.stage),
        SafetyCheck(rule_id="cli.tos_present", verdict=SafetyVerdict.PASS, message=final.output_safety.stage),
    ]

    if final.status is SafetyVerdict.BLOCK:
        reasons.extend(final.blocked_reasons or (DENY_NOT_PASS,))
        return _deny(tuple(reasons) or (DENY_NOT_PASS,), final)

    proposal = final.proposal
    if proposal.status == MERGE_REQUIRES_REVIEW or proposal.review_reasons:
        reasons.append(DENY_MERGE)
        reasons.extend(proposal.review_reasons)
    if final.blocked_reasons:
        reasons.append(DENY_BLOCKED_REASONS)
        reasons.extend(final.blocked_reasons)
    if final.clamped_tune is None:
        reasons.append(DENY_MISSING_TARGET)
    if proposal.current is None:
        reasons.append(DENY_MALFORMED)

    fw_label = _firmware_label(final)
    support = classify_betaflight_version(fw_label)
    if support.get("cli_allowed") is not True:
        reasons.append(DENY_UNSUPPORTED)
        reasons.append(str(support.get("reason") or "betaflight_firmware_unknown"))

    current_flat = flatten_absolute_tune(proposal.current)
    target_flat = flatten_absolute_tune(final.clamped_tune) if final.clamped_tune is not None else {}
    required = required_pid_keys()
    missing_required_current = tuple(k for k in required if k not in current_flat)
    if not current_flat or missing_required_current:
        reasons.append(DENY_MISSING_BASELINE)
        reasons.extend(f"missing_baseline:{k}" for k in missing_required_current)
    missing_required_target = tuple(k for k in required if k not in target_flat)
    if final.clamped_tune is not None and (not target_flat or missing_required_target):
        reasons.append(DENY_MISSING_TARGET)
        reasons.extend(f"missing_target:{k}" for k in missing_required_target)

    src_profile = profile_index(proposal.current)
    tgt_profile = profile_index(final.clamped_tune) if final.clamped_tune is not None else None
    if src_profile is None or tgt_profile is None or src_profile != tgt_profile:
        reasons.append(DENY_PROFILE)

    range_bad = _values_in_range(target_flat)
    if range_bad:
        reasons.append(DENY_RANGE)
        reasons.extend(range_bad)

    changed, unchanged, missing_base = diff_settings(current_flat, target_flat)
    if missing_base:
        reasons.append(DENY_ROLLBACK_INCOMPLETE)
        reasons.extend(f"missing_baseline:{k}" for k in missing_base)

    if final.status is SafetyVerdict.WARN:
        if reasons:
            return _deny(tuple(dict.fromkeys(reasons + [DENY_WARN_NOT_ACTIONABLE])), final)
        preview = render_cli(
            profile=src_profile,
            settings=changed,
            include_save=False,
            header_lines=(PREVIEW_BANNER,),
        )
        return CliAuthorizationResult(
            status="preview",
            preview=make_preview(
                preview_cli=preview,
                reasons=tuple(dict.fromkeys((*final.warnings, DENY_WARN_NOT_ACTIONABLE))),
                current_values=current_flat,
                target_values=target_flat,
                changed_settings=changed,
                final=final,
            ),
        )

    if final.status is not SafetyVerdict.PASS:
        reasons.append(DENY_NOT_PASS)
        return _deny(tuple(dict.fromkeys(reasons)), final)

    if reasons:
        return _deny(tuple(dict.fromkeys(reasons)), final)

    assert src_profile is not None and tgt_profile is not None
    include_save = bool(changed)
    apply_cli = render_cli(profile=src_profile, settings=changed, include_save=include_save)
    rollback_values = {key: current_flat[key] for key in changed}
    rollback_cli = render_cli(profile=src_profile, settings=rollback_values, include_save=include_save)

    after_apply = overlay_settings(current_flat, apply_cli)
    after_rollback = overlay_settings(target_flat, rollback_cli)
    for key, val in target_flat.items():
        if after_apply.get(key) != val:
            return _deny((DENY_MALFORMED, f"apply_roundtrip_mismatch:{key}"), final)
    for key, val in current_flat.items():
        if key in changed and after_rollback.get(key) != val:
            return _deny((DENY_MALFORMED, f"rollback_roundtrip_mismatch:{key}"), final)

    checks.append(
        SafetyCheck(
            rule_id="cli.authorized",
            verdict=SafetyVerdict.PASS,
            message="PASS authorized",
            evidence={"changed": list(changed), "save": include_save},
        )
    )
    bundle = make_actionable_bundle(
        apply_cli=apply_cli,
        rollback_cli=rollback_cli,
        source_profile=src_profile,
        target_profile=tgt_profile,
        profile_command_required=True,
        current_values=current_flat,
        target_values=target_flat,
        changed_settings=changed,
        unchanged_settings=unchanged,
        warnings=tuple(final.warnings),
        verification_expectations={
            "after_apply_equals_target": True,
            "after_rollback_equals_baseline": True,
            "save_is_last_command": include_save,
            "profile": src_profile,
        },
        safety_provenance=_safety_provenance(final),
        firmware_provenance=dict(FIRMWARE_CLI_PROVENANCE),
        bundle_id=bundle_hash(apply_cli + "\n--rollback--\n" + rollback_cli),
        checks=tuple(checks),
        final=final,
    )
    return CliAuthorizationResult(status="authorized", bundle=bundle)


__all__ = ["authorize_cli"]
