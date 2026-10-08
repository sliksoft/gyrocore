# GyroCore PWA-first browser analysis audit

**Date:** 2026-10-08  
**Base:** `review/wu5-wu13` @ `39d36e079581bfe7843cdacf6c3fa5e868fb56b1`  
**Product direction:** Hosted/installable PWA-first (`https://app.gyrocore.dev/`), Betaflight App UX reference (`https://app.betaflight.com/`).  
**Not product architecture:** localhost analysis engine (preserved only on `experiment/pwa-local-engine-proof` @ `823b9301b55cf617db7706639bd83b8a9aa41794`).  
**Temporary:** Tauri desktop host (do not delete yet).

This document consolidates read-only research from the 2-hour PWA work session. No GPL source is copied from Betaflight.

---

## 1. Betaflight PWA patterns (Agent A)

### BF_PATTERNS_ADOPT

- Vite + `vite-plugin-pwa` with `registerType: "prompt"` (user confirms update; avoid silent reload during critical work).
- Manifest: `display: "standalone"`, `start_url` / `scope`, 192/512 icons, dark theme colors.
- Precache **app shell / static assets only** (Workbox); never user logs.
- Gate SW registration to real browser/PWA context (skip native wrappers).
- Capability matrix before enabling hardware APIs.
- Transport / platform facade (serial, files) behind one interface.
- Hidden `<input type="file">` / File System Access with blob-first handling for large files.
- Lazy-load heavy viz; workers for heavy export/parse jobs.

### BF_PATTERNS_AVOID

- Copying GPL Configurator / viewer source.
- `registerType: "autoUpdate"` for hardware-critical sessions.
- Registering SW inside Tauri/Capacitor shells.
- Putting flight log bytes in Cache Storage.
- Treating WASM as mandatory day-one (BF does not center on WASM for decode).

### BF_FILE_MODEL

Browser `File` / blob handles; extension filters; chunked writes for large dumps; optional OS `file_handlers` later. No absolute OS paths in UI.

### BF_DEVICE_MODEL

Logical transports (`serial` | `bluetooth` | `tcp` | `virtual` + DFU) behind a protocol router; MSP above transports. GyroCore should keep WebSerial/WebUSB **out of analysis** until a later WU.

### BF_PERFORMANCE_MODEL

Precache shell; workers + transferables for large buffers; do not stringify huge arrays; pause heavy work when tab hidden.

### BF_UPDATE_MODEL

Prompt → user accepts → `skipWaiting` / reload. Defer during active sessions. Offline-ready is informational.

---

## 2. blackbox_decode browser / WASM (Agent B)

**Exact dependency:** Vendored Betaflight `blackbox-tools` → native `blackbox_decode` C binary, invoked via `subprocess` from `gyrocore.decode.decoder.decode_bbl` (filesystem path + `--stdout`, optional `--index`).

| Option | Notes |
|--------|--------|
| A WASM current decoder | Best CSV bit-compat; needs mmap/path/pthread surgery |
| B Reuse vendored JS FlightLog / chirp parsers | Already in-tree under `third_party/betaflight/*` (GPL); CHIRP parity path exists |
| C Clean-room port | High cost / high parity risk |
| D Native sidecar bridge | Current desktop path; keep temporarily |

**BLACKBOX_BROWSER_RECOMMENDATION=`B_with_D_bridge`**

Use browser JS decoder path for PWA (GPL-compatible product per repo LICENSE/provenance); keep native `blackbox_decode` for Tauri/desktop until parity is proven. Prefer WASM(A) only if bit-identical CSV is mandatory in-browser.

**Licensing:** Treat product as GPL-3.0-compatible with vendored BF trees; resolve `pyproject.toml` MIT mismatch separately.

---

## 3. Core + CHIRP browser feasibility (Agent C)

Stack is mostly **Python + NumPy**; hard SciPy only in `resonance.py`; soft SciPy with NumPy fallbacks elsewhere; **no pandas**; decode is the native wall.

| Class | Examples |
|-------|----------|
| EASY_BROWSER | safety gates, CLI emit/authorize, verification, much of tune merge |
| WASM_SUITABLE / PYODIDE_SUITABLE | FFT, CHIRP math, noise, propwash, filter evidence |
| NEEDS_PORT | hard SciPy `resonance.py` island (or Pyodide-only) |
| KEEP_TEMPORARILY_NATIVE | `blackbox_decode` subprocess |

**RECOMMENDED_BROWSER_ANALYSIS_ARCHITECTURE:**

```
MIXED_D__PYTHON_CORE_GOLDEN__BROWSER_TS_PURE_GATES+WASM_OR_TS_FFT_CHIRP__PYODIDE_OPTIONAL_SCIPY_ISLAND__NATIVE_DECODE_UNTIL_JS_OR_WASM
```

Migration order: pure gates/CLI → preprocess/spectral → CHIRP/autotune (golden parity) → SciPy island → decode replacement.

---

## 4. Security / performance (Agent D)

### Normative rules

1. Single owning BBL buffer; no duplicate full copies.
2. Never `JSON.stringify` huge binary/frame grids for IPC.
3. Heavy work in Web Workers; use Transferables.
4. Lazy charts; pause/cancel when `document.hidden`.
5. Cache Storage = shell only; optional IDB for **derived** artifacts with TTL — never raw BBL/CLI.
6. CSP enforce (future deploy); Permissions-Policy deny `serial`/`usb` until intentionally enabled.
7. Defer COOP/COEP until SharedArrayBuffer/WASM threads are required.
8. Selecting a local file must produce **zero** network upload of that file.

### Phase test themes

Installability (Chrome/Edge), offline shell, prompt updates, no upload on file pick, worker transferables, hidden-tab pause, large-BBL soft failure, file_handlers later.

---

## 5. Session implementation snapshot

Implemented on `review/wu5-wu13` (this session):

- Installable PWA via `vite-plugin-pwa` (prompt updates, shell precache).
- Browser-native Open choosers (BBL + required CLI) keeping `File` objects.
- Runtime capability boundary: browser analysis = `unavailable` (honest UX; demos still work).
- Tauri path Open retained when Tauri runtime detected.

**Not implemented:** browser decode/analysis, localhost engine, WebSerial, Tauri removal.
