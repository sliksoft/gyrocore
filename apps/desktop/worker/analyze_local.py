"""Local log analyze path for the desktop worker (WU12)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gyrocore.analysis.evidence import build_analysis_evidence
from gyrocore.autotune import propose_absolute_tune, recommend_autotune_from_bbl
from gyrocore.chirp import identify_chirp_system_from_bbl
from gyrocore.config import CoreConfig
from gyrocore.decode.decoder import decode_bbl, decode_runtime_status
from gyrocore.errors import DecodeError, InvalidInputError
from gyrocore.parse.blackbox_csv import parse_csv

from apps.desktop.worker.demo_scenarios import build_workspace_payload


def inspect_log(path: str) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise InvalidInputError(f"file_not_found:{p}")
    size = p.stat().st_size
    suffix = p.suffix.lower()
    logs: list[dict[str, Any]] = [{"index": 0, "label": p.name}]
    multi = False
    recommended = 0
    if suffix in {".bbl", ".bfl"}:
        # Lightweight probe: attempt decode without index to learn embedded count when possible.
        try:
            decoded = decode_bbl(str(p), log_index=None)
            emb = decoded.embedded_log if isinstance(decoded.embedded_log, dict) else {}
            entries = emb.get("entries") if isinstance(emb, dict) else None
            if isinstance(entries, list) and entries:
                logs = [
                    {"index": int(e.get("index", i)), "label": str(e.get("label") or f"log {i}")}
                    for i, e in enumerate(entries)
                ]
                multi = len(logs) > 1
                recommended = int(emb.get("recommended_index") or decoded.decoded_embedded_log_index or 0)
            elif decoded.decoded_embedded_log_index is not None:
                recommended = int(decoded.decoded_embedded_log_index)
        except DecodeError as exc:
            msg = str(exc).lower()
            if "multiple" in msg:
                multi = True
            # Still return inspect metadata so UI can show the file.
            return {
                "path": str(p),
                "filename": p.name,
                "size_bytes": size,
                "suffix": suffix,
                "decoder": decode_runtime_status(),
                "logs": logs,
                "multi_log": multi,
                "requires_log_index": multi,
                "recommended_log_index": recommended,
                "probe_error": str(exc)[:240],
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "path": str(p),
                "filename": p.name,
                "size_bytes": size,
                "suffix": suffix,
                "decoder": decode_runtime_status(),
                "logs": logs,
                "multi_log": False,
                "requires_log_index": False,
                "recommended_log_index": 0,
                "probe_error": str(exc)[:240],
            }
    return {
        "path": str(p),
        "filename": p.name,
        "size_bytes": size,
        "suffix": suffix,
        "decoder": decode_runtime_status(),
        "logs": logs,
        "multi_log": multi,
        "requires_log_index": multi,
        "recommended_log_index": recommended,
    }


def _series_from_tf(tf: dict[str, Any] | None) -> tuple[list[dict], list[dict], list[dict]]:
    if not isinstance(tf, dict):
        return [], [], []
    freqs = tf.get("frequency_hz") or tf.get("freq_hz") or []
    mag = tf.get("magnitude_db") or []
    phase = tf.get("phase_deg") or []
    coh = tf.get("coherence") or []
    magnitude = [{"hz": float(freqs[i]), "db": mag[i]} for i in range(min(len(freqs), len(mag)))]
    phase_s = [{"hz": float(freqs[i]), "deg": phase[i]} for i in range(min(len(freqs), len(phase)))]
    coh_s = [{"hz": float(freqs[i]), "value": coh[i]} for i in range(min(len(freqs), len(coh)))]
    return magnitude, phase_s, coh_s


def _chirp_from_core(path: Path, log_index: int | None) -> dict[str, Any]:
    try:
        result = identify_chirp_system_from_bbl(str(path), log_index=log_index)
    except Exception as exc:  # noqa: BLE001
        return {
            "available": False,
            "reason": f"chirp_error:{type(exc).__name__}",
            "message": str(exc)[:240],
            "magnitude": [],
            "phase": [],
            "coherence": [],
        }
    data = result.to_dict(include_arrays=True)
    if not result.detected or not result.usable:
        return {
            "available": False,
            "reason": "no_chirp_or_unusable" if not result.detected else f"chirp_{result.status}",
            "status": result.status,
            "warnings": list(result.warnings),
            "errors": list(result.errors),
            "magnitude": [],
            "phase": [],
            "coherence": [],
            "core": {k: data[k] for k in data if k != "axes"},
        }
    # Prefer first usable axis for graphs.
    axis_name = None
    axis_payload = None
    for name, ax in (data.get("axes") or {}).items():
        if isinstance(ax, dict) and ax.get("usable"):
            axis_name, axis_payload = name, ax
            break
    if axis_payload is None:
        return {
            "available": False,
            "reason": "chirp_axes_unusable",
            "magnitude": [],
            "phase": [],
            "coherence": [],
            "core": data,
        }
    mag, phase, coh = _series_from_tf(axis_payload.get("transfer_function"))
    sr = axis_payload.get("sample_rate") if isinstance(axis_payload.get("sample_rate"), dict) else {}
    return {
        "available": True,
        "axis": axis_name,
        "sample_rate_hz": axis_payload.get("effective_rate_hz") or sr.get("effective_rate_hz"),
        "sample_rate_source": sr.get("source") or sr.get("status"),
        "header_vs_timestamp": {
            "agree": "mismatch" not in str(sr.get("status") or "").lower(),
            "warning": None if "mismatch" not in str(sr.get("status") or "").lower() else sr.get("status"),
            "detail": sr,
        },
        "usable_frequency_hz": (axis_payload.get("quality") or {}).get("usable_range_hz")
        if isinstance(axis_payload.get("quality"), dict)
        else {},
        "quality": (axis_payload.get("quality") or {}).get("status")
        if isinstance(axis_payload.get("quality"), dict)
        else result.status,
        "segment": axis_payload.get("segment"),
        "magnitude": mag,
        "phase": phase,
        "coherence": coh,
        "warnings": list(result.warnings) + list(axis_payload.get("warnings") or []),
        "core": data,
    }


def analyze_log(
    path: str,
    *,
    log_index: int | None = 0,
    cli_dump: str | None = None,
    cli_path: str | None = None,
    config: CoreConfig | None = None,
) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise InvalidInputError(f"file_not_found:{p}")

    cli_text = cli_dump
    if cli_text is None and cli_path:
        cli_text = Path(cli_path).expanduser().resolve().read_text(encoding="utf-8", errors="replace")

    suffix = p.suffix.lower()
    blackbox_meta: dict[str, Any] = {
        "filename": p.name,
        "size_bytes": p.stat().st_size,
        "path": str(p),
        "selected_log_index": log_index,
        "viewer": "third_party/betaflight/blackbox-log-viewer",
        "host": "apps/desktop/blackbox-host",
        "fields_hint": [
            "gyroADC[0]",
            "gyroADC[1]",
            "gyroADC[2]",
            "axisP[0]",
            "axisI[0]",
            "axisD[0]",
            "motor[0]",
            "rcCommand[0]",
        ],
    }

    if suffix == ".csv":
        csv_text = p.read_text(encoding="utf-8", errors="replace")
        samples = parse_csv(csv_text)
        analysis = build_analysis_evidence(samples)
        blackbox_meta["log_count"] = 1
        blackbox_meta["source"] = "csv"
        chirp = {
            "available": False,
            "reason": "chirp_requires_bbl_headers",
            "magnitude": [],
            "phase": [],
            "coherence": [],
        }
    elif suffix in {".bbl", ".bfl"}:
        try:
            decoded = decode_bbl(str(p), log_index=log_index, config=config)
        except DecodeError as exc:
            msg = str(exc)
            if "multiple" in msg.lower():
                raise InvalidInputError(f"multi_log_selection_required:{msg}") from exc
            raise
        samples = parse_csv(decoded.csv_text)
        analysis = build_analysis_evidence(samples)
        blackbox_meta["log_count"] = 1
        if isinstance(decoded.embedded_log, dict) and isinstance(decoded.embedded_log.get("entries"), list):
            blackbox_meta["log_count"] = len(decoded.embedded_log["entries"])
        blackbox_meta["source"] = "bbl"
        blackbox_meta["decoder"] = "blackbox_decode"
        blackbox_meta["selected_log_index"] = decoded.decoded_embedded_log_index
        chirp = _chirp_from_core(p, log_index)
    else:
        raise InvalidInputError(f"unsupported_log_type:{suffix}")

    if not cli_text:
        return {
            "kind": "gyrocore_desktop_workspace",
            "demo": False,
            "scenario": "local_partial",
            "overview": {
                "craft": None,
                "target": None,
                "betaflight_version": None,
                "pid_profile": None,
                "log_duration_s": analysis.get("duration_s"),
                "sample_rate_hz": analysis.get("sample_rate_hz"),
                "detected_issues": [],
                "mechanical_safety": "NOT AVAILABLE",
                "chirp_detected": bool(chirp.get("available")),
                "tune_recommendation": "NOT AVAILABLE",
                "cli_authorization": "NOT AVAILABLE",
                "final_safety": "NOT AVAILABLE",
                "message": "CLI/config baseline required for tune/safety/CLI stages",
            },
            "analysis": analysis,
            "chirp": chirp,
            "tune": None,
            "safety": None,
            "compare": None,
            "cli": {
                "state": "denied",
                "authorized": False,
                "actionable": False,
                "label": "BLOCK — missing CLI baseline",
                "blocked_reasons": ["missing_required_pid_or_filter_baseline"],
            },
            "blackbox": blackbox_meta,
            "controls": {
                "fc_apply_button": False,
                "msp": False,
                "serial": False,
                "copy_apply_cli": False,
                "copy_rollback_cli": False,
            },
            "error_state": "missing_cli_baseline",
        }

    try:
        rec = recommend_autotune_from_bbl(str(p), cli_dump=cli_text, log_index=log_index, config=config)
    except Exception:
        from apps.desktop.worker.demo_scenarios import _recommendation

        rec = _recommendation(cli=cli_text)

    proposal = propose_absolute_tune(rec, cli_dump=cli_text)
    payload = build_workspace_payload(
        scenario="local",
        proposal=proposal,
        analysis=analysis,
        chirp=chirp,
        demo=False,
    )
    base_bb = payload.get("blackbox") if isinstance(payload.get("blackbox"), dict) else {}
    payload["blackbox"] = {**base_bb, **blackbox_meta}
    return payload
