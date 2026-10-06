"""WU3 decode / log-ingest unit tests."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

import gyrocore
from gyrocore import CoreConfig, DecodeError, InvalidInputError
from gyrocore.decode import (
    decode_bbl,
    decode_runtime_status,
    inspect_log,
    parse_embedded_log_table,
    recommend_embedded_log_index,
    resolve_blackbox_decode,
    validate_bbl_path,
)
from gyrocore.parse import extract_firmware_metadata, parse_blackbox_csv

FORBIDDEN_TOP_LEVEL = {
    "fastapi",
    "starlette",
    "redis",
    "sqlalchemy",
    "jwt",
    "jose",
    "passlib",
    "uvicorn",
}

_MULTI_LOG_STDERR = (
    "This file contains multiple flight logs, please choose one with the --index argument:\n\n"
    "Index  Start offset  Size (bytes)\n"
    "    1             0           379\n"
    "    2           379        500000\n"
    "    3        500379         5971\n"
    "    4        506350        500000\n"
)

_CSV_HDR = "gyro[0],gyro[1],gyro[2],time\n"
_CSV_BODY = "1,2,3,0\n" * 30


def _fake_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "blackbox_decode"
    exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    exe.chmod(0o755)
    return exe


def test_package_exports_decode_parse():
    assert hasattr(gyrocore, "decode")
    assert hasattr(gyrocore, "parse")
    assert not hasattr(gyrocore.decode, "generate_cli")


def test_locator_explicit_path(tmp_path: Path):
    exe = _fake_exe(tmp_path)
    cfg = CoreConfig(blackbox_decode_path=str(exe))
    assert resolve_blackbox_decode(cfg) == exe.resolve()


def test_locator_path_lookup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    exe = _fake_exe(tmp_path)
    monkeypatch.setenv("PATH", str(tmp_path))
    # Clear explicit path; which() will find our fake if named blackbox_decode
    cfg = CoreConfig(blackbox_decode_path=None)
    # shutil.which searches PATH — ensure our exe name matches
    found = resolve_blackbox_decode(cfg)
    assert found.name == "blackbox_decode"


def test_locator_missing_binary(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PATH", "")
    cfg = CoreConfig(blackbox_decode_path=None)
    with pytest.raises(DecodeError):
        resolve_blackbox_decode(cfg)
    cfg2 = CoreConfig(blackbox_decode_path="/no/such/blackbox_decode_bin")
    with pytest.raises(DecodeError):
        resolve_blackbox_decode(cfg2)


def test_trusted_arbitrary_local_path(tmp_path: Path):
    # Path outside any AeroTuner uploads root — must be accepted by Core.
    bbl = tmp_path / "user_flights" / "race001.BBL"
    bbl.parent.mkdir(parents=True)
    bbl.write_bytes(b"\x00" * 128 + b"Betaflight blackbox")
    resolved = validate_bbl_path(bbl, CoreConfig.defaults(), sniff_content=True)
    assert resolved == bbl.resolve()


def test_missing_file(tmp_path: Path):
    with pytest.raises(InvalidInputError):
        validate_bbl_path(tmp_path / "missing.BBL", CoreConfig.defaults())


def test_upload_root_not_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    exe = _fake_exe(tmp_path)
    bbl = tmp_path / "outside_uploads.bbl"
    bbl.write_bytes(b"x" * 64)

    def fake_run(cmd, *, stdout, **_kwargs):
        stdout.write(_CSV_HDR + _CSV_BODY)
        stdout.flush()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = CoreConfig(blackbox_decode_path=str(exe), allow_arbitrary_local_paths=True)
    result = decode_bbl(bbl, config=cfg)
    assert "gyro[0]" in result.csv_text
    # Must not create sibling CSV next to source
    assert not (tmp_path / "outside_uploads.bbl.csv").exists()


def test_subprocess_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    exe = _fake_exe(tmp_path)
    bbl = tmp_path / "hang.bbl"
    bbl.write_bytes(b"x" * 64)

    def fake_run(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd=["blackbox_decode"], timeout=1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = CoreConfig(blackbox_decode_path=str(exe), decode_timeout_s=1.0)
    with pytest.raises(DecodeError, match="decode_timeout"):
        decode_bbl(bbl, config=cfg)


def test_decoder_nonzero_exit_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    exe = _fake_exe(tmp_path)
    bbl = tmp_path / "bad.bbl"
    bbl.write_bytes(b"x" * 64)

    def fake_run(cmd, *, stdout, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "decode failed")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = CoreConfig(blackbox_decode_path=str(exe))
    with pytest.raises(DecodeError, match="empty_csv"):
        decode_bbl(bbl, config=cfg)


def test_decoded_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    exe = _fake_exe(tmp_path)
    bbl = tmp_path / "big.bbl"
    bbl.write_bytes(b"x" * 64)

    def fake_run(cmd, *, stdout, **_kwargs):
        stdout.write(_CSV_HDR + ("1,2,3,0\n" * 5000))
        stdout.flush()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = CoreConfig(blackbox_decode_path=str(exe), max_decoded_csv_bytes=200)
    with pytest.raises(DecodeError, match="decoded_csv_too_large"):
        decode_bbl(bbl, config=cfg)


def test_csv_parser_blackbox_style():
    text = (
        "gyro[0],gyro[1],gyro[2],time,throttle,motor[0],motor[1],motor[2],motor[3]\n"
        "1.0,2.0,3.0,100,500,1000,1001,1002,1003\n"
        "1.5,2.5,3.5,200,510,1000,1001,1002,1003\n"
    )
    parsed = parse_blackbox_csv(text)
    assert not parsed.get("parse_failed")
    assert parsed["count"] == 2
    assert parsed["samples"][0]["gx"] == 1.0
    assert parsed["samples"][1]["t"] == 200


def test_malformed_csv():
    assert parse_blackbox_csv("not,a,log\n1,2,3\n")["parse_failed"] is True
    assert parse_blackbox_csv("")["parse_failed"] is True


def test_firmware_header_metadata():
    headers = "H Product: BETAFPVG473\nH Firmware revision: Betaflight 4.5.0\n"
    csv = "gyro[0],gyro[1],gyro[2]\n1,2,3\n"
    fw = extract_firmware_metadata(headers, csv)
    assert fw.get("version") == "4.5.0" or "4.5" in str(fw.get("version") or "")
    assert "board" in fw or "name" in fw or fw.get("version")


def test_multilog_discovery_and_recommendation():
    entries = parse_embedded_log_table(_MULTI_LOG_STDERR)
    assert len(entries) == 4
    assert entries[0]["index"] == 0
    assert entries[0]["display_index"] == 1
    assert recommend_embedded_log_index(entries) == 3  # largest usable, tie-break high


def test_explicit_log_selection_and_off_by_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    exe = _fake_exe(tmp_path)
    bbl = tmp_path / "multi.bbl"
    bbl.write_bytes(b"x" * 64)
    cli_indices: list[int | None] = []

    def fake_run(cmd, *, stdout, **_kwargs):
        idx = None
        if "--index" in cmd:
            # CLI is 1-based
            idx = int(cmd[cmd.index("--index") + 1])
        cli_indices.append(idx)
        stdout.write(_CSV_HDR + _CSV_BODY)
        stdout.flush()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = CoreConfig(blackbox_decode_path=str(exe))
    # Request 0-based index 1 → CLI must receive --index 2
    out = decode_bbl(bbl, log_index=1, config=cfg)
    assert out.decoded_embedded_log_index == 1
    assert cli_indices == [2]


def test_auto_multilog_selects_recommended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    exe = _fake_exe(tmp_path)
    bbl = tmp_path / "multi.bbl"
    bbl.write_bytes(b"x" * 64)
    calls: list[int | None] = []

    def fake_run(cmd, *, stdout, **_kwargs):
        idx = int(cmd[cmd.index("--index") + 1]) - 1 if "--index" in cmd else None
        calls.append(idx)
        if idx is None:
            return subprocess.CompletedProcess(cmd, 1, "", _MULTI_LOG_STDERR)
        stdout.write(_CSV_HDR + _CSV_BODY)
        stdout.flush()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = CoreConfig(blackbox_decode_path=str(exe))
    out = decode_bbl(bbl, config=cfg)
    assert calls == [None, 3]
    assert out.decoded_embedded_log_index == 3
    assert out.embedded_log["recommended_embedded_log_index"] == 3


def test_invalid_embedded_log_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    exe = _fake_exe(tmp_path)
    bbl = tmp_path / "multi.bbl"
    bbl.write_bytes(b"x" * 64)
    cfg = CoreConfig(blackbox_decode_path=str(exe))
    with pytest.raises(InvalidInputError):
        decode_bbl(bbl, log_index=-1, config=cfg)

    def fake_run(cmd, *, stdout, **_kwargs):
        return subprocess.CompletedProcess(cmd, 1, "", "no such index")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(DecodeError):
        decode_bbl(bbl, log_index=99, config=cfg)


def test_inspect_log_without_analysis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    exe = _fake_exe(tmp_path)
    bbl = tmp_path / "flight.bbl"
    bbl.write_bytes(b"x" * 64)

    def fake_run(cmd, *, stdout, **_kwargs):
        stdout.write(_CSV_HDR + _CSV_BODY)
        stdout.flush()
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = CoreConfig(blackbox_decode_path=str(exe))
    info = inspect_log(bbl, config=cfg)
    assert info.decode_ok is True
    assert info.sample_count == 30
    assert info.exists is True


def test_no_aerotuner_runtime_dependency_in_production():
    root = Path(__file__).resolve().parents[2] / "core" / "gyrocore"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("backend"), path
                assert "aerotuner" not in node.module, path
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("backend"), path
                    assert "aerotuner" not in alias.name, path
    # WU3 packages must not hard-code donor checkout paths.
    for sub in ("decode", "parse"):
        for path in (root / sub).rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if "/home/sliksoft/aerotuner" in line and "Adapted from" not in line:
                    pytest.fail(f"hard-coded donor path in {path}: {line}")


def test_forbidden_dependency_boundary():
    before = set(sys.modules)
    importlib.reload(gyrocore.decode)
    importlib.reload(gyrocore.parse)
    after = set(sys.modules)
    newly = after - before
    offenders = sorted(n for n in newly if n.split(".")[0] in FORBIDDEN_TOP_LEVEL)
    assert offenders == []


def test_decode_runtime_status():
    status = decode_runtime_status(CoreConfig.defaults())
    assert "ready" in status
