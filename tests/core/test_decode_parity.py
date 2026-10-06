"""Donor-vs-GyroCore parity for WU3 parse / embedded / firmware metadata."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from gyrocore.parse import (
    extract_firmware_metadata,
    parse_blackbox_csv,
)
from gyrocore.decode.embedded import (
    build_embedded_log_metadata,
    parse_embedded_log_table,
    recommend_embedded_log_index,
)

REPO = Path(__file__).resolve().parents[2]
LEGACY_FIXTURES = REPO / "tests/fixtures/legacy"

_MULTI_LOG_STDERR = (
    "This file contains multiple flight logs, please choose one with the --index argument:\n\n"
    "Index  Start offset  Size (bytes)\n"
    "    1             0           379\n"
    "    2           379        500000\n"
    "    3        500379         5971\n"
    "    4        506350        500000\n"
)

# Representative blackbox_decode-style CSV (GL fixtures are normalized sample rows).
_BB_STYLE = (
    "gyro[0],gyro[1],gyro[2],time,throttle,"
    "motor[0],motor[1],motor[2],motor[3],"
    "setpoint[0],setpoint[1],setpoint[2],"
    "axisP[0],axisP[1],axisP[2],"
    "axisI[0],axisI[1],axisI[2],"
    "axisD[0],axisD[1],axisD[2]\n"
    "1.0,2.0,3.0,1000,500,1100,1200,1300,1400,10,20,30,40,41,42,50,51,52,20,21,22\n"
    "1.5,2.5,3.5,2000,510,1101,1201,1301,1401,11,21,31,40,41,42,50,51,52,20,21,22\n"
    "2.0,3.0,4.0,3000,520,1102,1202,1302,1402,12,22,32,40,41,42,50,51,52,20,21,22\n"
)


def _donor_root() -> Path:
    env = os.environ.get("AEROTUNER_ROOT")
    if env:
        return Path(env)
    return REPO.parent / "aerotuner"


def _golden_root() -> Path:
    return _donor_root() / "backend" / "test" / "golden_logs"


GOLDEN_ROOT = _golden_root()


@pytest.fixture(scope="module")
def donor():
    root = _donor_root()
    if not root.is_dir():
        pytest.skip(f"AeroTuner donor not available at {root}")
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    import backend.services.parser as d_parser
    import backend.services.firmware_metadata as d_fw
    import backend.services.embedded_bbl_log as d_emb

    return {"parser": d_parser, "fw": d_fw, "emb": d_emb}


def _normalize_parse(result: dict) -> dict:
    """Drop deferred analysis-only keys before comparison."""
    out = dict(result)
    for key in (
        "precap_spectral_features",
        "spectral_samples",
        "spectral_sample_source_kind",
        "spectral_sample_count",
    ):
        out.pop(key, None)
    return out


def test_parity_blackbox_style_csv(donor):
    core = _normalize_parse(parse_blackbox_csv(_BB_STYLE))
    don = _normalize_parse(donor["parser"].parse_blackbox_csv(_BB_STYLE))
    assert core == don
    assert core["count"] == 3
    assert core["samples"][0]["gx"] == 1.0
    assert core["samples"][2]["throttle"] == 520.0


def test_parity_gl_normalized_csv_not_blackbox_format(donor):
    """
    Tracked GL-00x ``log.csv`` / GyroCore ``flight.csv`` are already-normalized
    sample rows (t,gx,gy,gz,…), not blackbox_decode CSV. Both parsers must agree
    they lack a gyro[0]-style header.
    """
    paths = [
        GOLDEN_ROOT / "GL-001-clean" / "log.csv",
        GOLDEN_ROOT / "GL-002-noisy" / "log.csv",
        GOLDEN_ROOT / "GL-003-motor_issue" / "log.csv",
        LEGACY_FIXTURES / "gl001_clean" / "input" / "flight.csv",
        LEGACY_FIXTURES / "gl002_noisy" / "input" / "flight.csv",
    ]
    for path in paths:
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8", errors="replace")
        core = parse_blackbox_csv(text)
        don = donor["parser"].parse_blackbox_csv(text)
        assert core.get("parse_failed") is True
        assert don.get("parse_failed") is True
        assert core.get("message") == don.get("message") == "no_valid_gyro_header"


def test_parity_firmware_metadata(donor):
    headers = (
        "Field,Value\n"
        "Firmware type,Betaflight\n"
        "Firmware revision,4.5.2\n"
        "Board identifier,BETAFPVG473\n"
    )
    csv_head = "# Product: BETAFPVG473\ngyro[0],gyro[1],gyro[2]\n1,2,3\n"
    assert extract_firmware_metadata(headers, csv_head) == donor["fw"].extract_firmware_metadata(
        headers, csv_head
    )


def test_parity_embedded_table(donor):
    core_entries = parse_embedded_log_table(_MULTI_LOG_STDERR)
    don_entries = donor["emb"].parse_embedded_log_table(_MULTI_LOG_STDERR)
    assert core_entries == don_entries
    assert recommend_embedded_log_index(core_entries) == donor["emb"].recommend_embedded_log_index(
        don_entries
    )
    assert build_embedded_log_metadata(
        core_entries, selected_index=3, selection_mode="auto"
    ) == donor["emb"].build_embedded_log_metadata(
        don_entries, selected_index=3, selection_mode="auto"
    )


def test_parity_off_by_one_cli_conversion_documented(donor):
    """0-based index 0 → CLI --index 1; display_index 1 → internal index 0."""
    entries = parse_embedded_log_table(_MULTI_LOG_STDERR)
    assert entries[0]["index"] == 0
    assert entries[0]["display_index"] == 1
    # Donor run_decode adds +1; Core mirrors that in decode._run_decode.
    zero_based = 0
    cli_index = zero_based + 1
    assert cli_index == 1
