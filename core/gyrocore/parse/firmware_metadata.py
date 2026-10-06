"""Firmware / board metadata extraction from Blackbox headers and CSV.

Adapted from AeroTuner ``backend/services/firmware_metadata.py`` (WU3).
"""


from __future__ import annotations

import csv
import io
import logging
import re

logger = logging.getLogger(__name__)

INVALID_BOARD_TOKENS = frozenset(
    {
        "ANGLE_MODE",
        "ACRO",
        "HORIZON",
        "ARMED",
        "DISARMED",
        "FAILSAFE",
        "GPS",
        "MAG",
        "BARO",
        "AIRMODE",
    }
)

# Subsystems / logging — not flight-controller targets (often matched by loose regex).
_BOGUS_BOARD_TOKENS = frozenset(
    {
        "BLACKBOX",
        "BLACKBOXFLIGHT",
        "OPENLOG",
        "OPENLOGREPLAY",
        "DATAFLASH",
        "SDCARD",
        "FLASHFS",
        "LOGGER",
        "FLIGHTDATA",
        "FIELD",
        "VALUE",
    }
)

_RE_BOARD_TOKEN_CHARS = re.compile(r"^[A-Za-z0-9_.-]+$")

# Data header row: first gyro sample columns blackbox_decode emits (see parser GYRO_ALIASES).
_GYRO_HEADER_CELL = re.compile(
    r"^("
    r"gyro\[\d+\]|"
    r"gyroadc\[\d+\]|"
    r"gyro_unfilt\[\d+\]|"
    r"gyrounfilt\[\d+]"
    r")$",
    re.IGNORECASE,
)


def _line_is_gyro_column_header_row(parsed: list[str]) -> bool:
    if len(parsed) < 2:
        return False
    for col in parsed:
        cell = col.strip()
        if not cell:
            continue
        if _GYRO_HEADER_CELL.match(cell):
            return True
    return False


def extract_preamble_before_gyro_header(csv_text: str) -> str:
    """
    All lines before the gyro data header row (columns ``gyro[0]`` / ``gyroADC[0]``
    / common unfilt variants). blackbox_decode often embeds a Field/Value metadata
    block in the main CSV; when ``*.headers.csv`` is missing, firmware/board still
    live here.
    """
    raw_lines = csv_text.splitlines()
    for idx, line in enumerate(raw_lines):
        if "," not in line:
            continue
        try:
            parsed = next(csv.reader([line]))
        except Exception:
            continue
        if not _line_is_gyro_column_header_row(parsed):
            continue
        if idx == 0:
            return ""
        return "\n".join(raw_lines[:idx])
    return ""


def csv_head_for_firmware_fallback(csv_text: str, max_chars: int = 49152, max_lines: int = 500) -> str:
    """
    When no sidecar and no lines precede the gyro header, still provide a prefix of
    the CSV so ``extract_firmware_metadata`` regex paths can find ``H ...`` lines.
    """
    if not csv_text or not str(csv_text).strip():
        return ""
    lines = csv_text.splitlines()
    chunk = lines[:max_lines]
    s = "\n".join(chunk)
    if len(s) > max_chars:
        s = s[:max_chars]
    return s


def _normalize_field_key(raw: str) -> str:
    """Lowercase, strip, drop leading underscores, spaces → underscores."""
    s = raw.strip().lower()
    s = s.lstrip("_").strip()
    s = re.sub(r"\s+", "_", s)
    return s


def _parse_headers_flat(headers_text: str) -> dict[str, str]:
    """
    Parse Field/Value CSV rows into a single dict with normalized keys
    (e.g. ``Firmware revision`` / ``_firmware revision`` → ``firmware_revision``).
    """
    text = headers_text.lstrip("\ufeff")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return {}
    flat: dict[str, str] = {}
    for row in rows[1:]:
        if len(row) < 2:
            continue
        key = _normalize_field_key(row[0])
        val = row[1].strip().strip('"')
        if not key or not val:
            continue
        # First wins (typical BF export order); skip duplicate keys.
        if key not in flat:
            flat[key] = val
    return flat


def _version_from_string(s: str) -> str | None:
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", s)
    return m.group(1) if m else None


def _pick_flat(flat: dict[str, str], keys: tuple[str, ...]) -> str:
    for k in keys:
        v = flat.get(k)
        if v and str(v).strip():
            return str(v).strip()
    return ""


def _apply_revision_string(rev: str, out: dict[str, str]) -> None:
    if not rev:
        return
    rl = rev.lower()
    if rl.startswith("btfl") or "betaflight" in rl:
        out.setdefault("name", "Betaflight")
        ver = _version_from_string(rev)
        if ver:
            out.setdefault("version", ver)
    elif rl.startswith("inav") or "inav" in rl:
        out.setdefault("name", "INAV")
        ver = _version_from_string(rev)
        if ver:
            out.setdefault("version", ver)
    else:
        ver = _version_from_string(rev)
        if ver:
            out.setdefault("version", ver)
        if "betaflight" in rl:
            out.setdefault("name", "Betaflight")
        elif "inav" in rl:
            out.setdefault("name", "INAV")


# Normalized keys only (after _normalize_field_key).
_FIRMWARE_KEYS = (
    "firmware_revision",
    "firmware",
    "fw_version",
    "version",
    "fw_revision",
    "firmware_rev",
    "firmware_version",
)

_BOARD_KEYS = (
    "board_name",
    "board",
    "product",
    "target",
    "board_identifier",
    "board_name_legacy",
    "mcu_id",
    "manufacturer_id",
)

# Preamble / comments / free-form BF log text (year-style e.g. 2025.12.2 or semver).
RE_BETAFLIGHT_VERSION_STRONG = re.compile(
    r"(Betaflight|BTFL)[^0-9]*([0-9]{4}\.[0-9]+\.[0-9]+|[0-9]+\.[0-9]+\.[0-9]+)",
    re.IGNORECASE,
)
RE_STM32_BOARD = re.compile(r"\b(STM32[A-Z0-9]+)\b", re.IGNORECASE)
RE_UNDERSCORE_TARGET = re.compile(
    r"\b([A-Z]{3,}_[A-Z0-9][A-Za-z0-9_]*)\b",
)
RE_FLYWOO_PRODUCT = re.compile(r"\b(FLYWOO[A-Z0-9]+)\b", re.IGNORECASE)
RE_FLWO_LINE = re.compile(r"\bFLWO\s+([A-Z][A-Z0-9]{4,})\b", re.IGNORECASE)

CSV_PREVIEW_LINE_CAP = 500


def _first_n_lines(blob: str, n: int) -> str:
    if not blob or not str(blob).strip():
        return ""
    lines = str(blob).splitlines()[:n]
    return "\n".join(lines)


def _firmware_search_corpus(headers_text: str | None, csv_text: str | None) -> str:
    """Full raw string for regex scan: headers plus first N lines of decoded CSV."""
    parts: list[str] = []
    h = (headers_text or "").strip()
    if h:
        parts.append(h)
    c = _first_n_lines((csv_text or "").strip(), CSV_PREVIEW_LINE_CAP)
    if c:
        parts.append(c)
    return "\n\n".join(parts)


def _board_token_plausible(token: str) -> bool:
    u = token.strip().upper()
    if len(u) < 5 or len(u) > 48:
        return False
    if u in frozenset({"FIELD_VALUE", "NONE", "UNKNOWN", "N_A"}):
        return False
    if u.startswith("GYRO") or u.startswith("FIELD"):
        return False
    return True


def _track_board_attempt(raw: str | None, attempts: list[str]) -> None:
    """Record a raw board string for end-of-parse fallback (priority order preserved)."""
    if not raw or not str(raw).strip():
        return
    s = str(raw).strip().strip('"')
    if s:
        attempts.append(s)


def _validate_board_candidate(candidate: str | None) -> str | None:
    """
    Accept FC-style identifiers: digits, underscores, or short all-caps slugs (HDZERO, MATEK).

    Reject flight modes, obvious non-FC tokens (BLACKBOX), whitespace-heavy strings.
    """
    if candidate is None:
        return None
    board = str(candidate).strip().strip('"')
    if not board:
        return None
    if board.startswith("_"):
        logger.info("firmware_board_candidate rejected=%s (leading_underscore)", board)
        return None
    if board.lower() in {"name", "_name"}:
        logger.info("firmware_board_candidate rejected=%s (reserved_key_fragment)", board)
        return None
    if any(ch.isspace() for ch in board):
        logger.info("firmware_board_candidate rejected=%s (whitespace)", board)
        return None
    b = board.upper()
    if len(b) < 3 or len(b) > 48:
        logger.info("firmware_board_candidate rejected=%s (length)", board)
        return None
    if not _RE_BOARD_TOKEN_CHARS.match(board):
        logger.info("firmware_board_candidate rejected=%s (charset)", board)
        return None
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,47}$", board):
        logger.info("firmware_board_candidate rejected=%s (board_id_shape)", board)
        return None
    if b in INVALID_BOARD_TOKENS or b in _BOGUS_BOARD_TOKENS:
        logger.info("firmware_board_candidate rejected=%s (denylist)", board)
        return None
    if any(c.isdigit() for c in b):
        return board
    if "_" in b:
        return board
    if len(b) <= 10 and b.isalnum() and board.isupper():
        return board
    logger.info("firmware_board_candidate rejected=%s (no digit/underscore/short-upper)", board)
    return None


def _fallback_board_score(raw: str) -> int:
    """When strict tiers fail, pick best remaining slug (higher = better)."""
    board = str(raw).strip().strip('"')
    if not board or any(ch.isspace() for ch in board):
        return 0
    if board.startswith("_") or board.lower() in {"name", "_name"}:
        return 0
    b = board.upper()
    if len(b) < 3 or len(b) > 48:
        return 0
    if b in INVALID_BOARD_TOKENS or b in _BOGUS_BOARD_TOKENS:
        return 0
    if not _RE_BOARD_TOKEN_CHARS.match(board):
        return 0
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,47}$", board):
        return 0
    score = 5
    if any(c.isdigit() for c in b):
        score += 80
    if "_" in b:
        score += 40
    if board.isupper() and len(b) <= 12:
        score += 25
    score += max(0, 20 - len(b))
    return score


def _best_board_from_attempts(attempts: list[str]) -> str | None:
    """Prefer first passing ``_validate_board_candidate``; else highest ``_fallback_board_score``."""
    uniq = list(dict.fromkeys(attempts))
    for x in uniq:
        v = _validate_board_candidate(x)
        if v:
            return v
    best_raw: str | None = None
    best_sc = 0
    for x in uniq:
        sc = _fallback_board_score(x)
        if sc > best_sc:
            best_sc = sc
            best_raw = x.strip().strip('"')
    if best_raw and best_sc >= 30:
        logger.info("firmware_board_fallback best=%s score=%s", best_raw, best_sc)
        return _validate_board_candidate(best_raw)
    return None


def _strong_raw_betaflight_version(corpus: str) -> str | None:
    m = RE_BETAFLIGHT_VERSION_STRONG.search(corpus)
    return m.group(2).strip() if m else None


def _board_from_product_patterns(corpus: str) -> str | None:
    """
    Tier 4: FC product / MCU tokens (FLWO lines, FLYWOO*, MATEK_F405, STM32*).
    """
    m = RE_FLYWOO_PRODUCT.search(corpus)
    if m:
        return m.group(1)
    m = RE_FLWO_LINE.search(corpus)
    if m:
        return m.group(1)
    m = RE_UNDERSCORE_TARGET.search(corpus)
    if m:
        cand = m.group(1)
        if _board_token_plausible(cand):
            return cand
    m = RE_STM32_BOARD.search(corpus)
    if m:
        return m.group(1).upper()
    return None


def _board_from_generic_regex(corpus: str) -> str | None:
    """Tier 5 (last): loose board|target|product adjacent token and label patterns."""
    rb = _regex_board_token(corpus)
    if rb and rb.lower() not in ("none", "unknown", "n/a"):
        return rb
    for pat in (
        r"(?i)board\s*name\s*[:,\t]\s*([^\n\r,]+)",
        r"(?i)board_name\s*[:,\t]\s*([^\n\r,]+)",
        r"(?i)H\s+product\s*:\s*([^\n\r]+)",
        r"(?i)(?:^|[\n\r])\s*product\s*[:,\t]\s*([^\n\r,]+)",
    ):
        mb = re.search(pat, corpus)
        if mb:
            cand = mb.group(1).strip().strip('"')
            if cand and cand.lower() not in ("none", "unknown", "n/a"):
                return cand
    return None


def _regex_firmware_btfl(text: str) -> tuple[str | None, str | None]:
    m = RE_BETAFLIGHT_VERSION_STRONG.search(text)
    if m:
        return "Betaflight", m.group(2).strip()
    return None, None


def _regex_firmware_inav(text: str) -> tuple[str | None, str | None]:
    m = re.search(
        r"(?:INAV)[^0-9]*([0-9]+\.[0-9]+\.[0-9]+)",
        text,
        re.IGNORECASE,
    )
    if m:
        return "INAV", m.group(1)
    m2 = re.search(
        r"(?i)(?:INAV)[^0-9]*([0-9]+\.[0-9]+(?:\.[0-9]+)?)",
        text,
    )
    if m2:
        return "INAV", m2.group(1)
    return None, None


def _regex_board_token(text: str) -> str | None:
    m = re.search(
        r"(?i)(?:board|target|product)[^A-Za-z0-9_]*([A-Za-z0-9_]{2,32})",
        text,
    )
    if m:
        cand = m.group(1).strip()
        if cand.lower() not in ("name", "revision", "id", "none", "unknown", "n", "a"):
            if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{2,47}$", cand):
                return None
            return cand
    return None


def extract_firmware_metadata(
    headers_text: str | None,
    csv_text: str | None = None,
) -> dict[str, str]:
    """
    Parse Betaflight / INAV style headers plus free-form text (preamble, ``#`` lines,
    ``H`` lines, raw CSV head). Pass optional ``csv_text`` (decoded log) so firmware
    embedded only in the first ~500 data lines is still found.

    Board resolution order: Field/Value → ``H`` product line → (version/name from
    strong BF/INAV regex) → product patterns (FLYWOO / FLWO / …) → generic regex last.
    """
    corpus = _firmware_search_corpus(headers_text, csv_text)
    if not corpus.strip():
        return {}

    h_only = (headers_text or "").strip()
    flat = _parse_headers_flat(h_only) if h_only else {}
    out: dict[str, str] = {}
    board: str | None = None
    board_attempts: list[str] = []

    rev = _pick_flat(flat, _FIRMWARE_KEYS)
    _apply_revision_string(rev, out)

    # 1) Field/Value board (highest priority)
    bv = _pick_flat(flat, _BOARD_KEYS)
    if bv and bv.lower() not in ("none", "unknown", "n/a"):
        _track_board_attempt(bv, board_attempts)
        board = _validate_board_candidate(bv)

    # H firmware revision (version only here; board from H product below)
    m_h_rev = re.search(
        r"(?im)^H\s+firmware\s+revision\s*:\s*(.+)$",
        corpus,
    )
    if m_h_rev:
        _apply_revision_string(m_h_rev.group(1).strip(), out)

    # 2) H product line
    if not board:
        m_h_prod = re.search(
            r"(?im)^H\s+product\s*:\s*(.+)$",
            corpus,
        )
        if m_h_prod:
            prod = m_h_prod.group(1).strip().strip('"')
            if prod and prod.lower() not in ("none", "unknown", "n/a"):
                _track_board_attempt(prod, board_attempts)
                board = _validate_board_candidate(prod)

    # 3) Strong Betaflight / INAV regex (name + version only)
    if "name" not in out or "version" not in out:
        n, v = _regex_firmware_btfl(corpus)
        if n and v:
            out.setdefault("name", n)
            out.setdefault("version", v)
        else:
            n2, v2 = _regex_firmware_inav(corpus)
            if n2 and v2:
                out.setdefault("name", n2)
                out.setdefault("version", v2)
            else:
                m = re.search(
                    r"(?i)\b(?:betaflight)\s+(\d+\.\d+(?:\.\d+)?)\b",
                    corpus,
                )
                if m:
                    out.setdefault("name", "Betaflight")
                    out.setdefault("version", m.group(1))
                else:
                    m2 = re.search(
                        r"(?i)\b(inav)\s+(\d+\.\d+(?:\.\d+)?)\b",
                        corpus,
                    )
                    if m2:
                        out.setdefault("name", "INAV")
                        out.setdefault("version", m2.group(2))
                    else:
                        m3 = re.search(
                            r"(?i)\bbtfl\s+(\d+\.\d+(?:\.\d+)?)\b",
                            corpus,
                        )
                        if m3:
                            out.setdefault("name", "Betaflight")
                            out.setdefault("version", m3.group(1))

    # 4) Product-style board patterns (FLYWOO / FLWO / underscore / STM32)
    if not board:
        raw_pat = _board_from_product_patterns(corpus)
        _track_board_attempt(raw_pat, board_attempts)
        board = _validate_board_candidate(raw_pat)

    # 5) Generic board regex (only if nothing better matched)
    if not board:
        raw_gen = _board_from_generic_regex(corpus)
        _track_board_attempt(raw_gen, board_attempts)
        board = _validate_board_candidate(raw_gen)

    if not board and board_attempts:
        board = _best_board_from_attempts(board_attempts)

    raw_v = _strong_raw_betaflight_version(corpus)
    logger.info(
        "firmware_extract RAW MATCH version=%s board=%s",
        raw_v,
        board,
    )
    if raw_v:
        out.setdefault("version", raw_v)
        out.setdefault("name", "Betaflight")

    if board:
        out["board"] = board

    result = {k: v for k, v in out.items() if isinstance(v, str) and v.strip()}
    logger.info(
        "firmware_extract result name=%s version=%s board=%s",
        result.get("name"),
        result.get("version"),
        result.get("board"),
    )
    return result


def extract_firmware_from_bbl_binary(file_path: str) -> dict[str, str]:
    """
    Scan the first 100KB of a raw ``.bbl`` for printable strings and run the same
    metadata regex/parse paths as decoded headers/CSV. Used when firmware exists
    only in the binary log, not in ``headers.csv`` or decoded CSV.
    """
    try:
        with open(file_path, "rb") as f:
            data = f.read(100000)  # first 100KB
    except OSError:
        return {}

    try:
        text = data.decode("latin-1", errors="ignore")
    except Exception:
        return {}

    strings = re.findall(r"[ -~]{6,}", text)
    corpus = "\n".join(strings)
    return extract_firmware_metadata(corpus)
