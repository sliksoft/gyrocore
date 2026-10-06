# CHIRP sample-rate path (WU5 audit — do not silently fix)

**Status:** documented finding for a later improvement WU. Upstream behavior preserved.

## Exact path

| Step | Location | Symbol |
|------|----------|--------|
| Header parse of `looptime`, `pid_process_denom`, `P interval` → `frameIntervalPNum` / `frameIntervalPDenom` | `third_party/betaflight/configurator/src/js/blackbox/chirp_bbl_parser.ts` | `parseHeader` / `parsePIntervalHeader` / `parsePRatioHeader` |
| Sample-rate derivation for Welch / Bode / coherence / step response | `third_party/betaflight/configurator/src/composables/useAutotune.ts` | `computeSampleRate` → used by `analyzeLog` |
| Spectral consumers of that rate | `third_party/betaflight/configurator/src/js/blackbox/spectral_analysis.ts` | `welchTransferFunction`, `computeStepResponse`, `computeSpectrogram` |

## Upstream formula (`computeSampleRate`)

```ts
function computeSampleRate(sysConfig: SysConfig) {
    const looptimeUs = sysConfig.looptime || 125;
    const pidDenom = sysConfig.pid_process_denom || 1;
    const bbRate = sysConfig.frameIntervalPDenom || 1;
    return 1e6 / (looptimeUs * pidDenom * bbRate);
}
```

Interpretation:

| Factor | Meaning |
|--------|---------|
| `looptime` | Gyro/PID base period in microseconds (header) |
| `pid_process_denom` | PID runs every N gyro loops |
| `frameIntervalPDenom` | Blackbox P-interval denominator (logs every N PID iterations when num=1) |

So:

- **PID-loop frequency** ≈ `1e6 / (looptime × pid_process_denom)`
- **Blackbox logging frequency** (as used for CHIRP) ≈ PID frequency / `frameIntervalPDenom`
- Upstream does **not** measure rate from logged `time` field deltas
- Upstream does **not** use `frameIntervalPNum` in the rate formula (assumes typical `1/N` P interval)

## When Blackbox logging frequency &lt; PID-loop frequency

Firmware may log every 2nd (or Nth) loop (`H P interval:2` → denom=2). Upstream then **divides** the sample rate by that denom via `bbRate`. Bode/Welch frequency axes therefore track the **logged** sample rate, not the full PID rate.

That is intentional for system-ID on logged samples (input and output are both at blackbox rate). Nyquist is limited by the log rate.

## Risks (deferred — do not fix in WU5)

1. **Header-only rate** — no cross-check against median `time` deltas; a bad/missing header yields wrong Bode frequencies.
2. **`frameIntervalPNum` ignored** — non-`1/N` P intervals would be mis-scaled.
3. **Defaults** — missing fields fall back to `looptime=125`, `pid_process_denom=1`, `frameIntervalPDenom=1` (full-rate assumption).
4. **Confusion with PID rate** — callers must not substitute PID frequency when log rate is lower; upstream already multiplies by `bbRate`, but future ports must preserve that.

## Regression coverage

- Python mirror + cases: `tests/core/chirp/test_chirp_sample_rate.py`
- Fixture notes: `tests/fixtures/chirp/README.md`
- Upstream Vitest (vendor tree): `third_party/betaflight/configurator/test/js/blackbox_chirp_p_interval.test.js`

## Next improvement WU

Mark for follow-up: optionally validate/derive sample rate from logged timestamps; assert `frameIntervalPNum === 1` or honor num/denom; surface a warning when log rate ≪ PID rate.
