# Betaflight upstream extracts (WU5)

GyroCore vendors relevant Betaflight GPL-3.0 sources here as the **traceable
upstream foundation**. Desktop integration adapters live under `apps/desktop/`.

## Layout decision

| Area | Canonical GyroCore location | Rationale |
|------|----------------------------|-----------|
| Blackbox Viewer UI / graph / FFT presentation | `third_party/betaflight/blackbox-log-viewer/` → adapted via `apps/desktop/blackbox/` | Prefer the **standalone** Blackbox Log Viewer repo as the viewer foundation. Configurator embeds a diverging fork under `src/blackbox-viewer/`; that fork is also retained under `configurator/` because Autotune/CHIRP tests and tooling depend on it. |
| Autotune / CHIRP / Bode / coherence / system-ID | `third_party/betaflight/configurator/` → adapted via `apps/desktop/chirp/` | Lives in Configurator (`src/js/blackbox/*`, Autotune Vue tab). Mathematics stay in upstream TypeScript until parity is proven; not forced into Python Core in WU5. |
| blackbox-tools decode/parser C sources | `third_party/betaflight/blackbox-tools/` | Decoding pieces for reference/parity. Runtime decode continues to use GyroCore’s existing `gyrocore.decode` wrapper around `blackbox_decode`. |

Reusable **Python** analysis already in `core/gyrocore/` (FFT, resonance, sample-rate
metadata, …) is **not** duplicated here. Viewer/presentation belongs in desktop.
CHIRP system-ID math remains upstream-shaped for parity first.
