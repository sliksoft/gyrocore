# Upstream provenance manifest (WU5)

GyroCore license: **GPL-3.0**.

All imported areas below are GPL-3.0 (or GPL-3.0-or-later) from the Betaflight
project. Copyright headers, SPDX identifiers, and license notices in copied
files are retained.

Exact upstream commits recorded at import time (also in each tree’s
`UPSTREAM_COMMIT` / `UPSTREAM_COMMIT.txt`):

| Upstream repository | Commit |
|---------------------|--------|
| https://github.com/betaflight/blackbox-log-viewer | `a84755c5e897c1a3a580424b64c0df066c12c6b4` |
| https://github.com/betaflight/betaflight-configurator | `a38c4a797a86a580106162653db92af7e14be787` |
| https://github.com/betaflight/blackbox-tools | `f832acf9cd9dbe5ad8220de1a5f4eb4021523d72` |
| https://github.com/betaflight/betaflight | `e0b7bb01b17b21351057e9ead2d1ab39dd44fa16` (tag `2026.6.2`, WU9) |

## Imported areas

| Upstream repository | Upstream path | GyroCore destination | License | Status |
|---------------------|---------------|----------------------|---------|--------|
| blackbox-log-viewer | `/` (src, public, test, package.json, vite, index.html, LICENSE; exclude dmg/screenshots/node_modules) | `third_party/betaflight/blackbox-log-viewer/` | GPL-3.0 | copied |
| blackbox-log-viewer | (integration pointer) | `apps/desktop/blackbox/` | GPL-3.0 (adapter docs) | adapted (thin desktop adapter) |
| betaflight-configurator | `src/js/blackbox/` | `third_party/betaflight/configurator/src/js/blackbox/` | GPL-3.0-or-later | copied |
| betaflight-configurator | `src/composables/useAutotune.ts` | `third_party/betaflight/configurator/src/composables/useAutotune.ts` | GPL-3.0-or-later | copied |
| betaflight-configurator | `src/stores/autotune.ts` | `third_party/betaflight/configurator/src/stores/autotune.ts` | GPL-3.0-or-later | copied |
| betaflight-configurator | `src/components/tabs/AutotuneTab.vue` + `autotune/` | `third_party/betaflight/configurator/src/components/tabs/` | GPL-3.0-or-later | copied |
| betaflight-configurator | `src/blackbox-viewer/` (embedded fork) | `third_party/betaflight/configurator/src/blackbox-viewer/` | GPL-3.0-or-later | copied |
| betaflight-configurator | CHIRP deps: `data_storage.ts`, `debug_*.ts`, `utils/debugModes.ts`, `utils/common.ts` | `third_party/betaflight/configurator/src/js/` | GPL-3.0-or-later | copied |
| betaflight-configurator | `test/js/blackbox_chirp_p_interval.test.js`, `spectral_analysis.test.js`, `test/components/autotuneApplyGate.test.ts` | `third_party/betaflight/configurator/test/` | GPL-3.0-or-later | copied |
| betaflight-configurator | (integration pointer) | `apps/desktop/chirp/` | GPL-3.0 (adapter docs) | adapted (thin desktop adapter) |
| blackbox-tools | `src/` (decode/parser; render/font assets excluded — see IMPORT_NOTES.md) | `third_party/betaflight/blackbox-tools/src/` | GPL-3.0 | copied (partial) |
| blackbox-tools | `test/`, `LICENSE`, `Makefile`, `Readme.md` | `third_party/betaflight/blackbox-tools/` | GPL-3.0 | copied |

## Firmware extract (WU9)

Tag `2026.6.2` / commit `e0b7bb01b17b21351057e9ead2d1ab39dd44fa16`. Copied
byte-identical from that tag (`git show`). Not a full firmware tree.

| Upstream repository | Upstream path | GyroCore destination | License | Status |
|---------------------|---------------|----------------------|---------|--------|
| betaflight | `LICENSE` | `third_party/betaflight/firmware/LICENSE` | GPL-3.0 | copied |
| betaflight | `src/main/config/simplified_tuning.c` | `third_party/betaflight/firmware/src/main/config/simplified_tuning.c` | GPL-3.0-or-later | copied |
| betaflight | `src/main/config/simplified_tuning.h` | `third_party/betaflight/firmware/src/main/config/simplified_tuning.h` | GPL-3.0-or-later | copied |
| betaflight | `src/main/flight/pid.h` | `third_party/betaflight/firmware/src/main/flight/pid.h` | GPL-3.0-or-later | copied |
| betaflight | `src/main/sensors/gyro.h` | `third_party/betaflight/firmware/src/main/sensors/gyro.h` | GPL-3.0-or-later | copied |
| betaflight | `src/main/common/axis.h` | `third_party/betaflight/firmware/src/main/common/axis.h` | GPL-3.0-or-later | copied |
| betaflight | `src/main/common/maths.h` | `third_party/betaflight/firmware/src/main/common/maths.h` | GPL-3.0-or-later | copied |
| betaflight | `src/main/fc/parameter_names.h` | `third_party/betaflight/firmware/src/main/fc/parameter_names.h` | GPL-3.0-or-later | copied |
| betaflight | `src/main/msp/msp.c` (simplified-tuning helpers + `MSP_VALIDATE_SIMPLIFIED_TUNING` / `MSP_SET_SIMPLIFIED_TUNING` slices) | `third_party/betaflight/firmware/src/main/msp/msp_simplified_tuning.c` | GPL-3.0-or-later | copied (extract; original line numbers retained) |

Existing WU5 trees under `third_party/betaflight/{blackbox-log-viewer,configurator,blackbox-tools}/` are unchanged.

## Not imported (WU5)

- Configurator MSP/FC apply stack beyond the Autotune composable’s existing imports (not wired into GyroCore)
- Configurator locales, Capacitor/Android, Tauri shell, crowdin
- blackbox-tools `lib/` platform binaries (~105MB)
- AeroTuner (read-only donor; no runtime dependency)
- Full Python port of CHIRP/system-ID mathematics (deferred until parity — done in WU7, see below)

## Python ports (WU7)

Ported to GyroCore Python (GPL-3.0-or-later, derived from the files above;
vendored copies unchanged). Parity record: `CHIRP_SYSTEM_ID_PARITY.md`.

| Upstream | GyroCore |
| --- | --- |
| `chirp_bbl_parser.ts` `findLogBoundaries` / `parseHeader` / `validateDebugModeIsChirp` / `collectIfActive` / `collectSample` / `updateSegments` / `closeSegment` | `core/gyrocore/chirp/{sysconfig,debug_modes,extraction}.py` |
| `utils/debugModes.ts` + `debug_modes_table.ts` (CHIRP slot only) | `core/gyrocore/chirp/debug_modes.py` |
| `spectral_analysis.ts` (all except `recommendGains` and its private helpers) | `core/gyrocore/chirp/system_id.py` |
| `useAutotune.ts` `chooseSegmentSize`, `analyzeLog` / `computeAxisResult` orchestration (minus gains) | `core/gyrocore/chirp/{system_id,pipeline}.py` |
| blackbox-tools `blackbox_fielddefs.c` flight-mode names | `core/gyrocore/chirp/frames.py` `FLIGHT_MODE_FLAG_NAMES` |

Reference tooling (not shipped in Core): `tools/chirp_reference/` — BBL writer,
case generator, and a Node harness that runs temporary copies of the vendored
TypeScript to produce `tests/fixtures/chirp/wu7/upstream_*.json`.

## Python ports (WU8)

Autotune gain recommendation, recommendations only (non-actionable; no MSP /
CLI / apply). Parity record: `AUTOTUNE_RECOMMENDATION_PARITY.md`.

| Upstream | GyroCore |
| --- | --- |
| `spectral_analysis.ts` `recommendGains`, `extractMetrics`, `computeGainScales`, `buildProposedSliders`, `findOpenLoopCrossover`, `findTargetCrossover`, `peakSensitivityAtGain`, `scanSensitivity`, `robustGain`, `findMaxAchievablePhaseMargin`, `estimateLoopDelayMs`, `findBandwidth`, `findResonantPeak`, `computeLowFreqError`, `findNoiseFloor`, `computeMeanCoherence`, `resonanceBackoffs`, `gainClampLimitOf`, `integralScale` + constants | `core/gyrocore/autotune/recommend.py` |
| `utils/common.ts` `clamp` | `core/gyrocore/autotune/recommend.py` `js_clamp` |
| `useAutotune.ts` `extractCurrentSliders`, `buildGains` | `core/gyrocore/autotune/{current_tune,recommend}.py` |
| `chirp_bbl_parser.ts` `parseHeader` (slider / PID keys) | `core/gyrocore/chirp/sysconfig.py` `header_pairs` + `core/gyrocore/autotune/current_tune.py` |
| `useAutotune.ts` `applyGains`, `GainRecommendation.vue` `onApply` | **not ported** |

Reference tooling (not shipped in Core): `tools/autotune_reference/` — case
generator (synthetic `makeSyntheticTf` parameters + closed-loop CHIRP BBLs) and
a Node harness running temporary copies of the vendored TypeScript (and the
vendored test helper `makeSyntheticTf`) to produce
`tests/fixtures/autotune/wu8/upstream_autotune_reference.json.gz`. Staging is
shared with WU7 via `tools/chirp_reference/stage_vendored.mjs`.

## Python ports (WU9)

Firmware simplified-tuning mapping and a non-actionable global
`AbsoluteTuneProposal`. Parity record: `SIMPLIFIED_TUNING_PARITY.md`. Merge
policy: `AUTOTUNE_GLOBAL_SLIDER_POLICY.md`.

| Upstream | GyroCore |
| --- | --- |
| `simplified_tuning.c` `applySimplifiedTuning*` / `calculateNew*` | `core/gyrocore/betaflight/simplified_tuning.py` |
| `msp.c` `MSP_VALIDATE_SIMPLIFIED_TUNING` | `validate_simplified_tuning` |
| `useAutotune.ts` `applyGains`, `GainRecommendation.vue` `onApply` | **not ported** (documented only) |
| (GyroCore) unanimous / single-axis slider merge | `core/gyrocore/autotune/merge.py` (not firmware) |
| (GyroCore) current absolute tune + proposal | `core/gyrocore/autotune/absolute.py` |

Reference tooling (not shipped in Core): `tools/simplified_tuning_reference/`
compiles the vendored `simplified_tuning.c` as the discrete oracle.

## Source map (concise)

```
betaflight/blackbox-log-viewer/**          -> third_party/betaflight/blackbox-log-viewer/
                                           -> apps/desktop/blackbox/ (adapter)

betaflight-configurator/src/js/blackbox/*  -> third_party/betaflight/configurator/src/js/blackbox/
betaflight-configurator/.../autotune*      -> third_party/betaflight/configurator/src/...
                                           -> apps/desktop/chirp/ (adapter)

betaflight/blackbox-tools/src/*            -> third_party/betaflight/blackbox-tools/src/
betaflight 2026.6.2 simplified_tuning*     -> third_party/betaflight/firmware/
```
