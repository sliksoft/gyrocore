"""Explicit Core runtime configuration.

Donor AeroTuner currently reads several ``os.environ`` keys inside services
(``AEROTUNER_BLACKBOX_DECODE``, upload limits, decoder roots, AI flags).
Core domain code must receive an explicit ``CoreConfig`` instead of reading
environment variables directly. Environment adapters belong outside Core.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .errors import ConfigurationError

# Defaults aligned with donor decoder/upload behavior (values only; no env reads).
# Source reference: aerotuner/backend/services/decoder.py (_DECODE_TIMEOUT_S = 300)
DEFAULT_DECODE_TIMEOUT_S = 300.0
# Source reference: aerotuner upload_limits / decoded CSV guards — conservative default.
DEFAULT_MAX_DECODED_CSV_BYTES = 80 * 1024 * 1024


@dataclass(frozen=True)
class CoreConfig:
    """
    Domain/runtime knobs for later decoder/analysis extraction.

    WU1 does not implement decode/analyze; this object only defines the boundary.
    """

    # Decoder (future WU — locator only; no subprocess here)
    blackbox_decode_path: str | None = None
    decode_timeout_s: float = DEFAULT_DECODE_TIMEOUT_S
    max_decoded_csv_bytes: int = DEFAULT_MAX_DECODED_CSV_BYTES

    # Path policy for trusted local analysis (desktop/Redline).
    # ``allow_arbitrary_local_paths=True`` is the intended Core default for
    # user-selected files; AeroTuner upload allowlists are a web adapter concern.
    allow_arbitrary_local_paths: bool = True
    extra_trusted_path_roots: tuple[str, ...] = field(default_factory=tuple)

    # Determinism / optional online features
    ai_enabled: bool = False

    def __post_init__(self) -> None:
        if self.decode_timeout_s <= 0:
            raise ConfigurationError("decode_timeout_s must be > 0")
        if self.max_decoded_csv_bytes <= 0:
            raise ConfigurationError("max_decoded_csv_bytes must be > 0")
        if self.blackbox_decode_path is not None:
            path = str(self.blackbox_decode_path).strip()
            if not path:
                raise ConfigurationError("blackbox_decode_path must be non-empty when set")
            object.__setattr__(self, "blackbox_decode_path", path)

    def with_updates(self, **kwargs: object) -> CoreConfig:
        """Return a copy with selected fields replaced."""
        return replace(self, **kwargs)

    def trusted_roots(self) -> tuple[Path, ...]:
        return tuple(Path(p).expanduser() for p in self.extra_trusted_path_roots)

    @classmethod
    def defaults(cls) -> CoreConfig:
        return cls()

    @classmethod
    def for_deterministic_oracle(cls) -> CoreConfig:
        """Config matching WU0 AI-disabled oracle expectations."""
        return cls(ai_enabled=False, allow_arbitrary_local_paths=True)
