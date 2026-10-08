# GyroCore desktop (WU12)

| Package | Role |
|---------|------|
| `gyrocore-app/` | Tauri 2 + Vite + React shell |
| `worker/` | Python Core JSON Lines bridge |
| `blackbox-host/` | Vite host for vendored Blackbox Log Viewer |
| `blackbox/` | WU5 adapter notes |
| `chirp/` | WU5 CHIRP sample-rate re-exports |

Docs:

- `docs/desktop/WU12_DESKTOP_ARCHITECTURE.md`
- `docs/desktop/PACKAGING_PLAN.md`

## Quick start

```bash
# Generate / refresh demo fixtures (optional)
PYTHONPATH=.:core python apps/desktop/worker/gyrocore_worker.py <<'EOF'
{"id":1,"op":"demo","params":{"scenario":"pass"}}
EOF

# UI
cd apps/desktop/gyrocore-app
npm install
npm run dev

# Viewer host (optional iframe)
cd apps/desktop/blackbox-host && npm install && npm run dev

# Tauri (needs webview OS deps)
cd apps/desktop/gyrocore-app && npm run tauri dev
```

No FastAPI. No MSP. No FC apply. CLI text comes only from `authorize_cli`.
