# Known issues / deferred work after WU5 foundation

## CHIRP sample rate

WU5 finding documented in `docs/upstream/CHIRP_SAMPLE_RATE.md`.
**Addressed in WU6** for GyroCore Core (`CHIRP_SAMPLE_RATE_POLICY.md`);
vendored Autotune `computeSampleRate` snapshot remains unpatched.

## Autotune gain apply vs GyroCore safety chain

Upstream `useAutotune` / `GainRecommendation.vue` can push simplified-tuning sliders to a connected FC via MSP.

GyroCore must **not** wire that path as actionable tuning output until:

`mechanical safety → safe tune/clamps → tuning_output_safety → actionable CLI`

WU5 copies the upstream Autotune UI/math for parity foundation only. Desktop adapters do not enable MSP apply.

## Dual Blackbox Viewer trees

- Standalone: `third_party/betaflight/blackbox-log-viewer/`
- Configurator fork: `third_party/betaflight/configurator/src/blackbox-viewer/`

They diverge. Future desktop work should pick one primary and track deltas explicitly.

## blackbox-tools render/libs excluded

Platform `lib/` binaries and cairo render sources were not vendored (size + binary blobs). See `third_party/betaflight/blackbox-tools/IMPORT_NOTES.md`.

## CHIRP math still TypeScript

System-ID / Bode / coherence remain in upstream TS under `configurator/src/js/blackbox/`. Python Core already has separate FFT/spectral analysis from AeroTuner extract; do not merge until parity is proven.

## Incomplete Configurator dependency graph

Copied CHIRP sources still import MSP/FC/FileSystem/i18n/UiBox/d3/Pinia for the full Autotune tab. Those modules are not fully vendored; the desktop adapter documents the dependency surface without claiming a runnable Configurator shell in WU5.

## Upstream tests not executed in GyroCore CI yet

Relevant tests are identified and vendored under `third_party/betaflight/configurator/test/`. Running them requires Configurator’s Node/Vitest graph. WU5 adds a Python regression for the sample-rate formula; full upstream Vitest is deferred.
