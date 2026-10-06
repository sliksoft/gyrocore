# CHIRP / system-ID parity with Betaflight (WU7)

GyroCore's CHIRP pipeline (`core/gyrocore/chirp/`) is a Python port of the
Betaflight Configurator chirp / autotune analysis, **up to and excluding**
`recommendGains`. This document traces every stage to the vendored upstream
source, states the numeric conventions, and records the measured parity.

Upstream snapshot (read-only): `third_party/betaflight/configurator/` @
`a38c4a797a86a580106162653db92af7e14be787`; `blackbox-tools` @
`f832acf9cd9dbe5ad8220de1a5f4eb4021523d72`. Line numbers below refer to these
snapshots.

Entry point: `gyrocore.chirp.identify_chirp_system(...)` /
`identify_chirp_system_from_bbl(path)` → `ChirpSystemIdResult` (analysis only;
`tuning_recommendations` is always `None`).

## 1. Pipeline trace

Abbreviations: `parser` = `src/js/blackbox/chirp_bbl_parser.ts`,
`spectral` = `src/js/blackbox/spectral_analysis.ts`, `fft` =
`src/js/blackbox/fft.ts`, `autotune` = `src/composables/useAutotune.ts`.
Parity class: **E** exact upstream parity, **M** mathematical equivalence,
**H** intentional GyroCore hardening.

| Stage | Upstream | GyroCore | Class |
| --- | --- | --- | --- |
| Log boundaries (`H Product:` marker) | `parser` `findLogBoundaries` L278 | `sysconfig.find_log_boundaries` | E |
| Header lines, ints via `Number.parseInt` | `parser` `parseHeader` L315, `parseIntHeader`, `parseSpecialHeader` | `sysconfig.parse_chirp_sysconfig`, `js_parse_int` | E (values) / H (absent keys stay `None`) |
| `P interval` `n/d` or bare divider `d` → `1/d` | `parser` `parsePIntervalHeader` L534 | `parse_chirp_sysconfig` | E |
| `P ratio` fallback only without `P interval` | `parser` `parsePRatioHeader` L549 | `parse_chirp_sysconfig` | E |
| Binary frame decode | `parser` `parseFrame` / predictors / encodings | `blackbox_decode` (`gyrocore.decode.decode_bbl`) → CSV | M (same frames; see §6) |
| CHIRP field selection `setpoint[0..2]`, `gyroADC[0..2]`, `debug[0..3]` | `parser` `parseChirpLog` L1015-1032 | `frames.read_chirp_frames_from_csv` (reuses `gyrocore.parse.blackbox_csv` header helpers) | E |
| Missing required field → reject | `parser` L1020-1032 | `ChirpFramesError("missing_required_field:…")` | E |
| `debug_mode == CHIRP` for API (log → caller → 1.49.0) | `parser` `validateDebugModeIsChirp` L961; `utils/debugModes.ts` `resolveTableVersion` L120, `getDebugModeIndex` L588; `data_storage.ts` L36 | `debug_modes.chirp_debug_mode_index`, `effective_chirp_api_version`, `extraction.validate_chirp_debug_mode` | E |
| Chirp active = S-frame `flightModeFlags` bit 6 (BOXCHIRP) | `parser` `BOXCHIRP_BIT` L190, `handleSFrame` L1305 | `extraction.extract_chirp` on per-row `flightModeFlags` (`blackbox_decode` prints bit 6 as `HEADFREE`; `frames.decode_flight_mode_flags`) | E |
| Chirp on → `currentAxis = -1`; chirp off → `closeSegment` | `parser` `handleSFrame` L1321-1327 | `extract_chirp` | E |
| Drop frames with `debug[1]` ∉ {-1,0,1,2} | `parser` `collectIfActive` L1284 | `extract_chirp` (`dropped_axis_frames`) | E |
| Sample = `value * hiResScale` (0.1 if `blackbox_high_resolution`) stored Float32; debug unscaled | `parser` L1046, `collectSample` L1358, Float32Array L1105-1118 | `extract_chirp` (`float32` arrays) | E (bit-exact) |
| Axis change opens segment; `-1` closes at `idx-1`; inclusive ends | `parser` `updateSegments` L1377, `closeSegment` L1406 | `extract_chirp` | E |
| Close open segment at end of data | `parser` L1098 | `extract_chirp` | E |
| Later segment of the same axis replaces earlier one | `autotune` `analyzeLog` L190-218 | `ChirpExtraction.selected_by_axis` (all segments kept in evidence) | E |
| Unsupported axis encoding → error | `autotune` L202 | impossible after the `debug[1]` filter | E |
| Sample rate `1e6/(looptime·pid_process_denom·PDenom)` (ignores `PNum`, defaults 125/1/1) | `autotune` `computeSampleRate` L234 | mirrored as `upstream_autotune_compute_sample_rate_hz` (reported); **analysis uses** `resolve_chirp_sample_rate` (PNum/PDenom + timestamp cross-check, WU6) | H |
| Segment size: 256 doubled while `< rate/2`, cap 4096 | `autotune` `chooseSegmentSize` L241 | `system_id.choose_segment_size` (applied to the resolved rate) | E |
| Skip axis if `len < segmentSize` | `autotune` `computeAxisResult` L296-299 | `insufficient_samples` gate (no TF computed) | E + H (reported, not silent) |
| Input = setpoint[axis], output = gyroADC[axis] slice `[start, end]` | `autotune` L300-301 | `ChirpExtraction.segment_signals` | E |
| Welch: `clampSegmentSize`, hop `Math.round(seg·(1-0.5))`, `numSegments = max(1, ⌊(N-seg)/hop⌋+1)`, tail ignored | `spectral` `welchTransferFunction` L102, `clampSegmentSize` L128 | `system_id.welch_spectra` (`js_round` = half-up) | E |
| Window: `0.5·(1-cos(2πi/(size-1)))` (symmetric Hann) | `spectral` `hanningWindow` L81 | `system_id.hanning_window` | E |
| FFT: forward `e^{-2πikn/N}`, unnormalized; real input | `fft` `ComplexFFT` L296, twiddles L316, `simple` | `numpy.fft.rfft` / `fft`; `system_id.complex_fft` mirror | M (same DFT, ≤5e-16 rel.) |
| Auto/cross spectra `Sxx=Σ|X|²`, `Syy=Σ|Y|²`, `Sxy=Σ conj(X)·Y`; no averaging / window-power normalization | `spectral` `accumulateSpectra` L140 | `welch_spectra` (`WelchSpectra`) | E |
| Bins `k=0..⌊seg/2⌋` (one-sided, DC + Nyquist), `f=k·fs/seg` | `spectral` `buildTransferFunction` L189 | `transfer_function_from_spectra` | E |
| `H=Sxy/Sxx`; `|H|` dB `20·log10(hypot)`; phase `atan2·180/π` ∈ (-180,180]; coherence `|Sxy|²/(Sxx·Syy)` (0 if denom ≤ 1e-30) | `spectral` `buildTransferFunction` | `transfer_function_from_spectra` | E |
| `Sxx < 1e-20` → H 0, magnitude −∞, phase 0, coherence 0 | `spectral` L209-215 | same | E |
| Smoothing | none beyond Welch averaging | none | E |
| Sensitivity `S=1-T`; peak over `0<f<500`, coherence ≥ 0.3 | `spectral` `computeSensitivity` L926 | `system_id.compute_sensitivity` | E |
| Step response: Hermitian IFFT, ÷N, cumsum of first N/2, ÷|H(0)|, first 100 ms; overshoot / rise / settling | `spectral` `computeStepResponse` L958, `stepMetrics` L1018 | `system_id.compute_step_response` | E |
| Spectrogram of output: Hann 256, overlap 0.75, `10·log10(|X|²+1e-20)` (absolute scale) | `spectral` `computeSpectrogram` L1092 | `system_id.compute_spectrogram` | E |
| Open loop `L=T/(1-T)` from first bin ≥ 2 Hz, coherence ≥ 0.5, ±360° unwrap | `spectral` `openLoopResponse` L402, `MIN_OPEN_LOOP_HZ` L240, `CROSSOVER_COHERENCE_MIN` L244 | `system_id.open_loop_response` | E |
| Measurement-quality metric (mean coherence 5–100 Hz) | `spectral` `computeMeanCoherence` L708 (informational inside `recommendGains`) | `low_coherence` gate band | H (gate) |
| Gain recommendation / apply | `spectral` `recommendGains` L315; `autotune` `applyGains` L317 | **not ported** | — |

## 2. FFT scale and sign (finding)

`ComplexFFT` computes the plain DFT `X[k] = Σ x[n]·e^{-2πikn/N}` (forward
twiddles `cos/sin(-θi)`, fft.ts L316) with **no** normalization in either
direction; `computeStepResponse` divides by N itself. `numpy.fft.fft` /
`rfft` compute the identical sum and `numpy.fft.ifft·N` the identical inverse.
Verified on 48 vectors (sizes 2–1000, radix 2/3/4/generic, real/complex,
forward/inverse) against the vendored class: max |Δ| ≤ 5.1e-16·max|X| and
energy ratio 1 ± 2.2e-16. The absolute scale is therefore equal, not merely
cancelling: it is additionally locked through quantities where it does
*not* cancel (spectrogram dB power, the `Sxx < 1e-20` and `Sxx·Syy > 1e-30`
floors).

Upstream defect (not reachable from CHIRP): `new ComplexFFT(1)` has no radix
factors and returns zeros; the size-1 DFT is the sample itself. CHIRP paths
use segment / window sizes ≥ 4. Test:
`test_upstream_complex_fft_size_one_is_degenerate_and_documented`.

## 3. Tolerances (measured worst case in brackets)

Math vectors (`tests/core/chirp/test_chirp_wu7_math_parity.py`):

| Quantity | Tolerance | Observed |
| --- | --- | --- |
| FFT output | 1e-12 · max|X| | 5.1e-16 |
| Hann window | 1e-15 abs | 1.1e-16 |
| complex H | 1e-12 · |H| (+1e-15·max|H|) | 3.2e-15 |
| coherence | 1e-12 abs | 1.9e-15 |
| magnitude | 1e-10 dB | 2.3e-14 |
| phase (|H| significant) | 1e-9 deg, wrapped | 1.7e-13 |
| step response | 1e-12 abs; metrics 1e-9 | 1.2e-15 |
| open loop | 1e-10 rel; phase 1e-9 deg; NaN mask exact | 7.4e-15 / 6e-13 |
| spectrogram | 1e-9 dB | 7.8e-14 |
| segment size, sample rate, CHIRP debug index | exact | exact |

End-to-end BBL cases (`tests/core/chirp/test_chirp_wu7_pipeline_parity.py`):

| Quantity | Tolerance | Observed |
| --- | --- | --- |
| extracted setpoint / gyroADC / debug | SHA-256 of Float32 buffers | identical (18/18 parseable cases) |
| segments, sample count, selected segment | exact | exact |
| complex H | 1e-9 · |H| (+1e-12·max|H|) | 5.7e-11 |
| coherence | 1e-10 abs | 1.1e-12 |
| magnitude / phase | 1e-8 dB / 1e-6 deg | — |
| step response | 1e-10 abs | — |
| spectrogram rows, sum | 1e-8 dB, 1e-12 rel | — |

Remaining differences are floating-point summation order (numpy pocketfft vs
mixed-radix ComplexFFT; vectorized `cos`/`log10`/`hypot` vs `Math.*`).
Relative error grows only where |H| or `Sxx` is small (out-of-band bins),
hence the `|H|`-relative tolerances.

## 4. Fixture matrix

Generator: `tools/chirp_reference/make_cases.py` (seeded; writes
`tests/fixtures/chirp/wu7/bbl/*.bbl.gz`, `cases.json`, `math_inputs.json`).
Upstream expected values: `tools/chirp_reference/reference_harness.mjs`
(runs the vendored TypeScript; writes `upstream_reference.json`,
`upstream_math_reference.json`, recording SHA-256 of each vendored file used).

| Case | Class | Upstream | GyroCore |
| --- | --- | --- | --- |
| clean_single_axis | E | analysed @1 kHz, seg 512 | ok, identical H |
| known_gain (0.5) | E, M | analysed | ok; |H| within 8 % of 0.5 in band |
| known_phase_delay (4 samples @2 kHz) | E, M | analysed, seg 1024 | ok; phase within 1° of −360·f·d/fs |
| low_noise | E | analysed | ok |
| noisy (σ 40) | E | analysed | ok (coherence 5–100 Hz 0.94) |
| weak_excitation (2 °/s) | E, H | analysed | identical H; unusable: `insufficient_excitation` |
| poor_coherence | E, H | analysed | identical H; unusable: `low_coherence`, `unusable_frequency_range` |
| dropped_timestamps (6×15 frames) | E, H | analysed (gaps invisible) | identical H; unusable: `excessive_gaps` |
| log_rate_below_pid (PID 4 kHz, P 1/4) | E | 1 kHz | 1 kHz, identical H |
| pnum_pdenom (P 2/3 @ PID 2 kHz) | H | 666.7 Hz (PNum ignored) | header 1333.3 Hz, alternating dt; unusable: `non_uniform_sampling` |
| chirp_at_log_end | E | segment closed at end of data | same |
| chirp_near_nyquist (to 490 Hz @1 kHz) | E, H | analysed | identical H; warning `chirp_band_near_nyquist`, band capped at 0.9·Nyquist |
| insufficient_samples (300 < 512) | E, H | axis skipped → no result | `insufficient_samples` |
| malformed_missing_rate_headers | H | assumes 8 kHz → seg 4096 > N → no result | timestamp-only 1 kHz, usable with warnings |
| malformed_wrong_debug_mode | E | throws | `not_chirp_debug_mode` |
| malformed_missing_debug_field | E | throws | `missing_required_field` |
| three_axis_sequence | E | 3 axes | identical, gains/delays recovered |
| repeated_axis | E | last roll segment | same (both kept in evidence) |
| high_resolution | E | ×0.1 scaling | bit-identical Float32 |
| corrupt_axis_frames (`debug[1]=7`) | E | frames dropped | same; warning `timestamp_gaps_present` |

For every parseable case the test also recomputes H on GyroCore's extracted
samples at upstream's rate/segment size and matches upstream, so hardening
cases still prove numeric parity of the math.

## 5. Quality gates (analysis validity only — not PID safety)

`core/gyrocore/chirp/quality.py`. Blocking gates make `usable = False`:

| Gate | Rule |
| --- | --- |
| `invalid_sample_rate` | `resolve_chirp_sample_rate` not usable |
| `non_uniform_sampling` | < 90 % of timestamp deltas within ±10 % of the median, or non-positive deltas |
| `excessive_gaps` | estimated missing samples > 1 % (gap = dt > 1.5·median) |
| `insufficient_samples` | segment < Welch segment (upstream skip) or < 4 Welch segments |
| `insufficient_excitation` | setpoint RMS < 5 °/s |
| `low_coherence` | mean coherence over 5–100 Hz ∩ chirp band < 0.6 |
| `unusable_frequency_range` | < 8 bins with coherence ≥ 0.5 inside the analysis band |

Warnings: `timestamp_gaps_present`, `sample_rate_crosscheck`,
`chirp_band_near_nyquist`, `chirp_band_unknown_default_used`. Usable mask =
analysis band (chirp start/end from header, capped at 0.9·Nyquist) ∩
`Sxx ≥ 1e-20` ∩ coherence ≥ 0.5.

## 6. Remaining differences

1. Frame decoding: GyroCore uses `blackbox_decode` instead of upstream's
   `parseFrame`. For well-formed logs the frames are identical (verified
   bit-exact on all fixtures). Corrupt-stream resynchronisation and
   `LOGGING_RESUME` handling follow blackbox-tools rules, which may keep or
   drop different frames than upstream's heuristic on damaged logs. Not
   covered by fixtures.
2. Chirp activity comes from per-row `flightModeFlags` (latest S-frame repeated
   by `blackbox_decode`) instead of S-frame events. Equivalent at main-frame
   granularity. If the flags column is unavailable (e.g. via
   `chirp_frames_from_parsed_samples` from integer-less CSV), extraction falls
   back to `debug[1]`-only gating with `chirp_mode_flag_unavailable_debug_axis_only`
   (segment indices then shift; segment data is unchanged).
3. Analysis sample rate (H): PNum/PDenom-aware and timestamp-checked; differs
   from upstream for `PNum ≠ 1` and for missing headers (§4).
4. Floating-point rounding (§3) and the `ComplexFFT(1)` defect (§2).

## 7. Before `recommendGains` can be ported

> WU8 has since ported `recommendGains` as a non-actionable recommendation in
> `core/gyrocore/autotune/` (record: `AUTOTUNE_RECOMMENDATION_PARITY.md`). The
> WU7 pipeline itself still stops before it. Open items below that WU8 did not
> close (real flight logs, the safety chain) are carried over there.

- Real CHIRP flight logs (several frames / firmware versions) added as fixtures,
  with upstream reference vectors, to complement the synthetic set.
- Port `extractMetrics`, crossover / phase-margin search, loop-delay estimate,
  sensitivity scan and gain clamps with their own parity vectors — kept
  analysis-only until the safety chain exists.
- Decide how recommendations treat GyroCore-unusable segments (upstream would
  still recommend on PNum ≠ 1, gapped or low-excitation logs).
- Mechanical safety → safe tune / clamps → final `tuning_output_safety` →
  actionable CLI must all exist and gate any output; no MSP write path.

## 8. Regenerating

```bash
python tools/chirp_reference/make_cases.py
node --experimental-strip-types tools/chirp_reference/reference_harness.mjs
```

Node ≥ 22.6 (`--experimental-strip-types`). The harness copies the vendored
files to a temp directory, adds `.ts`/`.js` suffixes to relative imports in the
copies, stubs `vue.reactive` (identity) and `semver` (`valid`/`compare`/`gte`)
plus `utils/common.clamp`, and extracts `computeSampleRate` /
`chooseSegmentSize` verbatim from `useAutotune.ts`. Nothing under
`third_party/` is written.
