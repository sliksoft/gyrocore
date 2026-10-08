# Autotune global-slider policy (WU9)

GyroCore merge of WU8 **per-axis** Autotune slider recommendations into one
**global** simplified-slider set.

This policy is **GyroCore-specific**. It is not Betaflight firmware behaviour
and it is not Configurator Autotune behaviour. The merge module is
`core/gyrocore/autotune/merge.py` (`POLICY_ID` =
`gyrocore.autotune.global_slider.merge.v1`, `policy_kind` = `gyrocore`).

Firmware mapping of sliders → absolute PIDs/filters lives separately in
`core/gyrocore/betaflight/simplified_tuning.py` (Betaflight 2026.6.2 parity).

## 1. What upstream Autotune actually does

Sources (vendored, byte-identical):

- `third_party/betaflight/configurator/src/composables/useAutotune.ts`
  `applyGains` (sends **one** axis’ `proposed` object)
- `third_party/betaflight/configurator/src/components/tabs/autotune/GainRecommendation.vue`
  `onApply` (the UI axis currently selected)

Observed behaviour:

- `recommendGains` runs independently per CHIRP axis.
- The UI lets the user pick **one** axis.
- `onApply` / `applyGains` writes **that axis’ full proposed slider set** via
  `MSP_SET_SIMPLIFIED_TUNING`. Firmware sliders are global; the FC then maps
  them to all axes under `simplified_pids_mode`.
- Upstream does **not** merge roll/pitch/yaw proposals.
- Autotune `proposed` keys are only:

  `slider_master_multiplier`, `slider_pi_gain`, `slider_i_gain`,
  `slider_d_gain`, `slider_feedforward_gain`,
  `slider_dterm_filter_multiplier`

- Autotune does **not** propose `simplified_d_max_gain`,
  `simplified_pitch_pi_gain`, `simplified_pitch_d_gain`
  (`simplified_roll_pitch_ratio`), or gyro-filter sliders. Those stay at the
  current FC values.
- Pitch has an extra independent firmware multiplier
  (`simplified_pitch_pi_gain` / `simplified_roll_pitch_ratio`). Autotune does
  not infer it from per-axis PI differences.

## 2. GyroCore merge (v1)

Participating axes: WU8 recommendations that are **not blocked** and have a
`proposed_sliders_unvalidated` set.

| Situation | Result |
| --- | --- |
| No participating axes | `MERGE_REQUIRES_REVIEW` (`no_participating_axes`) |
| Exactly one participating axis | Use that axis’ Autotune slider integers (same as upstream apply-one-axis). Every merged field is `constrained_by` that axis. |
| Two or more axes, **all six Autotune sliders identical** | Merge. Each field `agreed=true`, `constrained_by` all participating axes. |
| Any Autotune slider disagrees across participating axes | `MERGE_REQUIRES_REVIEW` (`slider_disagreement:<key>`). **No** min/max/average. |

Retained from the **current** tune (not inferred, not averaged):

- `simplified_pids_mode`
- `simplified_d_max_gain`
- `simplified_pitch_pi_gain`
- `simplified_pitch_d_gain` / `simplified_roll_pitch_ratio`
- `simplified_dterm_filter` (on/off)
- `simplified_gyro_filter` / `simplified_gyro_filter_multiplier`

Every source per-axis proposal is retained on `AbsoluteTuneProposal`
(`per_axis_wu8_recommendations`) even when merge fails.

The merge never masquerades as Betaflight: `policy_kind` is `gyrocore`,
`upstream_or_gyrocore` is `gyrocore`.

## 3. Conditions that produce `MERGE_REQUIRES_REVIEW`

1. `no_participating_axes` — every axis blocked, or no proposed slider set.
2. `slider_disagreement:<autotune_key>` — at least two participating axes
   proposed different integers for that Autotune slider.

There is no automatic resolution for (2). Guessing (min-across-axes, yaw 0.5
clamp, pick-roll, interpolate pitch_pi from PI ratios) is rejected as
undefensible for a safety-bound pipeline.

## 4. After a successful merge

`core/gyrocore/betaflight/simplified_tuning.py` maps the merged sliders through
the 2026.6.2 firmware formulas (`applySimplifiedTuningPids` /
`DtermFilters` / `GyroFilters`) into absolute P/I/D/D-max/F and filter Hz.

The result is an `AbsoluteTuneProposal` with `actionable = False`. It has **not**
passed mechanical safety, GyroCore safe-tune clamps, or
`tuning_output_safety`, and it is not CLI/MSP.

## 5. Intentional differences vs upstream

| Topic | Upstream | GyroCore WU9 |
| --- | --- | --- |
| Multi-axis | User picks one axis; that set is applied | Auto-merge only when unanimous or single-axis; else review |
| `pitch_pi` / `pitch_d` / `d_max` / gyro sliders | Left unchanged | Left unchanged (current values) |
| Apply | `MSP_SET_SIMPLIFIED_TUNING` | **Not implemented** |
| Safety | Configurator apply gate only | Deferred to WU10+ |
