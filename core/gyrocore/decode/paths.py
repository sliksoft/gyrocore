"""Trusted local BBL path validation (no upload-root jail)."""

from __future__ import annotations

from pathlib import Path

from gyrocore.config import CoreConfig
from gyrocore.errors import InvalidInputError

_ALLOWED_SUFFIXES = {".bbl", ".bfl", ".txt"}  # .txt rare; keep donor-ish flexibility
_SNIFF_BYTES = 4096
_MIN_PLAUSIBLE_BLACKBOX_BYTES = 64
_MIN_BINARY_RATIO_FOR_FRAMED_BBL = 0.05
_BLACKBOX_LIKE_TOKENS = (
    b"blackbox",
    b"betaflight",
    b"cleanflight",
    b"inav",
    b"field ",
    b"h product",
    b"firmware",
)


def validate_bbl_path(
    file_path: str | Path,
    config: CoreConfig | None = None,
    *,
    sniff_content: bool = True,
) -> Path:
    """
    Validate an explicit local BBL path for Core decode.

    Default policy (``allow_arbitrary_local_paths=True``): any readable existing file
    that passes basic type/content checks. Optional ``extra_trusted_path_roots`` are
    only enforced when ``allow_arbitrary_local_paths`` is False (web-adapter mode).
    """
    cfg = config or CoreConfig.defaults()
    try:
        resolved = Path(file_path).expanduser().resolve()
    except OSError as exc:
        raise InvalidInputError(f"invalid BBL path: {file_path}") from exc

    if not resolved.is_file():
        raise InvalidInputError(f"BBL file not found: {resolved}")

    if not cfg.allow_arbitrary_local_paths:
        roots = cfg.trusted_roots()
        if not roots:
            raise InvalidInputError(
                "allow_arbitrary_local_paths is False and no extra_trusted_path_roots set"
            )
        allowed = False
        for root in roots:
            try:
                resolved.relative_to(root.expanduser().resolve())
                allowed = True
                break
            except ValueError:
                continue
        if not allowed:
            raise InvalidInputError("BBL path is outside configured trusted roots")

    suffix = resolved.suffix.lower()
    if suffix and suffix not in _ALLOWED_SUFFIXES and suffix != ".csv":
        # Allow unusual suffixes but prefer known ones; still sniff.
        pass

    if sniff_content:
        _sniff_blackbox_content(resolved)

    return resolved


def _sniff_blackbox_content(path: Path) -> None:
    try:
        with path.open("rb") as fh:
            head = fh.read(_SNIFF_BYTES)
    except OSError as exc:
        raise InvalidInputError(f"cannot read BBL: {path}") from exc

    if not head:
        raise InvalidInputError("BBL file is empty")

    lowered = head.lower()
    stripped = lowered.lstrip()
    if stripped.startswith((b"{", b"[", b"<html", b"<!doctype", b"<?xml")):
        raise InvalidInputError("BBL content looks like text/html/json, not Blackbox")

    if any(token in lowered for token in _BLACKBOX_LIKE_TOKENS):
        return

    if len(head) < _MIN_PLAUSIBLE_BLACKBOX_BYTES:
        raise InvalidInputError("BBL content too small / implausible")

    printable = sum(1 for b in head if b in (9, 10, 13) or 32 <= b <= 126)
    printable_ratio = printable / max(1, len(head))
    if printable_ratio >= 0.92 and b"\x00" not in head:
        raise InvalidInputError("BBL content looks like plain text, not Blackbox")

    binary_ratio = 1.0 - printable_ratio
    if binary_ratio < _MIN_BINARY_RATIO_FOR_FRAMED_BBL:
        raise InvalidInputError("BBL content failed binary/framed heuristics")
