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

### Source facts

| Artifact | Path / URL | License statement in tree |
| --- | --- | --- |
| Repo root license file | `LICENSE` | GNU GPL v3 |
| Provenance manifest | `docs/upstream/PROVENANCE_MANIFEST.md` | States “GyroCore license: **GPL-3.0**”; lists blackbox-log-viewer as GPL-3.0 copied into `third_party/…` |
| Vendored viewer | `third_party/betaflight/blackbox-log-viewer/LICENSE` | GNU GPL v3 |
| Upstream commit pin | `third_party/betaflight/blackbox-log-viewer/UPSTREAM_COMMIT*` | Points at vendored BF commit |
| Python packaging metadata | `pyproject.toml` `license = { text = "MIT" }` | Declares MIT (conflicts with root `LICENSE` / PROVENANCE) |

### Engineering inference (not legal advice)

- Under the **root `LICENSE` + PROVENANCE** statements, linking the PWA decode worker to vendored FlightLog is consistent with an already-GPL GyroCore distribution story; no *new* GPL dependency is introduced beyond what is already vendored.
- The **`pyproject.toml` MIT** line is an inconsistency. Shipping a combined work that includes GPL FlightLog while claiming MIT for the Python package would be misleading; that packaging metadata should be reconciled separately (out of scope for this decoder checkpoint).
- Direct production reuse of FlightLog is therefore **allowed relative to root GPL / PROVENANCE**, with a **WARN** on the MIT packaging mismatch — not a silent license change.

GyroCore-owned files under `apps/desktop/gyrocore-app/src/decode/` are adapters/contracts/tests; they do not relicense upstream.

## Normalized contract

`NormalizedDecodedLog` (`src/decode/types.ts`), `schemaVersion: 1`:

- `source` — filename, size, decoder id, license note
- `embedded` — `logCount`, `selectedIndex`, `recommendedIndex`, per-flight summaries (duration, sampleCount, errors)
- `metadata` — firmware/craft when present, field names, sample-rate estimate
- `timeUs` — `Float64Array` (µs) for selected flight when series extracted
- `series` — compact `Record<string, Float64Array>` for primary channels (gyro / setpoint / motors / RC / PID / debug candidates)

Consumers must not depend on FlightLog object shapes.

## Multi-log

Browser decode enumerates all embedded logs (`getLogCount` / `openLog`). Recommended index prefers longest duration (then sample count). UI exposes the existing log selector when `logCount > 1`. Manual `logIndex` is preserved for future analysis.

## Parity rules

Harness: `src/decode/parity.ts` (+ `parity.test.ts`).

For the same BBL and 0-based `logIndex`:

| Side | Path |
| --- | --- |
| A (trusted) | system `blackbox_decode --stdout --index <1-based>` |
| B (browser) | FlightLog → `normalizeFromFlightLog(..., includeSeries: true)` |

Compared when available:

- embedded log count (native stderr “Log N of M”)
- field-name overlap
- sample count (2% / min 5 tolerance)
- time / gyro / setpoint / motor / PID correlation (Pearson; absolute scale may differ)

**PASS** requires embedded + sample count + timing + gyro correlation thresholds. Setpoint/motors/PID may be missing on some logs → documented as partial, not silent PASS.

Fixture: set `GYROCORE_BBL_FIXTURE`, or use the local multi-log BBL already used for validation (not committed).

## Known unsupported / deferred

- CSV browser decode (selection allowed; decode message explains binary-only)
- Full field dump into JSON (intentionally not done)
- Browser Core analysis / CHIRP / PID / filter migration
- Service-worker caching of user BBL bytes (explicitly forbidden; Workbox caches app shell only)
- Absolute filesystem paths in browser mode
- WASM `blackbox_decode`

## Performance notes

Measure via worker `timingsMs` (`read`, `index`, `normalize`, `total`) and parity `timingsMs.native` / `timingsMs.browser`. Prefer ArrayBuffer transfer into the worker; terminate worker after each decode to avoid retaining giant buffers across reselection.

Observed (local, series extraction / parity path):

| Fixture | Size | Browser normalize+series | Native `blackbox_decode` |
| --- | ---: | ---: | ---: |
| `clean_single_axis.bbl` (gunzipped chirp fixture) | ~68 KiB | ~32 ms | ~12 ms |
| Multi-log user BBL (3 embedded logs) | ~13 MiB | ~1.9–2.1 s | ~370–380 ms |
| File read of 13 MiB BBL (main thread `readFile`) | ~13 MiB | ~12 ms | — |

Open-page inspect uses `includeSeries: false` (index + metadata only) to keep UI responsive; full series is for parity / future analysis.

Bottleneck: full frame materialization through FlightLog `getChunksInTimeRange` for large logs — expected; keep it in the worker.
