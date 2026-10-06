# GyroCore Core parity (WU0)

## Why parity exists

GyroCore extracts AeroTuner’s proven analysis/tuning/safety engine into an importable Python Core.
Before moving production modules, WU0 freezes the **legacy DOMAIN oracle** so later work units can prove:

```
OLD AeroTuner behavior  ==  NEW GyroCore Core behavior
```

for safety-critical and tuning-critical fields.

## What the legacy oracle is

The oracle invokes the **existing** AeroTuner implementation (read-only donor checkout):

- Entrypoint: `backend.routes.analyze._build_response`
- Donor root: `AEROTUNER_ROOT` (default: sibling `../aerotuner`)
- AI disabled: `OPENROUTER_API_KEY` unset, `GYROCORE_AI_EXPLANATIONS_ENABLED=0`

WU0 does **not** reimplement analysis logic. The NEW Core side is `NOT_IMPLEMENTED`.

## Fixture selection

See `tests/fixtures/legacy/FIXTURE_INVENTORY.md`.

| Fixture | Role | Mode |
|---------|------|------|
| `gl001_clean` | Clean/healthy CSV | live legacy |
| `gl002_noisy` | Noisy/problem CSV | live legacy |
| `gl001_with_cli` | CSV + tracked whoop CLI | live legacy |
| `whoop75_cli_snapshot` | CLI + run snapshot | snapshot partial; **BLOCKED_REAL_BBL_FIXTURE** |

Real BBL candidates listed in AeroTuner’s `real_validation_manifest.json` were **missing** from `backend/uploads/` at WU0 time. No BBL pairing was invented.

## How to run golden tests

```bash
cd /home/sliksoft/GyroCore
export AEROTUNER_ROOT=/home/sliksoft/aerotuner
/home/sliksoft/aerotuner/.venv/bin/python -m pytest tests/test_parity_harness.py tests/test_parity_golden.py
```

Harness unit tests do not need AeroTuner for most cases; golden tests do.

## How to regenerate oracle files

Normal pytest **never** rewrites goldens. Explicitly run:

```bash
AEROTUNER_ROOT=/home/sliksoft/aerotuner \
  /home/sliksoft/aerotuner/.venv/bin/python tools/update_legacy_golden.py

# or one fixture:
... python tools/update_legacy_golden.py gl001_clean
```

Review the printed CHANGED/unchanged list and git diff before committing.

## Compared fields (DOMAIN projection)

Includes: analysis status, valid_log, flight selection indices, quality status/grade/score,
problem types/severities, key metrics, resonance, eRPM, tuning mode, PID/filter summaries,
mechanical safety, tuning_output_safety, authoritative CLI, tuning decision, ResultView hero/cards.

## Ignored / nondeterministic

session_id, job_id, timestamps, cache metadata, pipeline timings, URLs, ownership, user_id,
AI prose, temp filesystem paths.

Policies are centralized in `tests/golden/normalize.py`:
`EXACT` | `NORMALIZED_EXACT` | `TOLERANCE` | `IGNORED_NONDETERMINISTIC`.

## Safety invariants

Enforced by `tests/golden/safety.py`:

1. No actionable CLI unless `tuning_output_safety.cli_actionable` allows it.
2. Mechanical safety present on tuning results.
3. Final `tuning_output_safety` present.
4. Decision-engine CLI cannot be authoritative.
5. AI disabled for golden oracle.
6. Missing final safety fails.
7. Blocked/diagnostic status cannot be actionable.

## Connecting future GyroCore Core

1. Implement `gyrocore.analyze(...)` in `core/gyrocore/` (not in WU1).
2. Replace `NewCoreNotImplemented` with a real adapter that returns the **same DOMAIN projection**.
3. Keep frozen `expected/legacy_domain_result.json` as the OLD side.
4. Add NEW-vs-OLD compare using the same `compare_projections` contract — do not call legacy on both sides.

## WU1 foundations

WU1 adds stdlib-only request/result/safety/config/error types under `core/gyrocore/`.
It does **not** migrate analysis/tuning/decode and must not rewrite WU0 golden files.

Real BBL+matching CLI live oracle remains: **BLOCKED_REAL_BBL_FIXTURE**
(required before full-Core parity / WU9; not solved by WU1).
