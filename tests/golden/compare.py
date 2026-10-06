"""Compare two DOMAIN projections using centralized policies."""

from __future__ import annotations

from typing import Any

from tests.golden.normalize import (
    POLICY_EXACT,
    POLICY_IGNORED,
    POLICY_NORMALIZED_EXACT,
    POLICY_TOLERANCE,
    field_policy,
    floats_close,
    normalize_for_compare,
    tolerance_for_path,
)


class ParityMismatch(AssertionError):
    """Raised when golden parity comparison fails."""


def _walk(
    expected: Any,
    actual: Any,
    *,
    path: str,
    mismatches: list[str],
) -> None:
    policy = field_policy(path)
    if policy == POLICY_IGNORED:
        return

    exp_n = normalize_for_compare(path, expected)
    act_n = normalize_for_compare(path, actual)

    if policy in {POLICY_EXACT, POLICY_NORMALIZED_EXACT}:
        if type(exp_n) is not type(act_n) and not (
            isinstance(exp_n, (int, float)) and isinstance(act_n, (int, float))
        ):
            # Allow None vs missing only when both falsy-equivalent for optional indices.
            if exp_n is None and act_n is None:
                return
        if isinstance(exp_n, dict) and isinstance(act_n, dict):
            keys = sorted(set(exp_n) | set(act_n))
            for key in keys:
                child = f"{path}.{key}" if path else key
                if key not in exp_n:
                    mismatches.append(f"{child}: unexpected key in actual")
                    continue
                if key not in act_n:
                    mismatches.append(f"{child}: missing key in actual")
                    continue
                _walk(exp_n[key], act_n[key], path=child, mismatches=mismatches)
            return
        if isinstance(exp_n, list) and isinstance(act_n, list):
            if exp_n != act_n:
                mismatches.append(f"{path}: list mismatch expected={exp_n!r} actual={act_n!r}")
            return
        if exp_n != act_n:
            mismatches.append(f"{path}: expected={exp_n!r} actual={act_n!r}")
        return

    if policy == POLICY_TOLERANCE:
        if isinstance(exp_n, dict) and isinstance(act_n, dict):
            keys = sorted(set(exp_n) | set(act_n))
            for key in keys:
                child = f"{path}.{key}" if path else key
                if key not in exp_n or key not in act_n:
                    # Tolerate missing optional metric leaves.
                    continue
                _walk(exp_n[key], act_n[key], path=child, mismatches=mismatches)
            return
        if isinstance(exp_n, list) and isinstance(act_n, list):
            if len(exp_n) != len(act_n):
                mismatches.append(
                    f"{path}: list length expected={len(exp_n)} actual={len(act_n)}"
                )
                return
            for i, (e, a) in enumerate(zip(exp_n, act_n)):
                _walk(e, a, path=f"{path}[{i}]", mismatches=mismatches)
            return
        if isinstance(exp_n, (int, float)) and isinstance(act_n, (int, float)):
            abs_tol, rel_tol = tolerance_for_path(path)
            if not floats_close(float(exp_n), float(act_n), abs_tol=abs_tol, rel_tol=rel_tol):
                mismatches.append(
                    f"{path}: tol mismatch expected={exp_n!r} actual={act_n!r} "
                    f"(abs={abs_tol} rel={rel_tol})"
                )
            return
        if exp_n != act_n:
            mismatches.append(f"{path}: expected={exp_n!r} actual={act_n!r}")
        return

    if exp_n != act_n:
        mismatches.append(f"{path}: expected={exp_n!r} actual={act_n!r}")


def compare_projections(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    raise_on_mismatch: bool = True,
) -> list[str]:
    mismatches: list[str] = []
    # Top-level keys that must always be compared when present in expected.
    for key in sorted(expected.keys()):
        if key not in actual:
            mismatches.append(f"{key}: missing in actual")
            continue
        _walk(expected[key], actual[key], path=key, mismatches=mismatches)
    if raise_on_mismatch and mismatches:
        raise ParityMismatch("parity mismatches:\n- " + "\n- ".join(mismatches))
    return mismatches
