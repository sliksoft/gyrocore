"""Inspect a Blackbox log without flight analysis or tuning."""

from __future__ import annotations

from pathlib import Path

from gyrocore.betaflight.version import classify_firmware_metadata
from gyrocore.config import CoreConfig
from gyrocore.decode.decoder import decode_bbl, decode_runtime_status
from gyrocore.decode.models import InspectLogResult
from gyrocore.decode.paths import validate_bbl_path
from gyrocore.errors import DecodeError, InvalidInputError, ParseError
from gyrocore.parse.blackbox_csv import parse_blackbox_csv
from gyrocore.parse.firmware_metadata import (
    extract_firmware_from_bbl_binary,
    extract_firmware_metadata,
)


def inspect_log(
    file_path: str | Path,
    *,
    log_index: int | None = None,
    config: CoreConfig | None = None,
    parse_samples: bool = True,
) -> InspectLogResult:
    """
    Decode (and optionally parse) a BBL for metadata / sample count.

    Does not run FFT, quality analysis, or tuning.
    """
    cfg = config or CoreConfig.defaults()
    path_s = str(file_path)
    runtime = decode_runtime_status(cfg)
    decoder_ready = bool(runtime.get("ready"))

    try:
        bbl = validate_bbl_path(file_path, cfg, sniff_content=False)
    except InvalidInputError as exc:
        return InspectLogResult(
            path=path_s,
            exists=False,
            decoder_ready=decoder_ready,
            message=str(exc),
        )

    fw_binary = extract_firmware_from_bbl_binary(str(bbl))
    try:
        decoded = decode_bbl(bbl, log_index=log_index, config=cfg)
    except (DecodeError, InvalidInputError) as exc:
        return InspectLogResult(
            path=str(bbl),
            exists=True,
            decoder_ready=decoder_ready,
            firmware=dict(fw_binary),
            message=str(exc),
            decode_ok=False,
        )

    fw = extract_firmware_metadata(decoded.headers_text, decoded.csv_text)
    if fw_binary:
        merged = dict(fw)
        merged.update(fw_binary)
        fw = merged

    # Optional WU2 classification enrichment (does not replace raw metadata).
    _ = classify_firmware_metadata(
        {
            "name": fw.get("name") or fw.get("firmware") or "",
            "version": fw.get("version") or "",
            "board": fw.get("board") or fw.get("board_name") or "",
        }
    )

    sample_count: int | None = None
    message: str | None = None
    if parse_samples:
        try:
            parsed = parse_blackbox_csv(decoded.csv_text, log_index=log_index)
            if parsed.get("parse_failed"):
                message = str(parsed.get("message") or "parse_failed")
            else:
                sample_count = int(parsed.get("count") or len(parsed.get("samples") or []))
        except Exception as exc:  # pragma: no cover — parser returns dicts normally
            raise ParseError(str(exc)) from exc

    embedded = decoded.embedded_log if isinstance(decoded.embedded_log, dict) else {}
    entries = embedded.get("embedded_log_entries") if isinstance(embedded, dict) else None
    return InspectLogResult(
        path=str(bbl),
        exists=True,
        decoder_ready=decoder_ready,
        firmware=fw,
        embedded_log_count=(
            int(embedded["embedded_log_count"])
            if isinstance(embedded, dict) and embedded.get("embedded_log_count") is not None
            else (len(entries) if isinstance(entries, list) else None)
        ),
        embedded_log_entries=list(entries) if isinstance(entries, list) else [],
        recommended_embedded_log_index=(
            int(embedded["recommended_embedded_log_index"])
            if isinstance(embedded, dict)
            and embedded.get("recommended_embedded_log_index") is not None
            else None
        ),
        selected_embedded_log_index=decoded.decoded_embedded_log_index,
        sample_count=sample_count,
        headers_text=decoded.headers_text,
        decode_ok=True,
        message=message,
    )
