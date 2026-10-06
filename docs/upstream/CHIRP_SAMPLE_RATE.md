# CHIRP sample-rate path (WU5 audit → WU6 hardening)

**Status:** WU5 documented Autotune weaknesses. WU6 implements GyroCore
resolution **outside** `third_party/` — see `CHIRP_SAMPLE_RATE_POLICY.md`.

Vendored `useAutotune.computeSampleRate` remains unchanged (immutable snapshot).

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

## Risks (WU5) → GyroCore handling (WU6)

| Risk | WU6 |
|------|-----|
| Header-only / no timestamp check | `estimate_timestamp_rate_hz` + mismatch policy |
| `frameIntervalPNum` ignored by Autotune | Viewer formula via `header_logged_rate_hz` |
| Silent full-rate defaults | Effective resolution returns `unusable` without trustworthy evidence |
| PID vs log rate confusion | Explicit `pid_loop_rate_hz` vs `header_rate_hz` fields |

## Regression coverage

- WU5 Autotune mirror: `tests/core/chirp/test_chirp_sample_rate.py`
- WU6 resolver: `tests/core/chirp/test_chirp_sample_rate_resolver.py`
- Parity vectors: `tests/fixtures/chirp/sample_rate_parity_vectors.json`
- Upstream Vitest (vendor tree): `third_party/.../blackbox_chirp_p_interval.test.js`
