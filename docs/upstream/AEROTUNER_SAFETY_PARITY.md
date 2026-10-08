# AeroTuner safety parity (WU10)

GyroCore ports the **domain** safety chain from AeroTuner. HTTP, session, user,
database, Redis, FastAPI, and paste-ready CLI generation are **not** migrated.

Pipeline (mandatory order, enforced by stage tokens):

```
AbsoluteTuneProposal
        → MechanicalSafetyResult
        → SafeTuneCandidate
        → TuningOutputSafetyResult
        → FinalSafeTuneResult   # actionable = False in WU10
```

WU11 is the first work unit allowed to turn a **passed** `FinalSafeTuneResult`
into CLI/apply. WU10 never sets `actionable=True` and never emits CLI/MSP.

## 1. Mechanical safety

| | Donor | GyroCore |
|---|---|---|
| Function | `backend.services.mechanical_safety_gate.build_mechanical_safety_gate` | `gyrocore.safety.mechanical.build_mechanical_safety_gate` |
| Fault helpers | `craft_tuning_policy.collect_mechanical_fault_evidence`, `noise_only_low_confidence_should_caution_not_limit` | `gyrocore.safety.fault` |
| Entry | analyze route kwargs | `evaluate_mechanical_safety` (WU4 evidence via `mechanical_inputs_from_analysis`) |

**Inputs (donor kwargs):** `pipeline_problems`, `motor_diagnostics`, `engine_metrics`,
`resonance_module`, `confidence_eval`, `quality_status`, `noise_level`,
`debug_frame_analysis`.

**GyroCore mapping from WU4 `build_analysis_evidence`:** problems, motors.diagnostics,
metrics, resonance, confidence, quality.status, saturation/D-effectiveness/step/eRPM
attached under debug_frame_analysis (not re-analysed).

**Outputs:** `mechanical_block` / `mechanical_limited` / `mechanical_caution`,
`mechanical_outcome`, `blocking_reasons`, `limited_reasons`, `caution_reasons`,
`max_delta_scale` (0 / 0.5 / 0.65 / 0.75 / 1.0), evidence (motor counts, resonance,
independent mechanical evidence).

**Verdict mapping:** block → `BLOCK`; limited or caution → `WARN`; else → `PASS`.

**Do not silently loosen a donor block.** Parity tests call the live AeroTuner
function and GyroCore with the same kwargs.

### GyroCore-only mechanical rules

- `require_analysis=True` (Autotune pipeline): missing or `ok=False` evidence →
  `BLOCK` / `missing_required_analysis`. Donor empty kwargs still **pass**
  (not over-block). Direct `build_mechanical_safety_gate()` keeps donor behaviour.

## 2. Safe-tune / clamps

| | Donor | GyroCore |
|---|---|---|
| Step clamp | `tuning_safe_v2.apply_to_baseline` + `DEFAULT_MAX_DELTA` | `gyrocore.safety.clamps.apply_to_baseline` |
| Hard clamp / blend | `tuning_safe_v2.apply_safety` | `apply_safety` / `apply_safety_autotune` |
| Thermal envelope | `tuning_safety_policy.clamp_targets_to_baseline_thermal`, `should_enforce_baseline_envelope` | `gyrocore.safety.thermal` |
| Style / generate_v2_safe_tune / generate_cli | **not migrated** | — |

Donor step caps (absolute, per axis unless noted):

| Item | Max \|Δ\| |
|---|---|
| P | 4 |
| I | 8 |
| D | 6 |
| FF | 8 |
| gyro_lpf1_static_hz | 44 |
| gyro_lpf1_dyn_min_hz | 50 |
| gyro_lpf1_dyn_max_hz | 60 |
| gyro_lpf2_static_hz | 40 |
| dterm_lpf1_dyn_min_hz | 20 |
| dterm_lpf1_dyn_max_hz | 30 |
| dterm_lpf2_static_hz | 30 |

Scaled by mechanical `max_delta_scale`. Missing `max_delta` key → 0 (no change).
Only keys present on the **current baseline** are updated.

Donor `apply_safety`:

- confidence &lt; 0.4 + baseline → 50% blend toward baseline
- hardware weight &gt; 800 → D × 0.9
- hard PID: P 10–100, D 5–85, FF 0–220 (I has **no** donor hard min/max)
- gyro_lpf1_static 120–300; dterm dyn min 70–150; dterm dyn max 80–300;
  gyro LPF2 0 or 80–500; dterm LPF2 0 or 80–250
- thermal: no D increase vs baseline; no filter-Hz increase (loosening) vs baseline
  when `thermal_risk` / motor_issue / desync / explicit RPM-DShot unhealthy.
  Gyro filter baseline 0 Hz is non-binding.

### GyroCore-only clamp bridges (Autotune path)

1. **`d_max`** uses the D step cap (6 × scale). Donor had no d_max step.
2. **Firmware OFF (0 Hz)** is not raised to donor advisory minima
   (`apply_safety_autotune`). Donor `apply_safety` still raises gyro static 0 → 120
   (parity tests cover both).
3. **Firmware-legal 0 PID** (yaw D, unused d_max) is not raised to donor D min 5.
4. **Firmware ceilings** `PID_GAIN_MAX=250`, `F_GAIN_MAX=1000`, LPF 1000 Hz
   in addition to donor advisory ranges (never looser than donor P/D/FF caps).
5. Thermal envelope also caps **d_max** to baseline when thermal risk is set.
6. Missing required PID/filter **baseline** fails closed (no invented defaults).

Not migrated: style scaling, AI offsets, `generate_v2_safe_tune`, CLI dump
baseline resolver, D-min Policy A, FF Policy D boost.

## 3. tuning_output_safety

| | Donor | GyroCore |
|---|---|---|
| Compute | `backend.routes.analyze._build_tuning_output_safety` | `evaluate_tuning_output_safety` |
| Attach/HTTP | `backend.services.tuning_output_safety` (`attach` / `ensure` / `normalize`) | **not migrated** |

Donor statuses: `actionable` / `limited` / `blocked`. GyroCore: `PASS` / `WARN` /
`BLOCK` (maps to those donor names in `donor_status` / legacy view).

**Donor domain rules kept:**

- `mechanical_hard_block` → BLOCK
- mechanical limited/caution → WARN
- `quality_status_low_quality` → BLOCK
- `analysis_confidence_low` (score &lt; 0.4) → WARN
- `noise_level_high` → WARN

**Donor rules NOT migrated (web/SaaS/CLI plumbing):**

- `generated_cli_missing_or_invalid` (WU10 has no CLI)
- `limited_cli_not_safely_authorized`
- `hardware_source_default_*` / detected hardware
- motor pole pipeline / CLI baseline poles
- support_matrix_policy / paste_ready_eligible
- config_log_consistency / direction_alignment / phase2
- HTTP attach onto analyze response
- `cli_actionable = status in {actionable, limited} and cli_valid`

**GyroCore-only TOS (fail closed):**

- mechanical / clamp stages must exist (type tokens)
- `unresolved_merge_requires_review`
- `system_id_unusable`
- `invalid_simplified_tuning_state`
- `slider_inconsistency`
- `missing_required_analysis`
- `missing_required_pid_or_filter_baseline`
- `malformed_proposal` / `proposal_blocked`
- resulting values outside firmware limits
- **`cli_actionable` always False in WU10** even on PASS

## 4. Interaction order

1. Mechanical gate (block scale=0; limited scales 0.5–0.75; caution/clear=1.0)
2. Step clamp vs current tune (`apply_to_baseline`)
3. Confidence blend + weight D scale + hard ranges
4. Thermal envelope vs baseline
5. TOS (cannot run without 1–4 tokens)
6. `FinalSafeTuneResult` (`actionable=False`)

There is no public function that maps `AbsoluteTuneProposal` → final result
without constructing each stage. Direct dataclass construction without the
private stage token raises `StageBypassError`.

## 5. WU0 invariants (still mandatory)

1. No actionable CLI unless TOS allows it — WU10 never allows it.
2. Mechanical safety state must exist.
3. Final TOS state must exist.
4. Decision-engine CLI is never authoritative.
5. Missing final safety fails closed.
6. Blocked tune cannot expose paste-ready CLI.
7. Safety chain cannot be bypassed.

## 6. Fail closed

Unknown or incomplete critical states block: missing mechanical result, missing
current PID/filter baseline, unresolved merge review, unusable system-ID,
invalid simplified-tuning, malformed proposal, missing required analysis
(pipeline path), unsupported `simplified_pids_mode=OFF`, values outside firmware
limits. Donor empty-kwargs pass is preserved only on the raw mechanical gate.
