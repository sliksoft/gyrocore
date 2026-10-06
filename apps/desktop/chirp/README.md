# Desktop CHIRP / Autotune adapter (WU5)

Upstream foundation (copied, GPL-3.0-or-later):

```
third_party/betaflight/configurator/
```

Commit: see `third_party/betaflight/configurator/UPSTREAM_COMMIT`.

## What this adapter is

Thin GyroCore desktop integration entry for Betaflight Configurator Autotune/CHIRP:

| Concern | Upstream path |
|---------|---------------|
| BBL chirp parser | `src/js/blackbox/chirp_bbl_parser.ts` |
| System ID / Welch TF / Bode mag+phase / coherence | `src/js/blackbox/spectral_analysis.ts` |
| FFT helper | `src/js/blackbox/fft.ts` |
| Autotune orchestration + **sample rate** | `src/composables/useAutotune.ts` (`computeSampleRate`) |
| Store | `src/stores/autotune.ts` |
| Bode / spectrogram / import UI | `src/components/tabs/autotune/*`, `AutotuneTab.vue` |

## Sample-rate handling

- WU5 audit: `docs/upstream/CHIRP_SAMPLE_RATE.md`
- WU6 policy: `docs/upstream/CHIRP_SAMPLE_RATE_POLICY.md`
- Resolver: `core/gyrocore/chirp/sample_rate.py` (`resolve_chirp_sample_rate`)
- Minimal system-ID: `core/gyrocore/chirp/system_id.py`

Vendored Autotune TS is **not** patched; improvements live in Python Core.

## Safety

Upstream gain-apply (MSP write of simplified sliders) must **not** become
GyroCore actionable output without:

mechanical safety → safe tune/clamps → `tuning_output_safety` → actionable CLI

WU5 does not enable MSP apply from this adapter.

## Parity stance

CHIRP/system-ID mathematics remain in upstream TypeScript until parity is proven.
Do not force a Python Core port in this work unit. GyroCore Core already has
separate spectral/FFT analysis from the AeroTuner extract — keep those distinct.
