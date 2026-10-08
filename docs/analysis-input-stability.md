# Analysis input stability gate

Canonical source: `review/wu5-wu13`, HEAD `8c075e7cd51c9cc4035662828519fe43ba96bc1e`.
Direction: PWA first, `app.gyrocore.dev`. This work adds offline experiments and
regressions. Production Core, decoder, frontend and tuning targets are unchanged.
CHIRP/PID browser migration has not started.

## Decision

The current input policy is unsuitable as the browser analysis contract.
Recommend full valid time-domain data plus timestamp-anchored, gap-aware spectral
windows, with aggregate PSD and separate transient-event evidence. The prototype
is **not a qualified production replacement**: its direct PSD peak threshold
misses a weaker genuine tone, and downstream amplitude/confidence/safety semantics
have not been calibrated for that representation. No production change is made.

## Exact current pipeline

`core/gyrocore/parse/blackbox_csv.py:44` defines `MAX_PARSED_SAMPLES=20000`.
`parse_csv_rows` counts every successfully parsed gyro row. At spill it makes a
second parse and selects zero-based indices
`round(i * (n_full - 1) / 19999)` for `i=0..19999`. Invalid rows do not count.
Endpoints survive. Every selected position depends on the final valid row count.
The exported even-subsampling helper and spectral replay use floor division;
they are not an exact reproduction of this parser. The harness tests against the
actual parser, including a count that distinguishes round from floor.

No antialias filter, interpolation, timestamp replacement or gap correction runs
at this cap. Source timestamps remain integer microseconds. Missing/invalid time
values fall back to row numbers, which do not establish a physical timebase.
Even uniformly sampled source data acquires alternating rounded strides. Real
logs also retain jitter and missing intervals. The selected samples therefore
are generally **not uniformly spaced in time**.

`analysis/evidence.py:59` normalizes gyro/time/telemetry, selects a flight using
the already capped data, builds matrices and segments, then quality and signal
evidence. Flight splitting detects resets, gaps above 500ms, sustained inactivity
and motor-off; smaller missing blocks remain inside a flight. Gyro normalization
can apply the existing ADC heuristic; there is no temporal regularization.
`analysis/signal.py:12` calculates `1/median(positive delta_t)`. FFT and filtering
then treat array positions as uniformly spaced at that rate.

| Representation | Actual consumers and preprocessing |
| --- | --- |
| Full decoded CSV | Native decode output; CHIRP full-frame reader; autotune/PID identification. CHIRP resolves header/timestamp cadence per extracted segment, checks gaps/excitation/coherence, then Welch transfer functions. It rejects capped parsed mappings. |
| Normalized, flight-selected capped rows | Main noise/resonance/propwash/eRPM, motor diagnostics/saturation, quality, response, D effectiveness, metrics and confidence. |
| Main spectral bundle | Gyro arrays; median cadence; rectangular, unnormalized `abs(rfft)`; mean of three axis magnitudes; five-bin smoothing. DC removal defaults false, retried only for an all-zero spectrum. Noise uses per-axis spectra; resonance uses merged spectra plus roll gyro confirmation. |
| Supporting spectral evidence | Independent finite-value removal, centering and linear detrend; 0.5s Hann Welch windows, 50% overlap, density PSD. This does not replace the main FFT. Throttle bands concatenate noncontiguous rows before Welch, an additional timebase limitation. |
| Propwash | Rows having throttle; median cadence; approximately 200ms sample-count windows with minimum 20 samples; throttle-drop and gyro response evidence combined with high-frequency spectral share. Such windows can cross gaps. |
| Oscillation problems | Derived segment maneuver fraction/count, HF noise ratio and tracking score. This is distinct from `metrics.resonance.severity`. |
| Confidence and safety | Unified confidence consumes primary resonance confidence and computed metrics. Mechanical safety adapts evidence; staged safety consumes the unchanged full-data tune proposal. |
| Precap helper | Dense activity-window extraction exists, but has no production caller in this path. It cannot rescue these capped spectra. |

PID/autotune calls CHIRP on full decoded CSV independently of generic evidence.
Unchanged tune outputs under parser perturbation are structurally expected, not
proof that the generic evidence is physically correct.

## Resonance audit

Main FFT bins are `fs/N`, with no explicit taper, overlap or PSD normalization.
Five-bin smoothing has a physical width that changes with cadence and record
length. `resonance.py` finds 30–500Hz local maxima above in-band
`mean + 1.8*std`. Noise floor is whole-spectrum median plus `1.4826*MAD`.
Acceptance requires amplitude at least `1.2*floor` and bandwidth no greater than
`max(0.25*frequency,1Hz)`; a fallback retains the first raw peak if all raw
candidates fail acceptance. Width uses SciPy half-prominence and is later floored
at 1Hz. Sharpness `amplitude/width > 0.12` labels a narrow peak.

Neighboring peaks merge within `max(3Hz,3% of lower frequency)` with chaining;
cluster center is the unweighted mean. Cluster score is
`0.7*sum(amplitude)/floor + 0.3/mean(width)`. The strongest individual peak chooses
the primary cluster. Secondary score must exceed `max(0.2*primary_score,0.1)`.
Weak clusters excluded from secondary recommendations still remain in the
returned cluster list and spread.

Primary confidence weights SNR .35, width .25, isolation .20 and filtered
roll-gyro energy .20, then applies cluster consistency/dominance adjustments.
All returned cluster centers determine spread, with a confidence penalty up to
30%. The separate v2 per-axis peak detector uses three times whole-spectrum mean,
at most six peaks; merged fallback multipliers are 2, 1.5 and 1.25. Metrics
resonance severity compares strongest amplitude to median detected amplitude:
high above 4x, medium above 2x. This is not the oscillation problem classifier.

`safety/mechanical.py:201` considers resonance broad if the primary is noise,
bandwidth is at least 60Hz, or cluster spread is at least 75Hz. It considers it
persistent if severity is high or spread is at least 90Hz. **These flags are not
measurements of temporal persistence.** A weak distant cluster can trigger both.
Supporting Welch evidence instead defines persistence by throttle-band presence,
and confidence from persistence and relative power (high .72 with two bands,
medium .4). These are separate meanings and representations.

The real log-1 baseline has a 481.039Hz cluster with amplitude 7803.04 against
threshold 7641.95 (ratio 1.0211). Removing 26 tail rows yields a ratio .9952 and
removes the cluster. 12,200 selected source identities are replaced. The broad
and persistent warnings disappear; unified confidence moves .613 to .650 while
final safety stays BLOCK. Full-data FFT has no accepted 481Hz cluster (local
amplitude 11432.72 against threshold 24131.92). This proves the threshold crossing
and sampling dependence; it does not establish a physical 481Hz mechanical mode.

Root cause: **SAMPLING_SELECTION**, including its incorrect uniform-time model;
**THRESHOLD_EDGE**, rectangular leakage/binning and **CLUSTERING** amplify it.
No threshold has been widened or lowered.

## Experiment contract

Reproduce with the existing project Python environment:

```bash
PYTHONPATH=.:core python3 tools/analysis_stability/run.py /tmp/gyrocore-stability-final \
  BTFL_BLACKBOX_LOG_AIR65_C_20261005_224215_BETAFPVG473.BBL \
  'BTFL_cli_HMB_RS V2_20261006_175648.txt'
PYTHONPATH=.:core python3 tools/analysis_stability/summarize.py /tmp/gyrocore-stability-final \
  BTFL_BLACKBOX_LOG_AIR65_C_20261005_224215_BETAFPVG473.BBL
```

Two committed 1200-row clean/noisy CSV fixtures, three 100000-row timestamp-defined
2kHz controls, a seeded 40000-row white-noise control with no injected resonance,
and the three local embedded logs are evaluated. Each has complete
input, tail removal/restoration and holes at 20%, 50%, 80% positions for .05%, .10%,
.50% source rows: 16 cases per source. Tail addition restores actual removed
valid rows and compares with the corresponding shortened case; no synthetic real
flight tail is invented. Surviving timestamps, values and identities are retained.
The positive controls include a 250ms late 481Hz burst and a true 73.8→83.8Hz shift.

The harness captures source identity hashes/count changes, selected count,
median/mean/quantile cadence, gaps, peak/cluster frequencies, amplitudes/scores,
noise, propwash, actual oscillation problems, confidence, quality, safety and tune
hashes. Raw FFT magnitude is not compared across sample counts as a physical
amplitude. Separate normalized PSD and integrated band powers provide diagnostic
fidelity evidence. Zero accepted windows is unavailable, never zero noise.

`summary.json` is the report source: it extracts actual oscillation problems and
compares restored tails against their shortened counterparts. It also recomputes
D on normalized, flight-selected full input, recording scale and stage. This
corrects preliminary real-log raw artifacts whose `oscillation` field was
misnamed resonance severity and whose D PSD used raw rows. The preliminary
artifacts are retained; their `problems` and `metrics_resonance` remain original
observations. Use the summary for semantic comparisons.

All real-log D recomputations verify the supplied BBL SHA256 against the saved
per-log source manifest before combining observations.

CHIRP proof uses usable `three_axis_sequence` and `chirp_at_log_end` fixtures,
hashing complete transfer/coherence/gate output before and after experiments on
independent generic inputs. Dedicated full-frame CHIRP data is not resampled.
Existing CHIRP math/pipeline/native parity gates also run. This proves preservation
of the existing path; it does not qualify applying candidate policies to CHIRP.

For real-log safety the genuine full-BBL autotune proposal is computed once per
embedded log and reused; no desktop demo fallback is used. Tune invariance is
reported with that architecture explicitly. The local CLI has BBL/config mismatch
warnings, so unchanged final BLOCK must not mask changed mechanical evidence.

## Policies and qualification

| Policy | Fidelity/stability and events | Compute and browser suitability | CHIRP/tests |
| --- | --- | --- | --- |
| A current | Total-count-dependent index grid, mixed cadence, no antialiasing. Real threshold/cluster flips and stationary-tail confidence drift. | Bounded 20k dictionaries/FFT, deterministic for identical input; unsuitable physical sampling contract. | Dedicated CHIRP unchanged; all existing tests pass. |
| B timestamp resampling | Native-median-rate grid anchored at first timestamp, linear interpolation. Removes global cap dependence; deliberately bridges holes, which fabricates unobserved signal. Discrete fields use neighboring rows. Whole-record rectangular FFT remains. | Linear preprocessing, full-sized arrays; transferable Worker representation possible. Rate/gap/interpolation contract still needed. | Never feed this generic grid to CHIRP. Production adoption changes capped metadata and donor spectra. |
| C contiguous | First qualifying gap-free run, at most 20k. Stable to distant tail; a hole can shorten/reselect the run. Misses the late 481Hz burst. Real early-window frequencies differ strongly from full flight. | Bounded fast FFT, straightforward Worker, deterministic; insufficient flight/event coverage. | CHIRP independent. Not a complete replacement for current whole-flight evidence. |
| D window aggregation | 1.024s native-cadence timestamp windows, 50% overlap, periodic Hann, DC detrend, one-sided density PSD; rejects windows touching a >1.5-period gap and makes an entire unresolved span unavailable on a timestamp reset. Mean PSD plus per-window peak union/occupancy. Stable complete windows and retains late burst. Direct PSD threshold misses weak 180Hz control. | Linear scanning plus fixed FFTs. Streamable Worker with fixed buffer and accumulated PSD; prototype materializes full input/window stack. Deterministic explicit bins/timebase. | Generic downstream classification/tune/safety unavailable until calibrated; CHIRP retains its full segment path. New DSP regressions pass, not production qualification. |
| E full | Removes cap-grid dependence and restores source cadence. Existing FFT still concatenates small holes and changes bins with length. Large dictionary/FFT cost and altered evidence need qualification. | Linear input storage and whole-record FFT; less suitable than streaming windows for a Worker. | CHIRP independent; removing parser cap changes explicit capped-metadata tests. No goldens changed. |

D follows the window/PSD approach documented by [SciPy Welch](https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.welch.html).
Its direct mean+1.8sigma threshold on **power** is an experimental adaptation,
not the same classifier as legacy **magnitude** thresholding. The weak-tone miss
is a REAL_REGRESSION for that prototype and blocks promotion. Retained event-union
noise peaks also need confidence qualification; a union alone is not a safe alarm.

## Proposed shared Python/browser contract

1. Preserve full valid rows with original integer-microsecond timestamps and
   telemetry validity. Detect/select flights before any display reduction.
2. Establish native cadence from timestamp evidence cross-checked with available
   logging metadata. Missing physical timebase is unavailable. Split resets and
   rate transitions; never sort them into a fabricated continuous flight.
3. Anchor complete spectral windows to the first valid timestamp in each flight,
   independent of total count. Specify exact window duration, hop, rate, taper,
   detrending, normalization, frequency bins and arithmetic for cross-language
   conformance vectors. The prototype uses 1.024s/50%; those are not promoted yet.
4. Regularize only bounded jitter within a contiguous interval. Never interpolate
   missing blocks; reject affected windows with explicit coverage. If a lower
   fixed rate is chosen, specify and verify antialias filtering first.
5. Aggregate calibrated normalized spectra for stationary evidence, retaining
   per-window peaks and actual temporal occupancy for short events. Missing
   coverage is unknown. Tail fragments need a separately qualified event path;
   silently discarding all incomplete tail windows can miss a real late event.
6. Keep response/propwash/motor evidence on full valid time-domain data with gaps
   explicit. Preserve the existing full-frame CHIRP segment/rate/validity path.
7. Qualify peak/classification/confidence/safety mapping against strong and weak
   tones, bursts near boundaries/tails, jitter, noise-only controls and real logs
   before Python promotion. Then freeze browser conformance vectors. No browser
   analysis port starts in this gate.

Expected future changes: recovering valid timebase and reducing sampling artifacts
are EXPECTED_CORRECTION when supported by signal evidence; stable within-tolerance
frequency/amplitude shifts are NUMERICAL_DRIFT; missed genuine tones, new false
alarms or unjustified safety/tune changes are REAL_REGRESSION. No existing expected
output or golden is edited in this work unit.

## GitNexus and boundaries

Initial index matched canonical HEAD and runner schema 4. Parser impact: LOW,
direct `parse_csv_with_meta`/`parse_blackbox_csv`, indirectly decode inspection.
`build_analysis_evidence` impact was UNKNOWN with no resolved callers; source
search confirmed desktop analysis, exports, tests and golden harness consumers.
No production function was modified on the strength of that empty graph result.
New offline-symbol UNKNOWN results were checked against their tooling/test-only
text callers. Final `detect_changes(scope=all)` reports HIGH risk: 56 changed
symbols, seven files and ten affected flows. Every changed symbol belongs to
the new report, tests or offline tooling; the affected flows enter through the
experiment runner, CHIRP proof or measurement routines. This is a HIGH result,
not a LOW-risk waiver. The result has no partial/truncated marker. No production
symbol changed, and no commit is created. New tooling was explicitly staged
for this check because unstaged untracked files were otherwise invisible.

The initial unrelated untracked `.claude/`, `.serena/`, `AGENTS.md`, `CLAUDE.md`,
BBL, CLI file and Zone.Identifier files are preserved. No merge, tuning target
change, localhost-engine extension or frontend migration is performed.

## Measured results

Nine sources, 16 perturbations and five policies produced **720 observations**.
Full artifacts: `/tmp/gyrocore-stability-final/`; semantic report source:
`summary.json`. Real source SHA256:
`97245445111bbfead8e2f3864dac92e24e70986ef2dce82e0fbf8679bda7b072`.
Python 3.12.3, NumPy 1.26.4, SciPy 1.15.3. Real logs have 51669, 36657 and 246358
valid frames. The historical pre-decoder-fix outputs supplied in the request
were not regenerated; these are fresh complete-frame and controlled-hole results.

| Real log | Current baseline clusters Hz | Current count range | Current confidence range | B / E count range | C count range |
| --- | --- | --- | --- | --- | --- |
| 1 | 40.224 / 481.039 | 1–2 | .613–.650 | 1 / 1 | 1–4 |
| 2 | 47.883 / 73.813 | 2 | .632–.633 | 2 / 2 | 1–2 |
| 3 | 122.61 / 31.92 / 157.30 / 166.95 | 2–7 | .564–.583 | 2 / 2 | 2 |

Log 1's actual oscillation problem varies between medium and high; its baseline
is medium. Quality ranges 57.802–57.966; noise value 0–1.5. Log 2 quality ranges
50.512–50.539, noise value 43.7–44.2. Log 3 quality ranges 64.691–64.773, noise
value 80.9–81.7. Baseline propwash is `none` for all three. The JSON retains each
propwash/confidence/warning observation, including changed mechanical evidence.
All A/B/C/E real cases remain final BLOCK with one unchanged proposal digest per
log. CLI/CHIRP are independent full-data paths; no new policy is applied to them.

Current log-1 tail removal of .05% or .10% removes the 481Hz cluster and both
resonance warnings. .50% tail removal retains two clusters. Equal .10% holes at
20%, 50%, 80% yield counts 1, 2, 2; equal .50% holes yield 2, 2, 1. This separates
gap-position effects from total-count effects. Restoring the removed tail returns
exactly to complete-input evidence.

Current log-3 counts for tail removal are 6, 2, 5 at .05%, .10%, .50%. Equal holes
at 20% / 50% / 80% produce:

| Removed rows | Tail | Hole 20% | Hole 50% | Hole 80% |
| --- | ---: | ---: | ---: | ---: |
| 123 (approximately .05%) | 6 | 4 | 4 | 6 |
| 246 (approximately .10%) | 2 | 4 | 5 | 7 |
| 1232 (approximately .50%) | 5 | 5 | 5 | 6 |

Current log-3 median cadence is 2971us versus mean 3051.12us; FFT claims 336.587Hz
and Nyquist 168.294Hz. Full native rows have median 248us, mean 247.687us and 174
gaps exceeding 1.5 periods. Thus the capped path cannot establish the native
high-frequency evidence even when its numerical outputs look plausible.

Full-data baselines cluster at 42.249Hz for log 1, 45.315/68.376Hz for log 2 and
442.53/34.13Hz for log 3. Timestamp-grid counterparts have the same counts but
slightly different centers. This is improved sampling fidelity evidence, not
an assertion that every returned cluster is a physical frame resonance.

D after full-flight normalization accepts/rejects 13/11, 11/5 and 34/84 windows
for the real logs. Mean-PSD peak counts vary 7–11, 17–20 and 16–18. This strict
gap rule leaves incomplete coverage, particularly in log 3. Its per-window union
has 95, 77 and 115 candidate peaks, not classified resonance clusters.

The stationary 73.8Hz tone appears at 74.219Hz on D's .9765625Hz bins and shifts
to 83.984Hz for the real 83.8Hz control. D retains the late 481Hz burst at
481.445Hz in two of 96 windows, although its mean spectrum misses it. A is limited
to 200Hz Nyquist on that control; C's early window excludes the burst entirely.
B/E whole-record detection has two or three clusters depending on perturbation,
so stable mean spectra alone do not guarantee transient detection.

D's stationary PSD integrates to approximately 28.60047, agreeing with the
independent axis-mean sine variance 28.6. The weak 180Hz component contributes
1.1 units of integrated power but fails D's experimental peak threshold:
**REAL_REGRESSION**, no promotion. A stronger two-tone control retains both peaks
when unrelated holes are relocated.

Pure seeded white noise contains no injected narrow resonance. A returns 15–23
clusters, B 17–24, C 6–13 and E 17–23. D returns 9–14 mean-PSD candidates and
376 distinct event-union bins on the baseline. These are false peak evidence;
they cannot be promoted to mechanical alarms without noise significance and
occupancy qualification. No candidate passes the complete false-positive gate.

The 1200-row committed noisy fixture also varies from one to five legacy
clusters under small perturbations, even without activating the cap. This proves
that removing global selection alone does not eliminate rectangular-FFT and
threshold sensitivity in the existing classifier.

## Performance

The main sensitivity run overlapped some validation work, so its times are
indicative. The following separate-process benchmarks ran sequentially after
those jobs finished. Each value is one observation, not a statistical timing
claim. Decode is native; preparation includes production CSV parsing or the
full-row experiment. Analysis is `build_analysis_evidence`; resonance is a
separate timed `analyze_resonance` call, excluding bundle construction. RSS is
whole-process peak including decode, CSV text and input/evidence materialization.

| Log | Policy | Decode s | Preparation s | Full analysis s | Resonance s | Peak RSS MiB |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | Current | .338 | 1.487 | .899 | .00494 | 199.9 |
| 1 | Full experiment | .338 | .923 | 2.376 | .00468 | 317.4 |
| 2 | Current | .238 | 1.091 | .876 | .00327 | 190.9 |
| 2 | Full experiment | .243 | .649 | 1.632 | .00289 | 255.0 |
| 3 | Current | 1.571 | 6.487 | 1.052 | .00594 | 302.0 |
| 3 | Full experiment | 1.560 | 4.969 | 14.065 | .05985 | 1125.7 |

Full preparation is faster here because the current parser parses spilled logs
twice. Full analysis and memory grow substantially. D's normalized full-input
diagnostic takes approximately 1.04/.80/4.16s on the three logs in the summary
pass; this is not a full analysis or browser benchmark. A separate log-3 D run
measured decode 1.642s, preparation 4.890s, PSD diagnostic 3.856s and whole-process
peak RSS 1042.1 MiB (34 accepted, 84 rejected windows). A/B/C/E per-case timings
and coarse retained-data memory estimates remain in the artifacts; these are
not isolated peak-RSS comparisons. No production after-change timing exists
because no replacement was implemented.

Reproduce isolated performance, with no other jobs active:

```bash
PYTHONPATH=.:core python3 tools/analysis_stability/benchmark.py \
  BTFL_BLACKBOX_LOG_AIR65_C_20261005_224215_BETAFPVG473.BBL 2 current
PYTHONPATH=.:core python3 tools/analysis_stability/benchmark.py \
  BTFL_BLACKBOX_LOG_AIR65_C_20261005_224215_BETAFPVG473.BBL 2 full
```

## Validation and final state

- Full Python pytest: **692 passed**, including Core, desktop, filter evidence,
  parity and golden tests. Focused stability harness: **18 passed**.
- Desktop pytest separately: **10 passed**.
- Native decode parity/full-frame tests separately: **7 passed**.
- Vitest with `GYROCORE_REQUIRE_NATIVE=1`: **61 passed in 13 files**, no skip.
- Typecheck: PASS. Production/PWA build: PASS (46 precached entries).
- Rust `cargo test --locked --lib`: **5 passed**.
- Integrity: PASS (`integrity OK`), including CHIRP/autotune, safety, CLI,
  native mode-event preservation and untouched vendored trees.
- CHIRP full-array proof: both usable fixtures remain `ok`, identical hashes.
- No frontend change; an additional PWA browser interaction proof is not required
  for this analysis-only work. No browser CHIRP or PID port started.
- No existing expected output or golden changed. Production diff is empty.
- Production implementation: NO. Commit: NONE. Push: NO. Merge: NO.

`ANALYSIS_STABILITY_GATE=WARN`: the investigation and validation are complete,
but current production sampling is unstable and no candidate is qualified against
all fidelity, gap, transient, false-positive and downstream safety requirements.
The next unit should qualify the proposed shared window/event contract in Python
and produce browser conformance vectors before either analysis browser port.
