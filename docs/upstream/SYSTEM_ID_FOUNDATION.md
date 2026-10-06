# System-ID foundation (WU6)

## Upstream functions inspected

| Concern | Path | Symbol |
|---------|------|--------|
| Excitation / chirp segments | `configurator/src/js/blackbox/chirp_bbl_parser.ts` | `parseChirpLog`, `collectIfActive`, `updateSegments` |
| Sample rate (Autotune, flawed) | `configurator/src/composables/useAutotune.ts` | `computeSampleRate`, `analyzeLog` |
| Sample rate (Viewer, correct num/denom) | `configurator/src/blackbox-viewer/flightlog.js` | `getBlackboxRate` |
| Sample rate + timestamp swap | `blackbox-log-viewer/src/graph_spectrum_calc.js` | `GraphSpectrumCalc.initialize` |
| Frame predicate | `blackbox-tools/src/parser.c` | `shouldHaveFrame` |
| Window | `configurator/src/js/blackbox/spectral_analysis.ts` | `hanningWindow` |
| Welch TF / Bode / coherence | same | `welchTransferFunction`, `accumulateSpectra`, `buildTransferFunction` |
| FFT | `configurator/src/js/blackbox/fft.ts` | `ComplexFFT` |
| Gain rec (deferred) | `spectral_analysis.ts` | `recommendGains`, `openLoopResponse`, `computeSensitivity` |

All under `third_party/betaflight/` (immutable in WU6).

## GyroCore Python port (minimal)

`core/gyrocore/chirp/system_id.py`:

- `hanning_window` — exact upstream formula
- `welch_transfer_function` — Welch H=Sxy/Sxx, mag/phase/coherence

Uses `numpy.fft.rfft`; FFT absolute scale may differ from `ComplexFFT` but
cancels in H and coherence.

**Not ported in WU6:** `recommendGains`, open-loop shaping, spectrogram UI path,
chirp BBL parser. Leave for WU7.

## Parity fixtures

`tests/fixtures/chirp/system_id_parity_vectors.json`
