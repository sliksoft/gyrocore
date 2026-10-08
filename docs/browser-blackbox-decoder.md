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

## Canonical sample inclusion

**The normalized contract contains every main frame FlightLog validates.** No frames are
filtered. Native `blackbox_decode` is *not* the definition of the sample set.

### Why native has fewer samples

The vendored `blackbox-tools` `parseEventFrame` (`third_party/betaflight/blackbox-tools/src/parser.c`)
only consumes payloads for SYNC_BEEP (0), INFLIGHT_ADJUSTMENT (13), LOGGING_RESUME (14) and
LOG_END (255). FLIGHT_MODE (30) is declared but has no `case`, so only its type byte is read and
the payload (`newFlags`, `lastFlags` as unsigned VB) stays in the stream:

- payload byte not a frame marker (e.g. `0x44` 'D' on disarm 69→68, `0x05` on 69→5) →
  `mainStreamIsValid = false`; P-frames cannot resync, so native drops every main frame
  until the next I-frame (`loopIteration % I interval == 0`) or end of log.
- payload byte `0x45` 'E' (arm 5→69) happens to re-enter event parsing → no loss.

Byte evidence (multi-log fixture, log 1): `45 1e 44 45 53 …` at `0x1f8ae9` — `E`, type 30,
newFlags 0x44, lastFlags 0x45, then an `S` frame. FlightLog parses the event; native desyncs.

Measured on the 3-log user BBL (all frames otherwise bit-identical):

| Log | FlightLog | native | browser-only | predicted | windows |
| --- | ---: | ---: | ---: | ---: | --- |
| 1 | 51669 | 51608 | 61 | 61 | disarm flight-mode change at 20.611531 s (tail) |
| 2 | 36657 | 36641 | 16 | 16 | disarm flight-mode change at 43.001305 s |
| 3 | 246358 | 246200 | 158 | 158 | **mid-log** 68.84 s (46), 89.40 s (103), tail 110.89 s (9) |

`native --raw` emits 51669 rows for log 1 (the dropped rows are flagged invalid, not absent),
confirming the frames exist in the file.

### Parity rule (option B: deterministic exclusion)

`predictNativeDesyncExclusions` (`src/decode/parity.ts`) predicts the native-dropped set from
FlightLog events + I interval. Parity requires, per log:

1. rows joined on `(loopIteration, time)` — no positional alignment;
2. browser-only rows **exactly equal** the predicted set, and zero native-only rows;
3. every compared channel bit-identical on all aligned rows (max abs error 0).

Events whose native effect is not modelled are reported (`unmodeledEvents`); any resulting
mismatch fails rule 2.

**Core impact:** the Python Core currently consumes native CSV, so on logs with FLIGHT_MODE
transitions Core and the browser see different frame sets (native has holes). Which side Core
should follow when CHIRP/PID analysis migrates is a product decision; the browser contract does
not reproduce the native defect.

## Multi-log

Browser decode enumerates all embedded logs (`getLogCount` / `openLog`). Recommended index prefers
longest duration (then sample count) — a UI policy, not decoder correctness; an explicit
`logIndex` always wins. Proofs:

- `parity.fixtures.test.ts` concatenates three committed fixtures; selecting log *i* yields
  exactly the standalone decode of part *i* (times, iterations, every series), and native parity
  passes for each index.
- `parity.test.ts` (local user BBL, skipped in CI) checks all 3 embedded logs against native
  `--index i+1`.

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
- `parity.fixtures.test.ts` — committed CHIRP fixtures; requires `blackbox_decode` (built in both the `desktop` and `integrity` CI jobs).
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
