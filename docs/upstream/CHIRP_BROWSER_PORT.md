# CHIRP browser port (CHIRP_BROWSER_WU1)

Browser / PWA port of GyroCore's validated CHIRP system identification.
The Python implementation (`core/gyrocore/chirp/`) remains the reference and was
not modified. Analysis only: no gain recommendation, PID/filter output, MSP or CLI.

```
Browser File ─▶ chirpAnalysis.worker (Web Worker)
                 ├─ FlightLog decode (same vendored decoder as blackboxDecode.worker)
                 ├─ chirpFramesFromFlightLog   (every valid main frame, CHIRP columns only)
                 ├─ identifyChirpSystem        (src/chirp/*.ts, float64 typed arrays)
                 └─ ChirpBrowserAnalysis       (series buffers transferred, not cloned)
             ─▶ chirpPayloadFromAnalysis ─▶ existing ChirpPage
```

## 1. Python reference audit

Entry point: `identify_chirp_system_from_bbl` → `decode_bbl` (`blackbox_decode` CSV)
+ `read_bbl_header_text` → `identify_chirp_system` (`pipeline.py`).

| Stage | Reference behaviour |
|---|---|
| Input fields | `setpoint[0..2]` (excitation / input), `gyroADC[0..2]` (response / output, never `gyro[]`/`gyroUnfilt[]`), `debug[0..3]` (`debug[1]` = excited axis), `time` (µs), optional `flightModeFlags` |
| Missing channel | `missing_required_field:<names>` (CSV columns, then header `Field I name`) → `status=error` |
| Headers (sysConfig) | `H` lines of the selected log; `Number.parseInt` semantics; `P interval` `a/b` or bare divider, `P ratio` fallback; present keys tracked so upstream defaults (`looptime` 125, `pid_process_denom` 1) are never mistaken for logged values |
| Debug mode | API version → CHIRP debug index table (1.47 → 97, 1.48/1.49 → 96, older → unsupported); `debug_mode` must equal it, else `not_chirp_debug_mode` / `chirp_debug_mode_unsupported_api` |
| Segment detection | Rows gated by `flightModeFlags` bit 6 (BOXCHIRP) per main row (empty cell = keep state); without the column: debug-axis-only gating + warning. Rows with `debug[1]` non-integer / outside −1..2 are dropped (`chirp_axis_out_of_range_frames_dropped`). Axis change opens a segment, −1 or chirp-off closes it (inclusive end). A later segment of the same axis replaces an earlier one (`repeated_axis_segments_last_selected`). None → `no_chirp_segments`, `status=unusable` |
| Scaling | `value * hiResScale` (0.1 when `blackbox_high_resolution`) rounded to **float32**; time stays float64 |
| Sample rate | Per segment: header `1e6·PNum/(looptime·pid_denom·PDenom)` cross-checked with `1e6/median(positive Δt)`; agree within 5 % → header; mismatch → timestamp rate; header-only / timestamp-only / unusable states. Upstream Autotune denom-only rate kept for provenance |
| Timestamp spacing | Δt uniformity (±10 % of median, ≥ 90 %, no non-positive Δt), gaps (`Δt > 1.5·median`, missing ≈ `rint(Δt/median) − 1`), resets / NaN counted as non-positive |
| Segment size | smallest pow2 ≥ 256 with seg ≥ fs/2, capped 4096; clamped to the segment length |
| Spectral method | Welch, symmetric Hann `0.5(1−cos(2πi/(N−1)))`, 50 % overlap (hop `Math.round`), unnormalized rfft, `Sxx/Syy/Sxy=conj(X)·Y` summed; trailing samples ignored. No detrending / filtering / smoothing / interpolation |
| Magnitude / phase | `H = Sxy/Sxx`; `20·log10|H|` dB; `atan2` degrees in (−180, 180]; bins with `Sxx < 1e-20`: H 0, −inf dB, phase 0 |
| Coherence | `|Sxy|²/(Sxx·Syy)` (0 when the denominator ≤ 1e-30) |
| Derived | sensitivity peak (`|1−T|`, 0–500 Hz, coherence ≥ 0.3), step response (IFFT of Hermitian H, cumsum, DC-normalised, 100 ms). Spectrogram (off by default) and open loop are not part of the result contract |
| Validity gates (blocking) | `invalid_sample_rate`, `non_uniform_sampling`, `excessive_gaps` (> 1 % missing), `insufficient_samples` (segment < Welch size, or < 4 Welch segments), `insufficient_excitation` (setpoint RMS < 5 deg/s), `low_coherence` (mean over 5–100 Hz ∩ band < 0.6), `unusable_frequency_range` (< 8 usable bins) |
| Warning gates | `timestamp_gaps_present`, `sample_rate_crosscheck`, `chirp_band_unknown_default_used`, `chirp_band_near_nyquist` |
| Valid range | analysis band = chirp start/end (header deci-Hz) capped at 0.9·Nyquist; usable bins = in band ∧ Sxx floor ∧ coherence ≥ 0.5 |
| Status | `ok` / `usable_with_warnings` / `unusable` / `error`; axis usable ⇔ H computed ∧ all blocking gates pass |
| Safety | Measurement validity only. Not PID / flight safety; never feeds tuning, CLI or MSP |

NumPy operations: `fft.rfft`, `fft.fft`, `fft.ifft`, `cos`, `hypot`, `log10`, `arctan2`,
`diff`, `median`, `rint`, `mean` (pairwise summation), `sqrt`, `cumsum`, masks /
`where`, float32 casts. No SciPy.

Reference observation (not changed here): the desktop worker adapter
`apps/desktop/worker/analyze_local.py:_series_from_tf` reads `frequency_hz` /
`freq_hz`, but the reference emits `frequencies_hz`, so the Tauri path can send
`available=true` with empty series and `quality=null`. The ChirpPage guard below
now renders such a payload as unavailable (`chirp_series_empty`) instead of PASS.

## 2. Browser contract

`src/chirp/types.ts`: `ChirpSystemIdResult` mirrors the reference
`to_dict(include_arrays=True)` key for key (axis, `frequencies_hz`, `magnitude_db`,
`phase_deg`, `coherence`, `h_real/h_imag`, `usable_mask`, `quality.usable_range_hz`,
`analysis_band_hz`, segment start/end index + µs, sample count, sample-rate
evidence, gates, warnings, errors, provenance). Arrays are `Float64Array`
(transferable). `ChirpBrowserAnalysis` adds `rejection` (`{code, detail}`; `null`
only for a usable axis with non-empty, equal-length series), `source`
(filename, log index/count, decoder, frames decoded, `inputPolicy: "full_frame"`)
and timings. No FlightLog objects cross the boundary.

## 3. Full-frame input policy

Every valid main frame of the selected log (FlightLog `getChunksInTimeRange(min,max)`,
the frame set already proven identical to patched native `blackbox_decode`). No
20k sampling or subsampling. FlightLog merges the latest S-frame into every main
frame, as the CSV does; `null` before the first S-frame maps to the reference's
empty cell (−1, keep state). Rows with non-finite required values are skipped
(`malformed_csv_rows_skipped`). Gaps, resets and NaN timestamps are never bridged:
they surface through the spacing gates.

## 4. Implementation notes

- Float64 iterative radix-2 FFT with directly evaluated twiddles (direct DFT for
  non-pow2); no dependency added. Gate means reproduce NumPy's pairwise
  summation (8192-element blocks) bit for bit; `rint` is half-to-even.
- `src/chirp/chirpAnalysis.worker.ts` decodes and analyses in one worker and
  transfers the result buffers; the full log never reaches the main thread.

## 5. Parity gate

Goldens: `tests/fixtures/chirp/browser/{bbl_golden,frame_cases}.json.gz`, written
by `tools/chirp_reference/make_browser_golden.py` from the unchanged reference;
`tests/core/chirp/test_browser_golden_fresh.py` fails if they go stale.
Test: `apps/desktop/gyrocore-app/src/chirp/parity.golden.test.ts`.

- BBL layer: all 20 WU7 fixtures, browser FlightLog decode vs native `blackbox_decode`.
- Frame layer: 14 edge cases (valid, each axis, repeated axis, no CHIRP flag,
  no axis, too short, low excitation, low coherence, timestamp gap, timestamp
  reset, NaN timestamps, no flags column, wrong debug mode, missing rate headers).
- Local logs (opt-in, not CI): `--local` mode + `src/chirp/parity.local.test.ts`.

Tolerances (declared before the first run; WU7 Python-vs-upstream values):

| Quantity | Tolerance |
|---|---|
| Structure, status, gates (code + pass), warnings, errors, segments, sample counts, segment size, Welch segments, `usable_mask` | exact |
| Frequency vector, rates, timestamps, scalars | rel 1e-12 |
| `h_real` / `h_imag` (analysis band) | rel 1e-9, abs floor 1e-12 |
| Magnitude (analysis band) | abs 1e-8 dB |
| Phase (analysis band, wrap-aware) | abs 1e-6° |
| Coherence (analysis band) | abs 1e-10 |
| Sensitivity peak / step response | abs 1e-8 dB / abs 1e-7 |

Result: 34/34 cases match. Worst in-band error over 3259 bins: magnitude
4.0e-11 dB, phase 2.0e-10°, coherence 6.7e-13, H rel 2.1e-10; correlation ≥
0.999999999999999. All-bin worst: magnitude 5.2e-10 dB, phase 4.2e-9°. The
local 3-log AIR65 file (51 669 / 36 657 / 246 358 frames) also matches exactly in
structure and within tolerance (in band ≤ 3.1e-11 dB, ≤ 1.1e-10°).

## 6. UI / capability

`runtime/capabilities.ts` lists features separately: browser `blackboxDecode`,
`cliSelection`, `chirpAnalysis` are available; `tuneSafety` stays `unavailable`
and `analysis` (general Tune/Safety) stays `unavailable`. The browser workspace
contains CHIRP only; Tune / Safety / Compare are `null`, CLI is
`NOT AVAILABLE` / not authorised / not actionable, all FC controls off.
ChirpPage shows charts only when `available` and all three series are
non-empty; the badge follows status (`usable_with_warnings` → WARN).
