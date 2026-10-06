"""Decode / inspect result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecodeResult:
    """Successful BBL → CSV decode payload (in-memory)."""

    csv_text: str
    headers_text: str = ""
    decoded_embedded_log_index: int | None = None
    embedded_log: dict[str, Any] | None = None

    def as_legacy_dict(self) -> dict[str, Any]:
        """Donor-shaped dict for parity comparisons (``ok`` always True)."""
        out: dict[str, Any] = {
            "ok": True,
            "data": self.csv_text,
            "headers_text": self.headers_text,
        }
        if self.embedded_log is not None:
            out["embedded_log"] = self.embedded_log
        if self.decoded_embedded_log_index is not None:
            out["decoded_embedded_log_index"] = self.decoded_embedded_log_index
        return out


@dataclass(frozen=True)
class InspectLogResult:
    """Low-level log inspection without analysis/tuning."""

    path: str
    exists: bool
    decoder_ready: bool
    firmware: dict[str, str] = field(default_factory=dict)
    embedded_log_count: int | None = None
    embedded_log_entries: list[dict[str, Any]] = field(default_factory=list)
    recommended_embedded_log_index: int | None = None
    selected_embedded_log_index: int | None = None
    sample_count: int | None = None
    headers_text: str = ""
    decode_ok: bool = False
    message: str | None = None
