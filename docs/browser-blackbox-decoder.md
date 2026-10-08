# Browser Blackbox decoder

PWA-first decode path for GyroCore (`https://app.gyrocore.dev/`). Logs stay on-device; no upload, no localhost engine, no Tauri requirement in browser mode.

## Architecture

```
Browser File (File / ArrayBuffer)
        ↓
decodeBlackboxFile / decodeBlackboxBuffer  (apps/desktop/gyrocore-app/src/decode/client.ts)
        ↓  postMessage + ArrayBuffer transfer
Web Worker (blackboxDecode.worker.ts)
        ↓
Betaflight FlightLog (vendored JS) via @bf-blackbox alias
        ↓
normalizeFromFlightLog → NormalizedDecodedLog
        ↓
Open page (metadata + multi-log selector) / future browser analysis
```

Heavy decode runs off the React main thread. The Open page currently requests `includeSeries: false` for fast inspect; full series extraction is used by the parity harness.

## Chosen decoder strategy

**Reuse already-vendored Betaflight `blackbox-log-viewer` FlightLog JS** under `third_party/betaflight/blackbox-log-viewer/`, resolved as `@bf-blackbox/*`.

Rationale (preferred order from product rules):

1. Browser-native decoder already present in-repo (same stack as [blackbox.betaflight.com](https://blackbox.betaflight.com/) / [betaflight/blackbox-log-viewer](https://github.com/betaflight/blackbox-log-viewer)).
2. GyroCore-owned adapter (`normalizeFromFlightLog` + `NormalizedDecodedLog`) isolates UI/analysis from FlightLog internals.
3. Pinia/Vue UI dependency is stubbed (`src/decode/bf-stubs/flightlog_fields_presenter.js`) so the worker does not pull Vue stores.
4. Native `blackbox_decode` remains the trusted parity oracle (not the PWA runtime path).
5. WASM port of `blackbox_decode` is deferred unless browser FlightLog cannot meet parity.

## Licensing boundary

| Artifact | Path | License |
| --- | --- | --- |
| Repo root license file | `LICENSE` | GNU GPL v3 text (no "or later" grant for GyroCore) |
| Provenance manifest | `docs/upstream/PROVENANCE_MANIFEST.md` | "GyroCore license: **GPL-3.0**" |
| Python package | `pyproject.toml` | `GPL-3.0-only` |
| Web app / blackbox host | `apps/desktop/*/package.json` | `GPL-3.0-only` |
| Tauri crate | `apps/desktop/gyrocore-app/src-tauri/Cargo.toml` | `GPL-3.0-only` |
| Vendored viewer | `third_party/betaflight/blackbox-log-viewer/LICENSE` | GNU GPL v3 |

`tests/test_license_metadata.py` (run by `tools/ci/integrity.sh`) keeps every published
metadata file consistent with the root `LICENSE`. The former `pyproject.toml` MIT
declaration was the only inconsistency and is resolved; no license policy changed.

GyroCore-owned files under `apps/desktop/gyrocore-app/src/decode/` are adapters/contracts/tests; they do not relicense upstream.

## Normalized contract

`NormalizedDecodedLog` (`src/decode/types.ts`), `schemaVersion: 1`:

- `source` — filename, size, decoder id, license note
- `embedded` — `logCount`, `selectedIndex`, `recommendedIndex`, per-flight summaries (start/end/duration µs, sampleCount, errors)
- `metadata` — firmware type/version/revision/date, board, craft, looptime, pid_process_denom,
  I/P interval, raw `gyro_scale`, motor protocol, debug mode, data version, log start datetime,
  field names, sample-rate estimate, and `presence` (see Metadata)
- `timeUs`, `loopIteration` — `Float64Array` for the selected flight when series extracted
- `series` — every logged `gyroADC[*]`, `setpoint[*]`, `motor[*]`, `rcCommand[*]`,
  `axisP/I/D/F[*]`, `debug[*]` slot (`SERIES_FIELD_PATTERN`)

Consumers must not depend on FlightLog object shapes.

## Canonical sample policy

GyroCore analysis input is the **complete valid frame set** of the selected embedded log, on
every path (browser FlightLog worker, native `blackbox_decode` → Python Core):

1. Include every main frame (I/P) the decoder validates in the selected embedded log.
2. Never drop frames because an event (flight-mode change, disarm, …) precedes them.
3. Malformed/truncated frames may be excluded only by the explicit, deterministic validity rules
   both parsers share: frame not followed by a valid frame start, frame longer than the maximum,
   loopIteration/time moving backwards or jumping beyond the parser limits, P-frames before a
   resynchronising I-frame after genuine corruption.
4. Browser and native/Python must yield the same sequence, joined on `(loopIteration, time)`.

### Native decoder fix

Unpatched `blackbox_decode` violated rule 2: `parseEventFrame` did not consume FLIGHT_MODE (30) /
DISARM (15) payloads, desynchronised on a non-marker payload byte and dropped P-frames until the
next I-frame (tail **and mid-log**). The vendored source is patched
(`docs/upstream/PATCHES.md`, with the full byte-level reproduction table). The browser decoder
was always correct and is unchanged.

| Log (local 3-log BBL) | browser | native unpatched | native patched |
| --- | ---: | ---: | ---: |
| 1 | 51669 | 51608 | 51669 |
| 2 | 36657 | 36641 | 36657 |
| 3 | 246358 | 246200 | 246358 |

### Parity rule

Harness `src/decode/parity.ts`, per log:

1. rows joined on `(loopIteration, time)` — no positional alignment;
2. **zero** browser-only and **zero** native-only rows;
3. every compared channel bit-identical on all aligned rows (max abs error 0).

`predictNativeDesyncExclusions` remains only as a diagnostic: when the browser-only rows exactly
match its prediction, the report sets `unpatchedNativeSignature` (an unpatched binary is on
PATH) — this is always a FAIL, never parity.

### Core impact of the fix

Python Core consumes native CSV, so its input now contains the recovered frames. On the local
3-log BBL, final safety status, `tune`, `cli` and `chirp` outputs are unchanged; evidence-level
values (resonance clusters, problem severity, confidence, mechanical resonance flags) move.
Controlled re-runs show these are driven by Core's 20 000-sample decimation grid
(`MAX_PARSED_SAMPLES`) and, for log 3, by the removed mid-log holes — not by the decoder change
itself. See the gate report for the classification.

## Multi-log

Browser decode enumerates all embedded logs (`getLogCount` / `openLog`). Recommended index prefers
longest duration (then sample count) — a UI policy, not decoder correctness; an explicit
`logIndex` always wins. Proofs:

- `parity.fixtures.test.ts` concatenates three committed fixtures; selecting log *i* yields
  exactly the standalone decode of part *i* (times, iterations, every series), and native parity
  passes for each index.
- `parity.test.ts` (local user BBL, skipped in CI) checks all 3 embedded logs against native
  `--index i+1` with exact counts 51669 / 36657 / 246358.

## Metadata

`metadata.presence` is computed against the raw `H` lines of the selected log
(`src/decode/headers.ts`), independent of FlightLog:

| Status | Meaning |
| --- | --- |
| `PRESENT` | logged and surfaced |
| `ABSENT_IN_LOG` | header not logged or empty (not a decoder defect) |
| `UNSET_SENTINEL` | logged placeholder, e.g. `Log start datetime:0000-01-01…` (RTC unset) |
| `PARSER_MISSING` | logged but not surfaced — parity FAIL |

FlightLog renames `motor_pwm_protocol` → `fast_pwm_protocol`, keeps `Craft name` / `Board
information` / `Firmware date` under their header names, and reports `firmwareType` as a numeric
enum; the adapter maps all of these. `gyro_scale` (converted by FlightLog) and `Data version`
(not kept by FlightLog) are taken from raw headers. Log start/end time = first/last frame time.

## Parity harness

Harness: `src/decode/parity.ts`. Native is run with `--unit-vbat raw --unit-amperage raw
--unit-flags raw` so every column is the decoded integer. Groups compared (all slots):
timestamps, gyro, setpoint, motors, PID P/I/D/F, debug, rcCommand. Each channel reports aligned
count, max/mean abs error and Pearson correlation (n/a for constant channels). A group with no
channel on either side is `absent_in_log`, not a failure.

Tests:

- `parity.rules.test.ts` — exclusion rule, alignment, channel comparison (synthetic).
- `parity.fixtures.test.ts` — committed CHIRP fixtures + `tests/fixtures/decode/mode_events.bbl.gz` (mode/disarm events with P-frames); requires the patched `blackbox_decode` (built from the vendored source in every CI job). With `CI=true` or `GYROCORE_REQUIRE_NATIVE=1` a missing decoder fails instead of skipping.
- `parity.test.ts` — local multi-log BBL (`GYROCORE_BBL_FIXTURE`), skipped when absent.

The small CHIRP fixture (`clean_single_axis`) logs no PID terms: `axisP` is absent in both
native CSV and FlightLog field lists (`pid: absent_in_log`).

Known non-analysis differences: FlightLog adds computed fields (`heading`, `axisSum`,
`rcCommands`, `axisError`); native adds `energyCumulative`; FlightLog leaves slow-frame fields
empty before the first S frame.

## Known unsupported / deferred

- CSV browser decode (selection allowed; decode message explains binary-only)
- Full field dump into JSON (intentionally not done)
- Browser Core analysis / CHIRP / PID / filter migration
- Service-worker caching of user BBL bytes (explicitly forbidden; Workbox caches app shell only)
- Absolute filesystem paths in browser mode
- WASM `blackbox_decode`

## Performance notes

Measure via worker `timingsMs` (`read`, `index`, `normalize`, `total`) and parity `timingsMs.native` / `timingsMs.browser`. Prefer ArrayBuffer transfer into the worker; terminate worker after each decode to avoid retaining giant buffers across reselection.

Observed (local, `new FlightLog` + `normalizeFromFlightLog(includeSeries: true)`, log 0; 5 interleaved runs each,
first run cold):

| Fixture | Size | 111ce8c | hardened | Native `blackbox_decode` |
| --- | ---: | ---: | ---: | ---: |
| `clean_single_axis.bbl` (gunzipped chirp fixture) | ~68 KiB | 13–54 ms | 13–57 ms | ~12 ms |
| Multi-log user BBL (3 embedded logs) | ~13 MiB | 1.94–2.12 s | 2.00–2.15 s | ~250–330 ms per log |
| File read of 13 MiB BBL (main thread `readFile`) | ~13 MiB | ~12 ms | — | — |

No material regression from the wider series set or the raw-header scan.

Open-page inspect uses `includeSeries: false` (index + metadata only) to keep UI responsive; full series is for parity / future analysis.

Bottleneck: full frame materialization through FlightLog `getChunksInTimeRange` for large logs — expected; keep it in the worker.
