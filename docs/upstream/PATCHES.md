# Local patches to vendored upstream sources

Every intentional modification of a file under `third_party/` is listed here. Upstream
copyright, license (GPL-3.0) and SPDX notices are untouched; patched lines are marked
`GyroCore local patch` in the source.

## blackbox-tools: consume FLIGHTMODE / DISARM event payloads

| | |
| --- | --- |
| Upstream | https://github.com/betaflight/blackbox-tools @ `f832acf9cd9dbe5ad8220de1a5f4eb4021523d72` |
| Files | `src/parser.c`, `src/blackbox_fielddefs.h`, `src/blackbox_decode.c` |
| Size | +34 lines, no deletions |
| Status upstream | Still unhandled on upstream `master` (checked 2026-10-08); suitable for a later upstream PR. Nothing submitted. |

### Bug

`parseEventFrame` (`src/parser.c`) consumes payloads only for SYNC_BEEP (0), INFLIGHT_ADJUSTMENT
(13), LOGGING_RESUME (14) and LOG_END (255). For any other type it reads the type byte and
sets `lastEvent.event = -1`, leaving the payload in the stream. The main parse loop then reads
the payload as a frame marker:

- lead byte not a frame marker (`I P E S G H`) → `mainStreamIsValid = false`; P-frames cannot
  resynchronise, so **every valid main frame is dropped until the next I-frame**
  (`loopIteration % I interval == 0`) or end of log;
- lead byte `0x45` ('E') → re-enters event parsing and happens to resync (no loss).

Betaflight writes FLIGHTMODE (30) with two unsigned VB values (`newFlags`, `lastFlags`) on
every flight-mode flag change, and DISARM (15) with one unsigned VB (`reason`) just before
LOG_END. Disarm (69→68, lead `0x44`) and mode-off (69→5, lead `0x05`) transitions therefore
drop frames, including **mid-flight**.

### Event audit

| EVENT_TYPE | EXPECTED_PAYLOAD (Betaflight writer / FlightLog reader) | CURRENT_NATIVE_BEHAVIOR | FIX_REQUIRED |
| --- | --- | --- | --- |
| 0 SYNC_BEEP | uVB time | consumed | no |
| 13 INFLIGHT_ADJUSTMENT | u8 function + sVB or float32 | consumed | no |
| 14 LOGGING_RESUME | uVB iteration, uVB time | consumed | no |
| 15 DISARM | uVB reason | type byte only → payload left in stream | **yes (patched)** |
| 30 FLIGHTMODE | uVB newFlags, uVB lastFlags | type byte only → desync unless lead byte is 'E' | **yes (patched)** |
| 255 LOG_END | "End of log\0" | consumed | no |
| 10/11/12 AUTOTUNE_*, 20 GTUNE_CYCLE_RESULT | fixed bytes (legacy Cleanflight/Baseflight) | type byte only | no — not written by current Betaflight; out of scope |
| 40 TWITCH_TEST | u8 stage + u32 | type byte only | no — not written by Betaflight firmware; out of scope |

### Fix

Add `FLIGHT_LOG_EVENT_DISARM = 15`, payload structs for both events, and `case`s in
`parseEventFrame` that read the unsigned VB payloads. `blackbox_decode.c` `onEvent` gains
matching event-file lines ("Disarm", "Flight mode") instead of falling into "Unknown event".
No parser restructuring; main-frame decoding, CSV columns and all other events are unchanged.

### Reproduction (local 3-log BBL, not committed)

Unpatched = vendored source at `e431d48`; patched = this tree. Frames are identical except the
recovered rows; recovery points are I-frames (multiples of the 128 I interval).

| log | offset | type | payload | lead byte is frame marker | last native frame before loss (iter, time µs) | recovery I-frame (iter) | dropped |
|---|---|---|---|---|---|---|---|
| 1 | 0xee69a | 30 | `45 05` | yes | — | — | 0 |
| 1 | 0x1f8ae9 | 30 | `44 45` | no | 51607, 20611283 | none (LOG_END) | 61 |
| 1 | 0x1f9471 | 15 | `04` | no | — | — | 0 (LOG_END follows) |
| 1 | | | | | | **total** | **61** (old 51608 → new 51669) |
| 2 | 0x2c53fa | 30 | `45 05` | yes | — | — | 0 |
| 2 | 0x35effb | 30 | `44 45` | no | 36591, 43001057 | 36608 | 16 |
| 2 | 0x35fa29 | 15 | `04` | no | — | — | 0 (LOG_END follows) |
| 2 | | | | | | **total** | **16** (old 36641 → new 36657) |
| 3 | 0x41e439 | 30 | `45 05` | yes | — | — | 0 |
| 3 | 0x65363a | 30 | `05 45` | no | 76497, 68839712 | 76544 | 46 |
| 3 | 0x7300ff | 30 | `45 05` | yes | — | — | 0 |
| 3 | 0x98842e | 30 | `05 45` | no | 159512, 89400374 | 159616 | 103 |
| 3 | 0x9f046a | 30 | `45 05` | yes | — | — | 0 |
| 3 | 0xcee172 | 30 | `44 45` | no | 246262, 110891662 | 246272 | 9 |
| 3 | 0xcef23c | 15 | `04` | no | — | — | 0 (LOG_END follows) |
| 3 | | | | | | **total** | **158** (old 246200 → new 246358) |

Committed regression: `tests/fixtures/decode/mode_events.bbl.gz` (generator
`tools/decode_reference/make_mode_event_fixture.py`): 640 frames, I interval 32, five mid-log
FLIGHTMODE/DISARM events including a multi-byte VB payload. Unpatched → 578 frames, patched → 640.
Guarded by `tests/core/test_decode_full_frame.py` (Core) and
`apps/desktop/gyrocore-app/src/decode/parity.fixtures.test.ts` (browser/native parity).

### Building

CI builds the decoder out of tree from this vendored source in every job (`core-tests`,
`desktop`, `integrity`). Locally:

```bash
cp -r third_party/betaflight/blackbox-tools /tmp/bbt && make -C /tmp/bbt obj/blackbox_decode
sudo install -m 755 /tmp/bbt/obj/blackbox_decode /usr/local/bin/blackbox_decode
```
