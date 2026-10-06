# Betaflight Autotune recommendation parity (WU8)

GyroCore ports Betaflight Configurator's Autotune gain recommendation
(`recommendGains` and every private helper it calls) to
`core/gyrocore/autotune/`. Input is a WU7 `ChirpSystemIdResult` plus the current
tune; output is an `AutotuneRecommendationResult` that is **non-actionable**:
no MSP, no CLI, no apply path, no flight-controller write.

Upstream snapshot: `third_party/betaflight/configurator` at
`a38c4a797a86a580106162653db92af7e14be787` (unchanged by WU8). Line numbers
below refer to that snapshot. Abbreviations: `spectral` =
`src/js/blackbox/spectral_analysis.ts`, `autotune` =
`src/composables/useAutotune.ts`, `parser` = `src/js/blackbox/chirp_bbl_parser.ts`,
`ui` = `src/components/tabs/autotune/GainRecommendation.vue`.

Chain position. WU8 is the first stage; everything after it is still missing:

```
autotune recommendation (WU8) -> mechanical safety -> safe-tune / clamps
    -> tuning_output_safety -> actionable CLI / apply
```

## 1. Upstream functions and Python replacements

| Upstream (file:line) | Role | GyroCore |
| --- | --- | --- |
| `spectral` `recommendGains` L315 | open loop → metrics → scales → sliders | `autotune/recommend.py` `recommend_gains` |
| `spectral` `extractMetrics` L328 | all diagnostic metrics | `extract_metrics` → `GainMetrics` |
| `spectral` `openLoopResponse` L402 | L = T/(1−T), unwrap from 2 Hz | reused: `chirp/system_id.py` `open_loop_response` (WU7) |
| `spectral` `findOpenLoopCrossover` L449 | first downward \|L\| = 1, PM there | `find_open_loop_crossover` |
| `spectral` `findTargetCrossover` L472 | phase = −(180 − PM) crossing, gain 1/\|L\| | `find_target_crossover` |
| `spectral` `peakSensitivityAtGain` L509 | Ms(g) = max 1/\|1 + gL\| | `peak_sensitivity_at_gain` (vectorised) |
| `spectral` `scanSensitivity` L552 | grid walk, withinBound / leastBad | `scan_sensitivity` (+ grid + `held`) |
| `spectral` `findMaxAchievablePhaseMargin` L581 | 180 + peak OL phase | `find_max_achievable_phase_margin` |
| `spectral` `estimateLoopDelayMs` L607 | LS slope of phase 20–140 Hz | `estimate_loop_delay_ms` |
| `spectral` `findBandwidth` L644 | −3 dB closed loop | `find_bandwidth` |
| `spectral` `findResonantPeak` L658 | max dB, 0 < f < 500 | `find_resonant_peak` |
| `spectral` `computeLowFreqError` L674 | mean dB, 2–10 Hz | `compute_low_freq_error` |
| `spectral` `findNoiseFloor` L694 | coherence drop after coherent | `find_noise_floor` |
| `spectral` `computeMeanCoherence` L708 | mean coherence 5–100 Hz | `compute_mean_coherence` |
| `spectral` `resonanceBackoffs` L721 | P/FF backoff from peak dB | `resonance_backoffs` |
| `spectral` `gainClampLimitOf` L732 | which per-pass limit bit | `gain_clamp_limit_of` |
| `spectral` `robustGain` L740 | Ms-bounded PI gain | `robust_gain` → `RobustGain` |
| `spectral` `integralScale` L756 | I from low-frequency error | `integral_scale` |
| `spectral` `computeGainScales` L766 | P/I/D/FF/filter scales | `compute_gain_scales` → `GainScales` |
| `spectral` `buildProposedSliders` L897 | slider integers | `build_proposed_sliders` → `SliderProposal` |
| `utils/common.ts` `clamp` L39 | `Math.min(Math.max(v, lo), hi)` | `js_clamp` |
| `Math.round` | ties toward +∞ | `js_math_round` |
| `autotune` `extractCurrentSliders` L249 | `(x \|\| 100) / 100` | `CurrentTune.upstream_current_sliders` |
| `autotune` `buildGains` L260 | UI summary | `build_gains` |
| `autotune` `computeAxisResult` L288 / `analyzeLog` L190 | per-segment orchestration | WU7 `identify_chirp_system` + `autotune/engine.py` `recommend_from_system_id` |
| `parser` `parseHeader` L315–560 | slider / PID header keys | `chirp/sysconfig.py` `header_pairs` + `autotune/current_tune.py` |
| `autotune` `applyGains` L317, `ui` `onApply` L485 | MSP write + EEPROM | **not ported** (by design) |

## 2. Trace of `recommendGains`

### 2.1 Inputs

- `tf`: `TransferFunction` from `welchTransferFunction(setpoint, gyro, sampleRate, segmentSize, 0.5)`
  (`autotune` L302). Consumed fields: `frequencies`, `magnitude` (dB),
  `coherence`, `hReal`, `hImag`. `phase` is not read by the recommendation.
- `currentSliders`: decimals (1.0 = slider 100). Built by `extractCurrentSliders`
  from `sysConfig.simplified_*` (`parser` defaults 100, L349–354) as
  `(value || 100) / 100` — so 0 and NaN also become 1.0.
- `targetPhaseMarginDeg`: default `PHASE_MARGIN_PRESETS.NORMAL` = 60; UI presets
  AGGRESSIVE 50, NORMAL 60, CONSERVATIVE 72.5 (`spectral` L286, `ui` L158–160).
  Not validated upstream.
- **Not consumed**: absolute P/I/D (`rollPID`/`pitchPID`/`yawPID` are
  display-only in `ui`), `simplified_pids_mode`, the real D-term filter
  configuration (`DEFAULT_DTERM_FILTER_HZ` = 150 is a constant), the PID profile
  index (not logged in BBL headers), sample rate (only via `tf`).

### 2.2 Open loop (`openLoopResponse`, L402)

`startIndex` = first k ≥ 1 with f ≥ `MIN_OPEN_LOOP_HZ` (2). For k ≥ startIndex
with coherence ≥ 0.5 and `(1−a)² + b² > 1e-12`:
`L = (a − a² − b², b) / ((1−a)² + b²)`, `|L| = hypot`, phase = `atan2·180/π`
unwrapped (±360 when the step between accepted bins exceeds 180°). Other bins
are NaN. Ported in WU7; WU8 reuses it unchanged.

### 2.3 Crossover and phase margin

- `findOpenLoopCrossover`: k from startIndex+1; skip NaN or coherence < 0.5 at
  k or k−1; first `|L|[k] ≤ 1 < |L|[k−1]`; linear interpolation of f and
  phase; `phaseMarginDeg = 180 + phase_interp`. None → `openLoopCrossoverHz`
  and `phaseMarginDeg` NaN.
- `findTargetCrossover`: wanted = −(180 − PM); same skipping; first
  `phase[k] ≤ wanted < phase[k−1]`; interpolate f and |L|; `|L| ≤ 1e-9` or NaN
  → null; `gainScale = 1/|L|`. None → `targetCrossoverHz`, `gainToTarget` NaN.
- `findMaxAchievablePhaseMargin`: 180 + max phase over coherent non-NaN bins
  (NaN if none).
- Gain margin: **not computed upstream**. Robustness is expressed as peak
  sensitivity Ms (which bounds PM ≥ 2·asin(1/(2Ms)) and GM ≥ Ms/(Ms−1),
  `spectral` L253–260). GyroCore reports exactly what upstream reports.

### 2.4 Sensitivity

- `peakSensitivityAtGain(g)`: over k ≥ startIndex, |L| not NaN and
  coherence ≥ 0.5: `d = hypot(1 + g|L|cos φ, g|L| sin φ)`; for d > 1e-9 the
  peak of 1/d; `peak > 0 ? peak : NaN`.
- `scanSensitivity(limit, maxGain = 2)`: `for (gain = 0.5; gain <= maxGain + 1e-9; gain += 0.01)`
  (accumulated float, not `0.5 + i·0.01`). Non-finite peak → return
  `min(1, maxGain)` for both answers (hold). Else `withinBound` = largest gain
  with peak ≤ limit (NaN if none), `leastBad` = argmin peak (first on ties).
- `sensitivityLimitedGain` = scan over [0.5, 2] with limit 2.0 (diagnostic).

### 2.5 Other metrics

| Metric | Rule |
| --- | --- |
| `bandwidthHz` | first −3 dB downward crossing, both bins coherence ≥ 0.3, interpolated; NaN if none |
| `resonantPeakDb` / `resonantFreqHz` | max magnitude over k ≥ 1, coherence ≥ 0.3, 0 < f < 500; initial −∞ / 0 |
| `lowFreqErrorDb` | mean magnitude dB over 2 ≤ f ≤ 10 with coherence > 0.3 (strict); 0 if none |
| `noiseFloorHz` | first f > 20 with coherence < 0.5 after any bin ≥ 0.5; last f if coherent but no drop; NaN if never coherent |
| `meanCoherence` | mean coherence over 5 ≤ f ≤ 100 (no coherence filter); 0 if none |
| `loopDelayMs` | least squares of OL phase vs f, 20 ≤ f ≤ 140, coherence ≥ 0.5; n < 5 or \|den\| < 1e-12 → NaN; `(−slope/360)·1000` |

### 2.6 Gain scales (`computeGainScales`, L766)

```
gainForMargin   = isFinite(gainToTarget) ? gainToTarget : 1          # hold when target unreachable
(rb, ffb)       = resonanceBackoffs(resonantPeakDb)                  # >6 dB: (0.75, 0.8); >3 dB: (0.9, 1); else (1, 1)
requestedGain   = gainForMargin · rb
admissibleMax   = clamp(requestedGain, 0.5, 2)                       # per-pass limit
gainClamped     = isFinite(gainToTarget) && (requestedGain > 2 || requestedGain < 0.5)
gainClampLimit  = gainClamped ? (requestedGain > 2 ? 2 : 0.5) : NaN
robustGain(admissibleMax):
    peak = Ms(admissibleMax); NaN or ≤ 2 → piScale = admissibleMax
    else scan [0.5, admissibleMax]: withinBound if finite,
         else leastBad (or admissibleMax) with sensitivityUnreachable = true
sensitivityBinds = piScale < admissibleMax · 0.98
P:  piScale  = clamp(piScale, 0.5, 2)
I:  iScale   = clamp(integralScale(lowFreqErrorDb), 0.5, 2)          # < −1 dB: 1 + |e|·0.1; > 2 dB: 1 − e·0.05; else 1
D:  dScale   = 1                                                     # always held (L826–846)
FF: ffScale  = clamp(gainForMargin · ffb · (piScale_unclamped / admissibleMax), 0.5, 2)
filter: filterScale = clamp(isFinite(noiseFloor) ? noiseFloor/150 : 1, 0.5, 1)   # tighten-only
predictedSensitivityPeakDb = 20·log10(Ms(piScale))
```

### 2.7 Sliders (`buildProposedSliders`, L897)

`Math.round(clamp((cur ?? 1) · scale · 100, 25, 250))`, evaluated left to
right, for `slider_pi_gain` (piScale), `slider_i_gain` (iScale),
`slider_d_gain` (dScale = 1), `slider_feedforward_gain` (ffScale),
`slider_dterm_filter_multiplier` (filterScale). `slider_master_multiplier` is
`Math.round(clamp(cur · 100, 25, 250))` — no scale.

"P/I/D/FF" in this port are therefore the slider multipliers piScale / iScale /
dScale / ffScale ("raw" = before the per-pass clamp, see `AxisRecommendation.scale_factors`)
and the slider integers ("rounded"). Absolute firmware PIDs are derived from
sliders by firmware `simplified_tuning.c`, which is not vendored; GyroCore does
not compute them.

### 2.8 Axis-specific behaviour

`recommendGains` has none: each axis' TF is processed identically. Upstream
runs it per CHIRP segment (later segments of the same axis overwrite earlier
ones, `autotune` L201–217). The UI lets the user pick **one** axis and applies
that axis' full slider set (`ui` L153, L485–489), although sliders are global
(roll/pitch, and yaw only in RPY mode). The D hold is partly justified by yaw
running no D (L840–842).

### 2.9 Invalid input / "cannot recommend" upstream

- `analyzeLog` returns null without CHIRP samples or segments (L192);
  throws for unsupported DEBUG_CHIRP axis encoding (L202).
- `computeAxisResult` returns null when the segment is shorter than the Welch
  segment (L297) — no recommendation for that axis.
- Otherwise upstream **always** recommends: incoherent data holds the gain
  (target NaN → gainForMargin 1; Ms NaN → admissibleMax), missing rate headers
  give 8 kHz (`computeSampleRate` `looptime || 125`, L234), absent or 0 sliders
  become 100. No PM validation.
- Firmware validation happens only after the MSP write in `applyGains`
  (`slider_pids_valid` / `slider_dterm_valid`, L325–328).

## 3. Clamps, defaults, rounding

| Rule | Value | Where |
| --- | --- | --- |
| open-loop start | f ≥ 2 Hz | `openLoopResponse` |
| open-loop denominator floor | `(1−a)² + b² > 1e-12` | `openLoopResponse` |
| margin / sensitivity coherence gate | ≥ 0.5 | crossover, target, Ms, max PM, loop delay |
| magnitude metric coherence gate | ≥ 0.3 (bandwidth, resonance), > 0.3 (low-freq error) | metrics |
| target magnitude floor | \|L\| > 1e-9 | `findTargetCrossover` |
| Ms distance floor | d > 1e-9 | `peakSensitivityAtGain` |
| Ms bound | 2.0 | `MAX_SENSITIVITY_PEAK` |
| scan grid | 0.5 → max + 1e-9, `+= 0.01` | `scanSensitivity` |
| scan hold | `min(1, maxGain)` when Ms non-finite | `scanSensitivity` |
| bind tolerance | piScale < 0.98 · admissibleMax | `computeGainScales` |
| per-pass scale clamp | [0.5, 2] for P, I, FF; filter [0.5, 1] | `computeGainScales` |
| D | always 1 | `computeGainScales` |
| D-term reference cutoff | 150 Hz constant | `DEFAULT_DTERM_FILTER_HZ` |
| resonance backoff | > 6 dB (0.75, 0.8); > 3 dB (0.9, 1) | `resonanceBackoffs` |
| I shaping | < −1 dB: +10 %/dB; > 2 dB: −5 %/dB | `integralScale` |
| hold rules | target NaN → gain 1; noise floor NaN → filter 1 | `computeGainScales` |
| slider clamp | [25, 250] then `Math.round` (ties → +∞) | `buildProposedSliders` |
| slider default in math | `cur ?? 1` (undefined only) | `buildProposedSliders` |
| slider default in extraction | `(x \|\| 100)/100` (0, NaN, missing) | `extractCurrentSliders` |
| header defaults | sliders 100, PIDs `[0,0,0]`, looptime 125 | `parseHeader` L328–354 |
| `parseInt` | sliders via `Number.parseInt` (truncates, leading digits) | `parseHeader` |

`js_clamp` propagates NaN like `Math.min(Math.max(NaN, …))`; `js_math_round`
is exact `Math.round` (floor + 1 if fraction ≥ 0.5; 0.49999999999999994 → 0).

## 4. Current tune / profile extraction

`autotune/current_tune.py` `extract_current_tune(headers=, cli_dump=)` →
`CurrentTune`; every field is a `TuneValue` with `source` ∈
`parsed | defaulted | inferred | missing`, `origin`, `raw`, `note`.

- BBL header: `chirp/sysconfig.py` `header_pairs` (the WU7 header reader,
  refactored out of `parse_chirp_sysconfig`, behaviour unchanged). Sliders by
  `Number.parseInt` semantics; `rollPID`/`pitchPID`/`yawPID` by
  `split(",").map(Number)`; `simplified_pids_mode`, `simplified_dterm_filter`,
  `ff_weight` (not read by upstream Autotune, recorded for the safety chain).
- CLI: the WU2 parsers only — `parse_cli_profile_blocks`
  (`active_profile_config`), `parse_cli_baseline_with_profile_isolation` (PIDs),
  `resolve_cli_profile_context`. No second parser. Values are `parsed` when the
  active profile is resolved with high confidence from profile blocks,
  otherwise `inferred` with `cli_active_profile_{ambiguous,unknown}`.
- Precedence: BBL header (describes the flight measured) over CLI; every
  disagreement is listed in `conflicts` and warned `bbl_cli_mismatch:<key>`.
- Missing input is `missing` — never filled. A `diff` omitting a default slider
  stays missing. The PID profile index is `missing` from BBL alone (not logged).
- Upstream's substitution is available only explicitly:
  `upstream_current_sliders()` (exact `extractCurrentSliders`) and
  `upstream_slider_inputs()` (substituted entries marked `defaulted`, origin
  `upstream:useAutotune.extractCurrentSliders(|| 100)`).

## 5. Gate policy (`autotune/engine.py`)

Blocking (axis `status = blocked`, proposals `None`):

| Code | Justification |
| --- | --- |
| `system_id:<gate>` (WU7 blocking gates: `invalid_sample_rate`, `non_uniform_sampling`, `excessive_gaps`, `insufficient_samples`, `insufficient_excitation`, `low_coherence`, `unusable_frequency_range`) | unusable system ID; upstream's own `insufficient_samples` analogue (L297) returns null |
| `system_id:no_transfer_function`, `system_id_error:*`, `no_chirp_segments`, `no_chirp_axes` | upstream `analyzeLog` null / throw |
| `current_tune_missing` | no tune at all |
| `current_tune_{missing,unparseable,zero}:<slider>` | upstream would silently use 100; missing critical input must not be invented. Opt-in `allow_upstream_slider_defaults=True` turns these into warnings (parity studies) |
| `simplified_pids_mode_off` | sliders do not drive the PIDs; upstream's apply would fail `slider_pids_valid` (L326) |
| `yaw_not_under_slider_control` (mode RP, yaw axis) | sliders do not reach yaw in RP mode |

Warnings only (status `proposed_with_warnings`):
WU7 warning gates (`system_id:timestamp_gaps_present`, …),
`sample_rate_differs_from_upstream_autotune`, `simplified_pids_mode_unknown`,
`simplified_dterm_filter_unknown` / `_off`, `current_tune:*` extraction
warnings, and the upstream outcome flags `autotune:target_margin_unreachable_gain_held`,
`autotune:no_open_loop_crossover`, `autotune:gain_clamped_per_pass:<limit>`,
`autotune:sensitivity_bound_unreachable` / `_binds`,
`autotune:slider_clamped:<key>` — the same conditions the upstream UI shows as
notes (`ui` L249–290), not hard blocks. Result-level:
`per_axis_proposals_differ_sliders_are_global`.

The engine validates `target_phase_margin_deg` ∈ (0, 180) and finite
(`ValueError`); `recommend_gains` itself, like upstream, does not.

## 6. Result model

`AutotuneRecommendationResult`: `kind`, `status` (`proposed` /
`proposed_with_warnings` / `blocked`), `target_phase_margin_deg`,
`current_tune` (with provenance), `axes` → `AxisRecommendation`,
`blocked_reasons`, `warnings`, `system_id_status`, `provenance` (upstream
functions, `not_ported`, WU7 system-ID provenance), `actionable = False`
(`init=False`), `required_downstream_stages`.

`AxisRecommendation`: status, reasons, warnings, WU7 `system_id` evidence
(quality, TF, open loop, step response), `recommendation` (`GainRecommendation`
with metrics, scales, shaping terms and per-slider current / scale / raw /
clamped / rounded), `current_sliders` used, GyroCore and upstream sample rate,
`proposed_sliders_unvalidated` (rounded integers; `None` when blocked),
`proposed_raw`, `scale_factors`. `to_dict()` always carries `actionable: false`
and the non-actionable notice. There is no method or string that renders CLI,
MSP or a paste-ready tune (asserted by `test_autotune_wu8_units.py`).

## 7. Fixtures

Generated by `tools/autotune_reference/make_autotune_cases.py` into
`tests/fixtures/autotune/wu8/`.

Synthetic transfer functions (`synthetic_cases.json`, 23): parameters for the
vendored test helper `makeSyntheticTf` (`test/js/spectral_analysis.test.js`
L24–105, extracted verbatim by the harness) plus coherence overrides and
current sliders; presets 50 / 60 / 72.5 (+ 95 on `nominal`). Cases: nominal,
delayed, fast, low/high plant gain (per-pass clamp up/down), target unreachable
in band and above ceiling, fragile resonance (binds / unreachable),
non-monotonic Ms, sharp 120 Hz mode, resonance backoff 3 dB / 6 dB,
incoherent (hold), coherence at / just below the 0.5 gate, coherent to 60 Hz
(filter tighten), narrow coherent band, a noisy bin, coarse bins, unusual
sliders (slider clamp 25 / 250), rounding ties (exact .5), undefined sliders
(`?? 1`), zero sliders, low-frequency error > +2 dB (I decrease).

Closed-loop BBLs (`bbl_cases.json` + `bbl/*.bbl.gz`, 19): simulated PID (D on
measurement, 100 Hz PT1) + motor lag + integrator plant + transport delay,
chirp 2 → 250 Hz, written as real Betaflight BBL with full headers.

| Case | Covers | Upstream | GyroCore |
| --- | --- | --- | --- |
| nominal_three_axis | roll / pitch / yaw | recommends | identical; yaw per-pass clamp warning |
| low_plant_gain / high_plant_gain | plant ×0.2 / ×2 | recommends | identical |
| delayed_plant | 4-sample delay | recommends | identical |
| noisy_usable | noise σ 12 | recommends | identical |
| near_quality_threshold | mean coherence 0.615 (WU7 gate 0.6) | recommends | identical |
| low_coherence | noise σ 400 vs amplitude 40 | recommends (pi 100) | **blocked** `system_id:low_coherence` |
| insufficient_frequency_range | chirp 0.2–3 Hz | recommends | **blocked** `system_id:unusable_frequency_range` |
| invalid_sample_rate | timing headers removed | 8 kHz fallback, recommends | **blocked** `system_id:invalid_sample_rate` |
| slider_upper_clamp / slider_lower_clamp | sliders 240–245 / 30 | 250 / 25 | identical + `slider_clamped` warning |
| unusual_pids | PIDs 120/20/80 | recommends | identical |
| missing_tune_headers | no `simplified_*` | uses 100 | **blocked** `current_tune_missing:*` |
| zero_slider | `simplified_feedforward_gain:0` | uses 100 | **blocked** `current_tune_zero:feedforward_gain` |
| pids_mode_off | mode OFF | recommends | **blocked** `simplified_pids_mode_off` |
| pids_mode_rp_yaw | mode RP | recommends yaw | yaw **blocked**, roll/pitch identical |
| log_rate_2k / log_rate_4k / log_rate_below_pid | 2 kHz; 4 kHz (P 1/2 of 8 kHz PID); 1 kHz (P 1/4 of 4 kHz PID) | recommends | identical (same rate) |

Reference vectors: `upstream_autotune_reference.json.gz`, from
`tools/autotune_reference/autotune_harness.mjs` running the vendored
TypeScript (139 `recommendGains` vectors: 70 synthetic, 69 BBL axis × preset),
with the SHA-256 of every vendored file used. Recorded per vector: `proposed`,
full `analysis`, crossover / target / resonance objects, every metric helper,
the full Ms scan grid (gains and peaks), backoffs, gainForMargin,
admissibleMax, gainClampLimit, Ms at admissibleMax, `robustGain` and its scan,
robustness factor, raw I / FF / filter scales, Ms at piScale, and per slider
current / scale / raw / clamped / rounded. The harness re-derives the local
expressions of `computeGainScales` / `buildProposedSliders` and aborts if they
disagree with the returned values. Output is deterministic (verified by
regenerating).

## 8. Tolerances (measured worst case in brackets)

Math parity (`test_autotune_wu8_math_parity.py`, upstream TF arrays as input):

| Quantity | Tolerance |
| --- | --- |
| proposed sliders, all booleans, `gainClampLimit` branch, scan gain grid, NaN/±∞ pattern, open-loop `startIndex` / NaN mask, crossover/target found-or-not, scan held | exact [exact] |
| continuous values (scales, crossover Hz, gains, raw sliders, Ms, delay, coherence) | 1e-11 relative [Ms peaks 1.7e-13; everything else ≤ 4.2e-15] |
| dB values (`predictedSensitivityPeakDb`, `lowFreqErrorDb`, `resonantPeakDb`) | 1e-10 dB absolute [4.2e-12 relative] |
| phase / phase margin | 1e-10 ° absolute [2.3e-13 °] |

Pipeline parity (`test_autotune_wu8_pipeline_parity.py`, GyroCore's own decode
and TF): H 1e-9 relative to max\|H\| [2.4e-13]; continuous 1e-9 relative
[3.5e-15]; dB 1e-8 [≤ 2.6e-14 relative]; phase 1e-7 ° [< 1e-13]; sliders and
flags exact [exact, all 60 compared axis × preset].

The only numeric source of difference is transcendental ulps (`cos`, `sin`,
`hypot`, `atan2`, `log10`: numpy / libm vs V8). Sums, interpolations, the scan
accumulation (`gain += 0.01`), comparisons, clamps and rounding follow JS
operation order exactly.

## 9. Remaining differences

Numeric: transcendental ulps only (§8); none changes any discrete output on the
fixture set. A Ms peak within ~1e-13 of 2.0, or a raw slider within ~1e-13 of
x.5, could round the other way in principle; no fixture is that close.

Semantic (all intentional, all hardening, none in the math):

1. Unusable system ID blocks (upstream recommends on any parseable segment).
2. Missing / zero / unparseable sliders block (upstream substitutes 100);
   opt-in parity mode reproduces upstream.
3. `simplified_pids_mode` OFF blocks; yaw blocked in RP mode (upstream offers both).
4. Sample rate comes from the WU6/WU7 resolver (PNum-aware, timestamp-checked);
   a difference from `computeSampleRate` is warned. Missing timing headers block
   instead of assuming 8 kHz.
5. Target phase margin validated in the engine.
6. Per-axis results are kept side by side with a global-slider warning; the
   upstream UI applies one chosen axis' set.
7. `predictedSensitivityPeakDb` guards `log10` of a non-positive value with NaN;
   Ms is either > 0 or NaN, so the result is identical.

Upstream behaviour preserved, not "fixed": D always held, filter tighten-only,
hold on unreachable target / incoherent data, `sensitivityUnreachable` takes the
least-bad gain, per-pass clamp [0.5, 2], slider clamp [25, 250].

## 10. Real-flight validation

REAL_BBL_VALIDATION = **BLOCKED**: no real CHIRP flight log is tracked in the
repository. Real logs work through `recommend_autotune_from_bbl(path, cli_dump=...)`
(`blackbox_decode` → WU7 → WU8), but parity and plausibility on real flights
are a separate gate and are not claimed here.

## 11. Before recommendations can enter the safety chain

- Real CHIRP flight logs (several frames, firmware versions, loop/log rates)
  with upstream reference vectors.
- Slider → absolute PID mapping (firmware `simplified_tuning.c`, not vendored),
  or a policy that the safety chain judges sliders directly; equivalent of
  upstream's post-write `slider_pids_valid` / `slider_dterm_valid` check
  before any output.
- Decide how per-axis proposals combine into one global slider set.
- Mechanical safety → safe-tune / clamps → `tuning_output_safety` must consume
  `AutotuneRecommendationResult` (it carries `required_downstream_stages`);
  only then can an actionable CLI / apply stage exist. No MSP write path is
  part of Core.

## 12. Regenerating

```bash
PYTHONPATH=core python tools/autotune_reference/make_autotune_cases.py
node --experimental-strip-types tools/autotune_reference/autotune_harness.mjs
```

Staging is shared with WU7 (`tools/chirp_reference/stage_vendored.mjs`): the
vendored files are copied to a temp directory; on the copies only, relative
imports gain `.ts`/`.js` suffixes, `vue` / `semver` / `utils/common` are
stubbed (the `clamp` stub is the vendored body verbatim — asserted by a test),
module-private `spectral_analysis.ts` helpers get an appended `export { … }`,
and `useAutotune.ts` functions plus `makeSyntheticTf` are extracted verbatim.
Nothing under `third_party/` is written.
