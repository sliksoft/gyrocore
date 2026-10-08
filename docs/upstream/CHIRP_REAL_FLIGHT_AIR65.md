# CHIRP real-flight qualification: AIR65 (2026-10-05)

Diagnosis of why every CHIRP segment in the first real AIR65 log is rejected
(`low_coherence`), and the protocol for the next CHIRP flight. Thresholds are
**unchanged**; numbers below are diagnostics, not new gates.

- Craft: `AIR65 C`, `BETAFPVG473`, Betaflight 2026.6.2, 1S, ANGLE mode during CHIRP
- File: `BTFL_BLACKBOX_LOG_AIR65_C_20261005_224215_BETAFPVG473.BBL` (local only, not committed)
- CHIRP config (headers, all 3 logs): `debug_mode = 96` (CHIRP), sweep 0.2 → 600 Hz in
  20 s, amplitude roll/pitch 230 °/s, yaw 180 °/s, lead-lag 3 / 30 Hz, logged at 4 kHz
- Tool: `PYTHONPATH=.:core python3 tools/chirp_reference/diagnose_chirp.py LOG.BBL [--json out]`.
  It runs the unchanged reference pipeline and adds the following from the same decoded CSV:
  sweep coverage (`debug[2]`, chirp frequency), spectra and coherence by band,
  operating point, saturation, stick input, disturbance events, event-free coherence
  and axis coupling.

## 1. Software vs data

The parser and pipeline are not the cause:

- browser and Python agree within 1e-10 on all 3 logs (CHIRP_BROWSER_WU1)
- sample rate is header-confirmed at 4 kHz (timestamp 4032 Hz, 0.8 %)
- timestamps are 97.7–98.7 % uniform, with gaps ≤ 0.11 % and no resets

Where the excitation was clean and actually swept, coherence is 0.99. Every
rejection is a **data-quality** result.

## 2. Per-segment findings

| | Log 1 roll | Log 2 pitch | Log 3 yaw | Log 3 roll | Log 3 pitch |
|---|---|---|---|---|---|
| Segment (s) | 13.90–20.63 | 39.11–43.02 | 54.72–68.84 | 74.46–89.40 | 92.06–110.92 |
| Duration / 20 s | 6.7 s (34 %) | 3.9 s (20 %) | 14.1 s (71 %) | 14.9 s (75 %) | 18.9 s (94 %) |
| End cause | log ended during chirp | log ended during chirp | CHIRP switched off | CHIRP switched off | log ended during chirp |
| Sweep reached (`debug[2]`) | 3.0 Hz | 1.0 Hz | 60.1 Hz | 83.5 Hz | 406.5 Hz |
| 5–100 Hz gate window swept | 0 % | 0 % | 58 % | 83 % | 100 % |
| Samples / Welch segs | 27 136 / 25 | 15 774 / 14 | 57 009 / 54 | 60 298 / 57 | 76 112 / 73 |
| Setpoint RMS (°/s) | 159 | 125 | 68 | 84 | 70 |
| Gate mean coherence (≥ 0.6) | 0.354 | 0.409 | 0.534 | 0.590 | 0.169 |
| Mean coherence, swept part of gate window | not swept | not swept | 0.93 (5–60 Hz) | 0.72 (5–83.5 Hz) | 0.17 |
| Bins ≥ 0.6 in gate window | 14 % | 33 % | 53 % | 59 % | 4 % |
| Usable range (coh ≥ 0.5) | 3.9–113 Hz, 11 bins | 3.9–600 Hz, 113 bins | 2.0–56.6 Hz | 2.0–70.3 Hz | 2.0–9.8 Hz, 5 bins |
| Disturbance events* | 5, incl. last 1.3 s | 2 (2.9 s, 3.6–3.9 s) | none | none | 4 (2.9–5.0 s, 18.4 s) |
| Gyro peak / clip | 2040 °/s, 0.25 % clipped | 2191 °/s, 1.9 % clipped | 175 | 241 | 860 |
| Motors saturated high / at min | 18 % / 10 % | 0.1 % / 12 % | 0 / 0 | 0 / 0 | 0.04 % / 3.8 % |
| Throttle `rcCommand[3]` | 1000–1568 | 1000–1484 | 1208–1428 | 1296–1402 | 1000–1410 |
| VBAT start → min (1S) | 4.09 → 3.06 V | 3.82 → 3.19 V | 3.76 → 3.53 V | 3.67 → 3.41 V | 3.58 → 3.04 V |
| Stick on excited axis: mean / std (of ±500) | 1 / 98 | −16 / 98 | 2 / 16 | 56 / 81 | 23 / 43 |
| Off-axis gyro / excited gyro (RMS) | 0.43, 0.38 | 0.86, 0.62 | 0.06, 0.04 | 0.04, 0.03 | 0.40, 0.05 |
| Excitation → off-axis gyro coherence | n/a | n/a | 0.07, 0.04 | 0.08, 0.27 | 0.004, 0.012 |

\* Any-axis gyro > 500 °/s, a motor ≥ 98 % of the output range, or throttle ≤ 1050.
The excitation itself never exceeds 230 °/s, so these are loss-of-control,
saturation or throttle-cut events.

Body attitude: `debug[4..7]` (angle and angle target) are all zero in this
firmware build, so body angle is not logged.

Coherence by band in the clean segments shows where identification works:

| Band (Hz) | 1–2 | 2–5 | 5–10 | 10–20 | 20–50 | 50–100 | 100–200 | 200–600 |
|---|---|---|---|---|---|---|---|---|
| Log 3 yaw | 0.997 | 0.994 | 0.993 | 0.990 | 0.984 | 0.13 (unswept above 60) | — | — |
| Log 3 roll | 0.994 | 0.990 | 0.993 | 0.987 | 0.899 | 0.29 (unswept above 83.5) | — | — |
| Log 3 pitch, event-free 5.0–18.4 s (1.5–336 Hz swept) | 0.995 | 0.988 | 0.991 | 0.992 | 0.916 | 0.438 | 0.087 | 0.032 |
| Log 3 pitch, whole segment | 0.942 | 0.898 | 0.677 | 0.317 | 0.169 | 0.082 | 0.036 | 0.041 |

**Usable** is 1–50 Hz: coherence above 0.9 on every axis that was swept cleanly.
**Marginal** is 50–100 Hz, around 0.3–0.45. **Fails** is above 100 Hz, below 0.1.
Applying the unchanged gate to the event-free pitch window gives a mean of
**0.675** (pass) over 5–100 Hz. That is 0.94 across the 23 bins in 5–50 Hz and
0.44 across the 26 bins in 50–100 Hz.

## 3. Classification

| Log | Primary | Secondary |
|---|---|---|
| 1 (roll) | INSUFFICIENT_DURATION: sweep stopped at 3 Hz, 0 % of the gate window excited | BAD_OPERATING_POINT: loss of control from 0.35 Hz (2040 °/s, motors pinned, throttle to 1000), then the log ended; PILOT_INPUT_CONTAMINATION: roll stick std 98 |
| 2 (pitch) | INSUFFICIENT_DURATION: sweep stopped at 1 Hz, 0 % excited | BAD_OPERATING_POINT: loss of control at 0.6–1 Hz (2191 °/s, 1.9 % clipped), then the log ended |
| 3 yaw | INSUFFICIENT_DURATION: switched off at 71 % (60 Hz); swept part 0.93 | LOW_SNR above 50 Hz |
| 3 roll | INSUFFICIENT_DURATION: switched off at 75 % (83.5 Hz); gate 0.590 vs 0.6 | LOW_SNR above 50 Hz |
| 3 pitch | BAD_OPERATING_POINT: saturation events at 0.6–1.5 Hz (2.9–5.0 s) and a throttle cut / impact at 18.4 s | LOW_SNR above 50 Hz |

`PRIMARY_LOW_COHERENCE_CAUSE = INSUFFICIENT_DURATION`. No sweep completed: 2
ended with the log during loss of control and 2 were switched off early. The gate
averages coherence over the fixed 5–100 Hz window, so unexcited bins count as
incoherent. This is the gate's definition, not a defect: unexcited bins carry no
identification.

Secondary causes:

1. **BAD_OPERATING_POINT.** Large attitude excursions below about 2 Hz at 230 °/s
   saturated the motors and gyro in 3 of 5 segments. At 0.4 Hz, 230 °/s is a
   ±92° swing (230 / 2π·0.4), so the excitation is too *strong* at low
   frequency, not too weak. A few saturated Welch segments add broadband
   uncorrelated output power, which collapses coherence everywhere (pitch: 0.17
   whole segment vs 0.675 event-free). The 1S pack also sagged to 3.0–3.4 V.
2. **LOW_SNR above about 50 Hz.** The 3/30 Hz lead-lag shaping leaves about 17 °/s
   of excitation above 30 Hz. Closed-loop gyro response is about 3 °/s at
   50–100 Hz and 1.7 °/s at 100–200 Hz, where gyro LPF1 (150 Hz) and LPF2
   (300 Hz) also act.

Not the cause:

- **EXCITATION_TOO_WEAK:** setpoint RMS was 68–159 °/s against a 5 °/s gate.
- **TIMESTAMP_OR_GAP_PROBLEM:** gaps ≤ 0.11 % and uniformity ≥ 97.7 %, rate confirmed.
- **AXIS_COUPLING:** cross-coherence ≤ 0.27 and off-axis gyro ≤ 6 % in clean segments.
- **PILOT_INPUT_CONTAMINATION** is present but not primary. The pilot held roll at
  about +56–71 throughout, with std 25–81, yet coherence is 0.99 from 1–20 Hz in
  those same segments. Stick input on the excited axis is part of the measured
  setpoint; it only harms identification through the attitude excursions it
  causes.

## 4. Next AIR65 CHIRP flight protocol

Use the existing firmware CHIRP and existing CLI parameters only, every change in
the *less* aggressive direction. The GyroCore gates and safety mapping are
unchanged.

**Blackbox / debug configuration**

- `set debug_mode = CHIRP`
- keep the 4 kHz logging rate and current fields (gyro, setpoint, rcCommand, motors, vbat)
- erase onboard flash before the session

**CHIRP parameters (per PID profile)**

| Parameter | Now | Next | Why |
|---|---|---|---|
| `chirp_frequency_start_deci_hz` | 2 (0.2 Hz) | **20 (2 Hz)** | Removes the 0.2–2 Hz phase where all 3 loss-of-control episodes began (0.35–0.64 Hz). Swing at 2 Hz is about ±18° vs ±92° at 0.4 Hz, and 5.8 s of sweep time is freed |
| `chirp_frequency_end_deci_hz` | 6000 (600 Hz) | **3000 (300 Hz)** | Coherence above 100 Hz was < 0.1 even when clean; gyro LPF1 150 Hz / LPF2 300 Hz |
| `chirp_time_seconds` | 20 | 20 | unchanged |
| `chirp_amplitude_roll / _pitch / _yaw` | 230 / 230 / 180 | unchanged; **never increase** | Low-frequency saturation is solved by the start frequency. If any abort still shows saturation, repeat with roll/pitch 180 |
| `chirp_lag_freq_hz / _lead_freq_hz` | 3 / 30 | unchanged | |

The firmware sweep is exponential. `debug[2]` follows `f0·(f1/f0)^(t/T)`: the reported end frequency is within 7 % of the model in all 5 segments, and the measured 3.89 s in 0.2–1 Hz matches the model's 4.0 s.
Dwell per octave is `T / log2(f1/f0)`:

- **now:** 20 / 11.55 = 1.73 s/octave, with 7.5 s in 5–100 Hz
- **next:** 20 / 7.23 = 2.77 s/octave, with 12.0 s in 5–100 Hz (×1.6)

With a fixed record, signal energy per bin scales with dwell while the noise does
not. On the event-free pitch data, 50–100 Hz coherence would rise from about
0.44 to about 0.55, and the projected gate mean from 0.675 to about 0.74. This
is an estimate, not a guarantee.

**Procedure**

1. **Pack and conditions.** Fresh pack, resting ≥ 4.1 V. Indoors or calm air, at
   least 3 m clear around. Check accelerometer trim first: the pilot held about
   +60 roll stick throughout the previous flight.
2. **Arm in ANGLE mode.** Hover at 1–1.5 m with throttle steady near the observed
   hover point (`rcCommand[3]` ≈ 1330–1360, motors about 30 %). Wait 3 s for a
   stable, hands-off hover.
3. **One axis per CHIRP activation.** The firmware advances the axis on each
   activation; these logs show roll → pitch → yaw → roll → pitch. Do roll, then
   pitch, then yaw, and confirm the axis afterwards from GyroCore's segment axis.
4. **Run the full sweep.** Keep the CHIRP switch on for at least 22 s (the sweep is
   20 s). Never switch off early: two of the previous sweeps were switched off
   at 14–15 s.
5. **Pilot during excitation.** Hands off roll, pitch and yaw. Small throttle
   corrections only, to hold height. Do not chop throttle. Do not fight the
   twitching. It is expected, and the excitation shrinks with frequency.
6. **Between axes.** Switch CHIRP off, hover 3 s, then activate the next axis.
   Land after one roll + pitch + yaw set per pack (about 75 s armed).

**Abort** (switch CHIRP off, recover in ANGLE, land; the repetition does not count):

- tilt beyond about 30°, a flip, or any visible loss of attitude control
- drift over 1 m, or any stick input needed beyond small throttle corrections
- motors audibly at full or cut (desync, prop strike), or any contact
- OSD/VBAT under load below 3.5 V
- the chirp does not start, or the craft yaws continuously

**Acceptance per repetition** (from `diagnose_chirp.py` plus the unchanged gate):

- GyroCore status `ok` or `usable_with_warnings` for the axis. The gate requires
  mean coherence over 5–100 Hz ≥ 0.6, at least 8 bins with coherence ≥ 0.5, and
  the gaps, uniformity, excitation and sample-count gates.
- Sweep completion ≥ 98 %, ending on `debug[1] = -1`, not on log end or switch-off
- No disturbance events
- Coherence ≥ 0.9 across 5–50 Hz (the PID-relevant band seen above)

**Repetitions.** 3 accepted sweeps per axis (9 total; about 3 packs). The
repetitions must agree to within ±1 dB magnitude and ±10° phase over 5–50 Hz
before the dataset is used for PID/filter work.
