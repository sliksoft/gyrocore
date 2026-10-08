#!/usr/bin/env python3
"""GyroCore desktop worker — JSON Lines over stdin/stdout (WU12).

No HTTP. No MSP. No serial. Calls Python Core only.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

# Allow `python apps/desktop/worker/gyrocore_worker.py` from repo root.
_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))
_CORE = _REPO / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from gyrocore.errors import DecodeError, GyroCoreError, InvalidInputError  # noqa: E402

from apps.desktop.worker.analyze_local import analyze_log, inspect_log  # noqa: E402
from apps.desktop.worker.demo_scenarios import DEMO_SCENARIOS, run_demo  # noqa: E402

PROTOCOL_VERSION = 1


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"id": req_id, "ok": True, "protocol": PROTOCOL_VERSION, "result": result}


def _err(req_id: Any, code: str, message: str, *, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": req_id,
        "ok": False,
        "protocol": PROTOCOL_VERSION,
        "error": {"code": code, "message": message},
    }
    if details is not None:
        body["error"]["details"] = details
    return body


def handle(request: dict[str, Any]) -> dict[str, Any]:
    req_id = request.get("id")
    op = str(request.get("op") or "").strip()
    params = request.get("params") if isinstance(request.get("params"), dict) else {}

    try:
        if op == "ping":
            return _ok(req_id, {"pong": True, "worker": "gyrocore_worker", "protocol": PROTOCOL_VERSION})
        if op == "list_demos":
            return _ok(req_id, {"scenarios": list(DEMO_SCENARIOS)})
        if op == "demo":
            scenario = str(params.get("scenario") or "pass")
            return _ok(req_id, run_demo(scenario))
        if op == "inspect":
            path = str(params.get("path") or "")
            return _ok(req_id, inspect_log(path))
        if op == "analyze":
            path = str(params.get("path") or "")
            log_index = params.get("log_index")
            if log_index is not None:
                log_index = int(log_index)
            return _ok(
                req_id,
                analyze_log(
                    path,
                    log_index=log_index,
                    cli_dump=params.get("cli_dump"),
                    cli_path=params.get("cli_path"),
                ),
            )
        return _err(req_id, "unknown_op", f"unsupported op: {op}")
    except InvalidInputError as exc:
        return _err(req_id, "invalid_input", str(exc))
    except DecodeError as exc:
        return _err(req_id, "decode_error", str(exc))
    except GyroCoreError as exc:
        return _err(req_id, "gyrocore_error", str(exc))
    except ValueError as exc:
        return _err(req_id, "value_error", str(exc))
    except Exception as exc:  # noqa: BLE001
        return _err(
            req_id,
            "internal_error",
            f"{type(exc).__name__}: {exc}",
            details=traceback.format_exc(limit=8),
        )


def main() -> int:
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stdout.write(json.dumps(_err(None, "bad_json", str(exc))) + "\n")
            sys.stdout.flush()
            continue
        if not isinstance(request, dict):
            sys.stdout.write(json.dumps(_err(None, "bad_request", "request must be object")) + "\n")
            sys.stdout.flush()
            continue
        sys.stdout.write(json.dumps(handle(request), default=str) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
