# Betaflight safe CLI parity (WU11)

WU11 is the first GyroCore stage allowed to emit paste-ready Betaflight CLI.
It consumes only a completed `FinalSafeTuneResult`. It does not talk to a
flight controller.

## 1. Donor (AeroTuner) behavior

| Function | Role |
|---|---|
| `tuning_engine_v2.generate_cli` | Emit `set` lines then always `save` |
| `tuning_engine_v2._append_pid_absolute_cli` | Absolute P/D/FF (`p_roll`, `d_roll`, `f_roll`) |
| `tuning_engine_v2._append_pid_delta_cli` | Delta P/I/D/FF vs current |
| `tuning_engine_v2.is_tuning_cli_key_allowed` | Version whitelist |
| `tuning_engine_v2.first_pid_cli_insert_index` | Insert RPM lines before PID / `save` |
| `cli_profile.active_profile_cli_selection_line` | `profile N` when isolation is high-confidence |
| `analyze._build_tuning_output_safety` | Donor gate: `cli_actionable` if status is actionable/limited **and** CLI contains `set`+`save` |

Donor `generate_cli` order: filter dict iteration → PID → `save`. Filter key
order is not a documented canonical sequence. Donor limited (WARN-like) status
can still be `cli_actionable` when a conservative CLI is authorized.

Not migrated: HTTP attach, session, user, database, RPM-notch SaaS helpers,
style/AI CLI, decision-engine advisory CLI.

## 2. Betaflight 2026.6.2 syntax (from source)

Vendored pin: tag `2026.6.2` / `e0b7bb01b17b21351057e9ead2d1ab39dd44fa16`.

Setting names from `third_party/betaflight/firmware/src/main/fc/parameter_names.h`
plus WU2 `cli.py` output map and the BBL alias `d_max` → CLI `d_min`:

| Internal | CLI name | Notes |
|---|---|---|
| roll/pitch/yaw P,I,D | `p_roll`, `i_roll`, `d_roll`, … | `cli/settings` component_axis form |
| feedforward | `f_roll`, `f_pitch`, `f_yaw` | not `ff_*` |
| D-max (firmware `d_max[]`) | `d_min_roll`, `d_min_pitch`, `d_min_yaw` | BBL header `d_max` aliases to `d_min` |
| gyro LPF | `gyro_lpf1_dyn_min_hz`, `gyro_lpf1_dyn_max_hz`, `gyro_lpf1_static_hz`, `gyro_lpf2_static_hz` | `0` = OFF |
| D-term LPF | `dterm_lpf1_dyn_min_hz`, `dterm_lpf1_dyn_max_hz`, `dterm_lpf1_static_hz`, `dterm_lpf2_static_hz` | `0` = OFF |
| PID profile select | `profile N` | bare command, N in 0–3 |
| persist | `save` | writes config; no reboot required for PID/filter |

Line form: `set <name> = <int>` (spaces around `=`). Comments start with `#`.

GyroCore does **not** emit `simplified_*` sliders. Absolute values are the
authority after WU10 clamps. Mixing sliders + expert PID is unsafe.

## 3. GyroCore safety policy

```
FinalSafeTuneResult
    → authorize_cli   (this package only)
    → ActionableTuneBundle | TuneCliPreview | TuneCliDenial
```

| Final status | CLI |
|---|---|
| PASS | Authorized `apply_cli` + `rollback_cli` (may include `save`) |
| WARN | `preview_cli` only — not paste-ready, no `save` |
| BLOCK | No CLI text in apply/preview/paste-ready fields |

This **differs from donor**: AeroTuner may mark limited CLI as `cli_actionable`.
GyroCore WU11 never treats WARN as PASS.

`save` policy: last line of an authorized apply/rollback that actually changes
settings. Omitted on no-op. Never present on WARN/BLOCK.

Canonical apply order:

1. `profile N` when the source PID profile is known
2. roll P/I/D/F/`d_min_roll`
3. pitch P/I/D/F/`d_min_pitch`
4. yaw P/I/D/F/`d_min_yaw`
5. gyro filters (dyn min, dyn max, static1, static2)
6. D-term filters (dyn min, dyn max, static1, static2)
7. `save` (authorized, non-empty change only)

Only keys that differ from the verified current baseline are emitted.
Missing baseline or missing target blocks authorization (no partial rollback).
