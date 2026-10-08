#!/usr/bin/env bash
# Minimal CI integrity runner for WU5–WU13 frozen contracts.
# Prefer existing pytest targets; do not invent a second framework.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

export PYTHONPATH="${ROOT}:${ROOT}/core${PYTHONPATH:+:$PYTHONPATH}"

# WU7/WU8 BBL end-to-end parity skips without the decoder; fail instead of
# reporting "integrity OK" with those tests silently skipped.
if ! command -v blackbox_decode >/dev/null 2>&1; then
    echo "ERROR: blackbox_decode not on PATH (required for WU7/WU8 BBL parity)." >&2
    echo "Build it from third_party/betaflight/blackbox-tools out of tree." >&2
    exit 1
fi

echo "== WU0 goldens / parity harness =="
python3 -m pytest tests/test_parity_golden.py tests/test_parity_harness.py

echo "== WU7 CHIRP / System-ID parity =="
python3 -m pytest tests/core/chirp

echo "== WU8 Autotune parity =="
python3 -m pytest tests/core/autotune

echo "== WU9 simplified-tuning firmware parity =="
python3 -m pytest tests/core/betaflight

echo "== WU10 staged safety / bypass =="
python3 -m pytest tests/core/safety tests/core/cli/test_invariants.py

echo "== WU11 CLI goldens + authorize =="
python3 -m pytest tests/core/cli

echo "== WU13 no-actionable-path architectural guards =="
python3 -m pytest tests/filter_evidence/test_no_actionable_path.py

echo "== Full-frame decode across mode events (patched blackbox_decode) =="
python3 -m pytest tests/core/test_decode_full_frame.py

echo "== Vendored Betaflight trees must remain untouched by tests =="
git diff --exit-code -- third_party/betaflight
test -z "$(git status --porcelain --untracked-files=all -- third_party/betaflight)"

echo "== Provenance manifest present =="
test -f docs/upstream/PROVENANCE_MANIFEST.md
test -f docs/upstream/FPVPIDLAB_SELECTIVE_AUDIT.md
test -f third_party/fpvpidlab/UPSTREAM_COMMIT
test -f third_party/fpvpidlab/LICENSE

echo "== Package license metadata matches root LICENSE =="
python3 -m pytest tests/test_license_metadata.py

echo "integrity OK"
