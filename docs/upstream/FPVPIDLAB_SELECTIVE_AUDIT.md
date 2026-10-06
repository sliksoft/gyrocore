# FPVPIDlab selective audit (WU13)

```
FPVPIDLAB_REPOSITORY=https://github.com/eddycek/fpvpidlab
FPVPIDLAB_COMMIT=76354a022b331a9b466727f9a67ba369a12067ac
FPVPIDLAB_LICENSE=GPL-3.0-only
```

GyroCore already owns Blackbox → CHIRP → System-ID → recommendGains →
simplified mapping → safety → authorize_cli. FPVPIDlab is used only for three
missing diagnostics. Nothing from FPVPIDlab becomes actionable CLI.

Vendored provenance (TypeScript source, not executed):
`third_party/fpvpidlab/`.

## Classification

| Module | Class | GyroCore destination / notes |
|--------|-------|------------------------------|
| `SegmentSelector.ts` | **REUSE** | `filter_evidence/segments.py` |
| `NoiseAnalyzer.ts` | **REUSE** | `filter_evidence/noise.py` (GyroCore Welch PSD) |
| `GroupDelayEstimator.ts` | **REUSE** | `filter_evidence/group_delay.py` |
| `DynamicLowpassRecommender.ts` (`analyzeDynamicLowpass` only) | **REUSE** | evidence inside `analyze_filter_evidence` |
| `ThrottleSpectrogramAnalyzer.ts` | **REUSE** | `throttle_analysis/spectrogram.py` |
| `ThrottleTFAnalyzer.ts` (band / contiguous-run policy) | **REUSE** (policy) | `throttle_analysis/response.py` |
| `VerificationMatcher.ts` | **REUSE** (matching ideas) | `verification/matching.py` |
| `ConvergenceDetector.ts` | **REUSE** (thresholds) | `verification/convergence.py` |
| `verificationDelta.ts` | **REUSE** (delta polarity) | `verification/compare.py` |
| `filterResponse.ts` | **REFERENCE_ONLY** | PT1/biquad response notes; delay uses GroupDelayEstimator |
| `FilterAnalyzer.ts` | **REFERENCE_ONLY** | orchestration map; GyroCore has its own entry |
| `FilterRecommender.ts` (`computeNoiseBasedTarget` heuristic) | **REFERENCE_ONLY** | non-actionable candidate only |
| `constants.ts` (subset) | **REUSE** | copied thresholds documented per package |
| `FFTCompute.ts` | **REJECT_DUPLICATE** | use `spectral_windows` / NumPy Welch |
| `TransferFunctionEstimator.ts` | **REJECT_DUPLICATE** | use WU7 `welch_transfer_function` |
| `SystemIdentifier.ts` | **REJECT_DUPLICATE** | WU7 CHIRP System-ID |
| `PIDRecommender.ts` / `PIDAnalyzer.ts` | **REJECT_DUPLICATE** | WU8 Autotune |
| `SliderMapper.ts` | **REJECT_DUPLICATE** | WU9 simplified mapping |
| `BayesianPIDOptimizer.ts` | **REJECT_DUPLICATE** | out of product scope |
| `FilterPlacementOptimizer.ts` | **OUT_OF_SCOPE** | not required for alpha |
| `RpmFilterRecommender.ts` | **OUT_OF_SCOPE** | no automatic RPM redesign |
| Blackbox parser / MSP / license / telemetry / Electron UI | **OUT_OF_SCOPE** | desktop already local; no FC |

## Intentional GyroCore differences

1. Filter recommendation always `actionable=False`; never enters `authorize_cli`.
2. Throttle TF uses WU7 Welch TF, not FPVPIDlab Wiener/impulse stack → metrics are
   **MATH_EQUIVALENT** where definitions overlap (bandwidth/coherence), not EXACT_PARITY.
3. TPA output is advisory enum only — no TPA value, no TPA CLI.
4. Convergence statuses map to GyroCore vocabulary:
   `IMPROVING | CONVERGED | REGRESSED | INCOMPARABLE | INSUFFICIENT_EVIDENCE`
   (FPVPIDlab used `continue` / `diminishing_returns`).
5. Verification compares GyroCore measurement snapshots, not FPVPIDlab session DB rows.

## Threshold provenance

| Threshold | Source |
|-----------|--------|
| Segment / sweep / noise-floor percentile / peak prominence | FPVPIDlab `constants.ts` |
| Group delay PT1/biquad/notch formulas + 80 Hz reference | FPVPIDlab `GroupDelayEstimator` |
| Dynamic LPF +6 dB / r≥0.6 / min 3 bands | FPVPIDlab `DynamicLowpassRecommender` |
| Contiguous-run spectrogram / TF policy | FPVPIDlab Throttle* analyzers |
| Similarity accept 70 / reject 40 | FPVPIDlab |
| Filter convergence 1.5 dB / diminishing 3.0 dB | FPVPIDlab |
| Craft/BF/profile identity gates | **GyroCore-specific** |
| Quality-gated CONVERGED (require usable analysis quality) | **GyroCore-specific** |
