# GyroCore WU6 — CHIRP sample-rate resolution policy

## Betaflight semantics (audited)

Logged Blackbox rate (Viewer `FlightLog.getBlackboxRate`,
`GraphSpectrumCalc.initialize`; tools `shouldHaveFrame`):

```
header_logged_rate_hz =
  1e6 * frameIntervalPNum
  / (looptime_us * pid_process_denom * frameIntervalPDenom)
```

Long-run fraction of PID iterations logged ≈ `PNum / PDenom`.

Autotune `useAutotune.computeSampleRate` incorrectly ignores `PNum`.
GyroCore does **not** use that formula for effective CHIRP analysis rates.
The denom-only mirror remains available only for upstream-parity tests.

## Mismatch tolerance

`MISMATCH_TOLERANCE_FRACTION = 0.05` (5%), matching Viewer
`WARNING_RATE_DIFFERENCE`.

## Resolution policy

| Case | Condition | Effective rate | Status |
|------|-----------|----------------|--------|
| A | Header valid + timestamps agree ≤5% | header | `ok` / `header_confirmed` |
| B | Header valid + timestamps disagree | **timestamp** | `mismatch` |
| C | Incomplete header + valid timestamps | timestamp | `timestamp_only` |
| D | Neither trustworthy | `None` | `unusable` |

On mismatch, timestamps win because Welch/Bode frequency bins must match the
actual spacing of the samples being transformed.

**Silent full-rate fallback is removed:** missing P-interval metadata does not
assume `1/1` logging when resolving an effective CHIRP rate.

## Timestamp estimate

Median of positive finite `diff(time_us)`; zero/negative deltas rejected.
