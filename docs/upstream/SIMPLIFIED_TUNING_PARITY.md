# Simplified-tuning firmware parity (WU9)

Authoritative mapping: **Betaflight firmware 2026.6.2**, not Configurator labels.

| Field | Value |
| --- | --- |
| Repository | https://github.com/betaflight/betaflight |
| Version / tag | `2026.6.2` |
| Commit | `e0b7bb01b17b21351057e9ead2d1ab39dd44fa16` |
| Vendored | `third_party/betaflight/firmware/` |

Discrete outputs are compared to a C harness that compiles the vendored
`simplified_tuning.c` (`tools/simplified_tuning_reference/`). Python float64 vs
C `float` is accepted only if the truncated integer matches; the C harness is
the oracle.

## Firmware → Python

| Firmware | GyroCore |
| --- | --- |
| `applySimplifiedTuning` | `apply_simplified_tuning` |
| `applySimplifiedTuningPids` | `apply_simplified_tuning_pids` |
| `calculateNewPidValues` | `calculate_new_pid_values` |
| `applySimplifiedTuningDtermFilters` | `apply_simplified_tuning_dterm_filters` |
| `calculateNewDTermFilterValues` | `calculate_new_dterm_filter_values` |
| `applySimplifiedTuningGyroFilters` | `apply_simplified_tuning_gyro_filters` |
| `calculateNewGyroFilterValues` | `calculate_new_gyro_filter_values` |
| `constrain` (`common/maths.h`) | `c_constrain` (C float-to-int toward 0, then clamp) |
| `MSP_VALIDATE_SIMPLIFIED_TUNING` | `validate_simplified_tuning` |
| Autotune `applyGains` / `onApply` | **not ported** (no MSP) |
| GyroCore multi-axis merge | `autotune/merge.py` (not firmware) |

PIDs are recomputed from **firmware PID defaults × sliders**, not from the
current PID integers. Filters use integer `default * multiplier / 100` and skip
a filter when the current Hz is 0.

## Intentional semantic differences

1. Python mapping is a library; firmware writes the in-memory profile.
2. Autotune slider integers 25–250 can exceed CLI minmax 0/10–200; WU9 records
   `sliders_outside_cli_range` and still maps with firmware `constrain` (PID
   0–250, F 0–1000). MSP SET historically accepted uint8.
3. Missing current-tune values stay missing in `AbsoluteTune`. Filter mapping
   treats a missing Hz as 0 (firmware skip-if-zero) and warns; it does not
   invent 75/150/250/500.
4. Global slider merge is GyroCore policy, not firmware (see
   `AUTOTUNE_GLOBAL_SLIDER_POLICY.md`).

## Chain position

```
WU8 Autotune recommendation
    → WU9 AbsoluteTuneProposal (this document)
        → mechanical safety          (not in WU9)
        → safe-tune / GyroCore clamps
        → tuning_output_safety
        → actionable CLI / apply
```
