"""Public analyze result wrapper preserving legacy/DOMAIN payloads."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping

from .safety import (
    MechanicalSafetyView,
    TuningOutputSafetyView,
    actionable_cli_allowed,
)


@dataclass(frozen=True)
class AnalyzeResult:
    """
    Minimal public result boundary for migration.

    ``domain`` holds the authoritative legacy-compatible / WU0 DOMAIN projection
    (or a full legacy response during adapter phase). Typed accessors are thin
    views — they do not recompute analysis.
    """

    domain: Mapping[str, Any] = field(default_factory=dict)
    legacy_response: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        # Freeze a shallow-copied mapping so callers cannot mutate stored state
        # through the original dict reference.
        object.__setattr__(self, "domain", dict(self.domain))
        if self.legacy_response is not None:
            object.__setattr__(self, "legacy_response", dict(self.legacy_response))

    @classmethod
    def from_domain(cls, domain: Mapping[str, Any]) -> AnalyzeResult:
        return cls(domain=deepcopy(dict(domain)))

    @classmethod
    def from_legacy_response(cls, response: Mapping[str, Any]) -> AnalyzeResult:
        """
        Wrap a full legacy analyze response.

        ``domain`` initially mirrors the response; later WUs may project.
        """
        copied = deepcopy(dict(response))
        return cls(domain=copied, legacy_response=copied)

    def domain_copy(self) -> dict[str, Any]:
        """Deep copy of the preserved domain payload."""
        return deepcopy(dict(self.domain))

    @property
    def analysis_status(self) -> str:
        return str(self.domain.get("analysis_status") or self.domain.get("status") or "")

    @property
    def authoritative_cli(self) -> str:
        return str(self.domain.get("authoritative_cli") or "")

    @property
    def tuning_output_safety(self) -> TuningOutputSafetyView:
        raw = self.domain.get("tuning_output_safety")
        if not isinstance(raw, Mapping):
            # Prefer nested legacy location when wrapping full responses.
            raw = None
            if self.legacy_response is not None:
                cand = self.legacy_response.get("tuning_output_safety")
                if isinstance(cand, Mapping):
                    raw = cand
        return TuningOutputSafetyView.from_legacy(raw)

    @property
    def mechanical_safety(self) -> MechanicalSafetyView:
        raw = self.domain.get("mechanical_safety")
        if isinstance(raw, Mapping):
            return MechanicalSafetyView.from_legacy(raw)
        tos = self.tuning_output_safety
        if tos.raw and isinstance(tos.raw.get("mechanical"), Mapping):
            return MechanicalSafetyView.from_legacy(tos.raw.get("mechanical"))  # type: ignore[arg-type]
        return tos.mechanical

    def cli_is_actionable(self) -> bool:
        return actionable_cli_allowed(self.tuning_output_safety)
