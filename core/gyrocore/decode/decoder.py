"""BBL → CSV via ``blackbox_decode`` (WU3).

Adapted from AeroTuner ``backend/services/decoder.py`` with:

- trusted explicit local paths (no uploads-root jail)
- CoreConfig for executable / timeout / size limits (no env reads)
- controlled temporary workspace for CSV capture (does not write ``*.csv``
  beside the caller's source BBL)
- typed ``DecodeError`` / ``InvalidInputError`` instead of HTTP-shaped dicts
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from gyrocore.config import CoreConfig
from gyrocore.decode.embedded import (
    build_embedded_log_metadata,
    parse_embedded_log_table,
    recommend_embedded_log_index,
)
from gyrocore.decode.locator import resolve_blackbox_decode
from gyrocore.decode.models import DecodeResult
from gyrocore.decode.paths import validate_bbl_path
from gyrocore.errors import DecodeError, InvalidInputError
from gyrocore.parse.firmware_metadata import (
    csv_head_for_firmware_fallback,
    extract_preamble_before_gyro_header,
)

logger = logging.getLogger(__name__)

_MULTI_LOG_MARKER = "multiple flight logs"
_MIN_CSV_BYTES = 50
_HEADERS_TEXT_RAW_CSV_MAX_CHARS = 50_000
_HEADERS_CSV_INDEX_RE = re.compile(r"\.(\d+)\.headers\.csv$", re.IGNORECASE)


def decode_runtime_status(config: CoreConfig | None = None) -> dict[str, object]:
    """Lightweight readiness: decoder executable resolvable?"""
    try:
        resolve_blackbox_decode(config)
    except DecodeError:
        return {"ready": False, "error": "decoder_unavailable"}
    return {"ready": True, "error": None}


def _stderr_for_log(stderr: str | None, max_len: int = 400) -> str:
    if not stderr:
        return ""
    line = " ".join(stderr.strip().splitlines())
    if len(line) > max_len:
        return line[:max_len] + "…"
    return line


def _ensure_decoded_csv_size(output_file: Path, limit: int) -> None:
    if limit <= 0:
        return
    try:
        size = output_file.stat().st_size
    except OSError:
        return
    if size > limit:
        raise DecodeError(
            f"decoded_csv_too_large: decoded CSV is {size} bytes, limit is {limit}"
        )


def _run_decode(
    file_path: Path,
    *,
    work_dir: Path,
    config: CoreConfig,
    index: Optional[int] = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """
    Invoke ``blackbox_decode --stdout`` writing CSV into ``work_dir``.

    ``index`` is **0-based** internal; CLI receives ``--index N+1``.
    """
    output_file = work_dir / "decoded.csv"
    exe = resolve_blackbox_decode(config)
    cmd: list[str] = [str(exe), "--stdout", str(file_path)]
    if index is not None:
        cmd.extend(["--index", str(int(index) + 1)])

    try:
        with output_file.open("w", encoding="utf-8", errors="replace") as out_f:
            result = subprocess.run(
                cmd,
                cwd=str(work_dir),
                stdout=out_f,
                stderr=subprocess.PIPE,
                text=True,
                timeout=float(config.decode_timeout_s),
                shell=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise DecodeError(
            f"decode_timeout: blackbox_decode exceeded {config.decode_timeout_s}s"
        ) from exc
    except FileNotFoundError as exc:
        raise DecodeError("decoder_unavailable: blackbox_decode missing") from exc
    except PermissionError as exc:
        raise DecodeError("decoder_unavailable: blackbox_decode not executable") from exc

    if result.returncode != 0:
        logger.warning(
            "blackbox_decode exited with rc=%s stderr_prefix=%s",
            result.returncode,
            _stderr_for_log(result.stderr),
        )
    return result, output_file


def _stderr_says_multiple_logs(stderr: str | None) -> bool:
    if not stderr:
        return False
    return _MULTI_LOG_MARKER in stderr.lower()


def _decode_index_failed(result: subprocess.CompletedProcess[str], output_file: Path) -> bool:
    if result.returncode != 0:
        return True
    if not output_file.is_file():
        return True
    try:
        if output_file.stat().st_size < _MIN_CSV_BYTES:
            return True
    except OSError:
        return True
    return False


def _collect_headers_csv_paths(search_dirs: list[Path], file_path: Path) -> list[Path]:
    base_name = file_path.name
    stem = file_path.stem
    suffix = ".headers.csv"
    candidates: list[Path] = []
    stem_cf = stem.casefold()
    name_cf = base_name.casefold()
    for base_dir in search_dirs:
        try:
            files = os.listdir(base_dir)
        except OSError:
            continue
        for f in files:
            fl = f.casefold()
            if not fl.endswith(suffix.casefold()):
                continue
            if fl.startswith(stem_cf + ".") or fl.startswith(name_cf + "."):
                candidates.append(base_dir / f)
    return candidates


def _read_headers_csv(
    search_dirs: list[Path],
    file_path: Path,
    prefer_log_index: Optional[int] = None,
) -> tuple[Path | None, str | None]:
    candidates = _collect_headers_csv_paths(search_dirs, file_path)
    if not candidates:
        return None, None
    if prefer_log_index is not None:
        for path in sorted(candidates):
            m = _HEADERS_CSV_INDEX_RE.search(path.name)
            if not m:
                continue
            try:
                file_idx = int(m.group(1))
            except ValueError:
                continue
            if file_idx == prefer_log_index or file_idx == prefer_log_index + 1:
                try:
                    return path, path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
    path = sorted(candidates)[-1]
    try:
        return path, path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None, None


def _read_decoded_csv(output_file: Path, limit: int) -> str:
    _ensure_decoded_csv_size(output_file, limit)
    return output_file.read_text(encoding="utf-8", errors="ignore")


def _build_headers_text(data: str, sidecar_text: str | None) -> str:
    sidecar_nonempty = bool(sidecar_text and str(sidecar_text).strip())
    if sidecar_nonempty:
        headers_text = str(sidecar_text)
    else:
        headers_text = ""

    if not headers_text or not str(headers_text).strip():
        headers_text = extract_preamble_before_gyro_header(data)

    if not headers_text or not str(headers_text).strip():
        headers_text = csv_head_for_firmware_fallback(data)

    if (not headers_text or not str(headers_text).strip()) and data.strip():
        headers_text = data[:_HEADERS_TEXT_RAW_CSV_MAX_CHARS]

    return headers_text if isinstance(headers_text, str) else ""


def decode_bbl(
    file_path: str | Path,
    *,
    log_index: int | None = None,
    config: CoreConfig | None = None,
) -> DecodeResult:
    """
    Decode a Blackbox log to CSV text + headers.

    ``log_index`` is **0-based**. When omitted and the file contains multiple logs,
    the recommended (largest meaningful) log is selected automatically.
    """
    cfg = config or CoreConfig.defaults()
    # Existence / readability; content sniff is optional (upload adapter concern).
    bbl = validate_bbl_path(file_path, cfg, sniff_content=False)

    prefer_sidecar_index: Optional[int] = None
    embedded_log_meta: dict[str, object] | None = None

    with tempfile.TemporaryDirectory(prefix="gyrocore-decode-") as tmp:
        work_dir = Path(tmp)
        search_dirs = [work_dir, bbl.parent]

        if log_index is not None:
            selected_index = int(log_index)
            if selected_index < 0:
                raise InvalidInputError(
                    f"invalid_selected_embedded_log_index: {selected_index}"
                )
            result, output_file = _run_decode(
                bbl, work_dir=work_dir, config=cfg, index=selected_index
            )
            if _decode_index_failed(result, output_file):
                raise DecodeError(
                    f"empty_csv: requested embedded log index={selected_index} failed "
                    f"rc={result.returncode} stderr={_stderr_for_log(result.stderr)}"
                )
            data = _read_decoded_csv(output_file, cfg.max_decoded_csv_bytes)
            prefer_sidecar_index = selected_index
            embedded_log_meta = {
                "embedded_log_selection_mode": "manual",
                "selected_embedded_log_index": selected_index,
            }
        else:
            result, output_file = _run_decode(bbl, work_dir=work_dir, config=cfg)

            if _stderr_says_multiple_logs(result.stderr):
                entries = parse_embedded_log_table(result.stderr)
                if not entries:
                    raise DecodeError("empty_csv: multi-log stderr missing index table")
                selected_index = recommend_embedded_log_index(entries)
                logger.info(
                    "[decoder] embedded multi-log count=%d recommended_index=%d",
                    len(entries),
                    selected_index,
                )
                embedded_log_meta = build_embedded_log_metadata(
                    entries,
                    selected_index=selected_index,
                    selection_mode="auto",
                )
                result, output_file = _run_decode(
                    bbl, work_dir=work_dir, config=cfg, index=selected_index
                )
                if _decode_index_failed(result, output_file):
                    raise DecodeError(
                        f"empty_csv: recommended embedded log index={selected_index} failed"
                    )
                data = _read_decoded_csv(output_file, cfg.max_decoded_csv_bytes)
                prefer_sidecar_index = selected_index
            else:
                if not output_file.is_file():
                    raise DecodeError("no_output_file: blackbox_decode produced no CSV")
                if output_file.stat().st_size < _MIN_CSV_BYTES:
                    raise DecodeError(
                        f"empty_csv: output too small rc={result.returncode} "
                        f"stderr={_stderr_for_log(result.stderr)}"
                    )
                data = _read_decoded_csv(output_file, cfg.max_decoded_csv_bytes)

        if len(data) < _MIN_CSV_BYTES:
            raise DecodeError("empty_csv: decoded CSV too small")

        _sidecar_path, sidecar_text = _read_headers_csv(
            search_dirs, bbl, prefer_log_index=prefer_sidecar_index
        )
        headers_text = _build_headers_text(data, sidecar_text)

        # Never leave artifacts next to the source BBL (temp workspace cleans up).
        return DecodeResult(
            csv_text=data,
            headers_text=headers_text,
            decoded_embedded_log_index=prefer_sidecar_index,
            embedded_log=dict(embedded_log_meta) if embedded_log_meta else None,
        )
