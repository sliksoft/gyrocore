# Desktop Blackbox Viewer adapter (WU5)

Upstream foundation (copied, GPL-3.0):

```
third_party/betaflight/blackbox-log-viewer/
```

Commit: see `third_party/betaflight/blackbox-log-viewer/UPSTREAM_COMMIT`.

## What this adapter is

Thin GyroCore desktop integration entry for the Betaflight Blackbox Log Viewer.
WU5 does **not** reimplement log loading, graphing, FFT overlays, timeline, or
export — those live in the vendored upstream tree.

## Upstream surface (presentation)

| Concern | Upstream location (under third_party/.../blackbox-log-viewer/) |
|---------|----------------------------------------------------------------|
| Log loading / flight data model | `src/flightlog.js`, `src/flightlog_parser.js`, `src/flightlog_index.js`, `src/datastream.js`, `src/decoders.js` |
| Field selection / defs | `src/flightlog_fielddefs.js`, `src/flightlog_fields_presenter.js` |
| Graph rendering | `src/grapher.js`, `src/graph_config.js`, `src/graph_map.js` |
| Smoothing / transforms | `src/graph_config.js`, `src/expo.js`, `src/imu.js` |
| Timeline / cursor / seek | `src/seekbar.js`, `src/playback_controls.js`, stores under `src/stores/` |
| Events / overlays | parser + grapher + Vue components under `src/components/` |
| FFT / spectral views | `src/graph_spectrum.js`, `src/graph_spectrum_calc.js`, `src/graph_spectrum_plot.js`, `src/fft_complex.js` |
| Export utilities | `src/csv-exporter.js`, `src/gpx-exporter.js`, `src/spectrum-exporter.js`, `public/js/webworkers/` |

## Integration rules

- Do not add FastAPI/Redis/DB/auth/SaaS dependencies.
- Do not take a runtime dependency on AeroTuner.
- Prefer improving the vendored upstream sources (with provenance) over rewriting.
- Python Core already owns decode/CSV/normalization/spectral analysis; keep
  viewer/presentation here / in third_party, not duplicated into Core.

## Next steps (post-WU5)

Wire a desktop host (e.g. Vite/Tauri) that loads the vendored viewer sources,
then improve behavior while retaining headers and the provenance manifest.
