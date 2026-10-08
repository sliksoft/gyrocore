# GyroCore desktop packaging plan (WU12 spike)

## Development

From repo root (or `apps/desktop/gyrocore-app`):

```bash
# UI only (Vite)
cd apps/desktop/gyrocore-app && npm install && npm run dev

# Python worker (JSON Lines)
PYTHONPATH=core python apps/desktop/worker/gyrocore_worker.py

# Tauri desktop (requires OS webview deps)
cd apps/desktop/gyrocore-app && npm run tauri dev

# Blackbox viewer host (vendored upstream, unmodified)
cd apps/desktop/blackbox-host && npm install && npm run dev
```

## Production build commands

```bash
cd apps/desktop/gyrocore-app
npm run build          # tsc + vite → dist/
npm run tauri build    # native installer (needs platform deps)
```

Blackbox host:

```bash
cd apps/desktop/blackbox-host && npm run build
```

## Python worker packaging

| Phase | Plan |
|-------|------|
| Dev | System / venv Python with `PYTHONPATH=core` |
| Alpha | Ship a venv or `uv`-managed env beside the app; Tauri sidecar points at it |
| Release | PyInstaller / Nuitka one-folder bundle of `gyrocore_worker` + `core/gyrocore` |

Worker must remain a local process (stdin/stdout JSON). Do not convert it into a network service.

## blackbox_decode packaging

| Phase | Plan |
|-------|------|
| Dev | `CoreConfig.blackbox_decode_path` or PATH discovery (`resolve_blackbox_decode`) |
| Alpha | Bundle platform `blackbox_decode` binary under `apps/desktop/resources/decode/<os-arch>/` |
| Release | Tauri resource dir; worker resolves relative to app resource root |

Do **not** depend on `/usr/local/bin/blackbox_decode` for release. Document override for developers.

Sources: vendored `third_party/betaflight/blackbox-tools/` (build per platform CI).

## Linux considerations

- Tauri 2 needs `webkit2gtk` / `librsvg2` (see Tauri prerequisites).
- Package formats: `.deb` / AppImage via `tauri build`.
- Ship decode binary for `x86_64-unknown-linux-gnu` (and arm64 later).

## Windows considerations

- WebView2 runtime (Tauri bundles bootstrapper).
- Package: `.msi` / `.exe` via `tauri build`.
- Ship `blackbox_decode.exe` as a sidecar resource.
- Avoid requiring Developer Mode for alpha; use standard installer paths.

## WU12 spike status

- Vite `build` + TypeScript check: required green.
- Full native `tauri build` may be blocked on CI/dev hosts missing webview libs — document, do not pretend the installer is finished.
- Real BBL decode still needs a packaged decoder for offline alpha.
