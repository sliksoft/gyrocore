/**
 * Columnar CHIRP frame table — browser counterpart of core/gyrocore/chirp/frames.py.
 *
 * Python builds the table from `blackbox_decode` CSV rows; here the same rows
 * come from FlightLog main frames (every valid frame of the selected log, the
 * frame set already proven identical to native `blackbox_decode`). Only the
 * exact fields upstream `parseChirpLog` reads are materialized — never a full
 * log copy. FlightLog merges the latest S-frame into each main frame, exactly
 * like the CSV, so `flightModeFlags` carries the same per-row state.
 */

import type { FlightLogLike } from "@/decode/normalizeFromFlightLog";

export const SETPOINT_FIELDS = ["setpoint[0]", "setpoint[1]", "setpoint[2]"] as const;
export const GYRO_ADC_FIELDS = ["gyroADC[0]", "gyroADC[1]", "gyroADC[2]"] as const;
export const DEBUG_FIELDS = ["debug[0]", "debug[1]", "debug[2]", "debug[3]"] as const;
export const REQUIRED_FIELDS: readonly string[] = [...SETPOINT_FIELDS, ...GYRO_ADC_FIELDS, ...DEBUG_FIELDS];

/** blackbox-tools FLIGHT_LOG_FLIGHT_MODE_NAME bit 6 ("HEADFREE") carries BOXCHIRP. */
export const BOXCHIRP_BIT = 6;

export type ChirpFrames = {
  timeUs: Float64Array;
  setpoint: [Float64Array, Float64Array, Float64Array];
  gyroAdc: [Float64Array, Float64Array, Float64Array];
  debug: [Float64Array, Float64Array, Float64Array, Float64Array];
  /** Integer flags per row, -1 where the row carries no value; null when the column is absent. */
  flightModeFlags: Int32Array | null;
  malformedRows: number;
  warnings: string[];
  /** Browser input is never subsampled (full-frame policy); kept for contract parity. */
  subsampled: false;
};

export class ChirpFramesError extends Error {}

export type FrameSource = Pick<
  FlightLogLike,
  "getMainFieldNames" | "getMainFieldIndexByName" | "getMinTime" | "getMaxTime" | "getChunksInTimeRange"
>;

function findField(names: string[], name: string): number | undefined {
  // frames.py `_exact_or_alias`: exact name or bracket-less alias, case-insensitive.
  const want = [name.toLowerCase(), name.replace(/[[\]]/g, "").toLowerCase()];
  for (const w of want) {
    const i = names.findIndex((n) => n.trim().toLowerCase() === w);
    if (i >= 0) return i;
  }
  return undefined;
}

const FLIGHT_MODE_FLAGS_ALIASES = ["flightmodeflags", "flight_mode_flags", "flightmodestate", "flight_mode"];

/**
 * Build the CHIRP frame table from an opened FlightLog. Throws
 * `ChirpFramesError("missing_required_field:...")` like `read_chirp_frames_from_csv`.
 */
export function chirpFramesFromFlightLog(log: FrameSource): ChirpFrames {
  const names = log.getMainFieldNames();
  const cols: number[] = [];
  const missing: string[] = [];
  for (const f of REQUIRED_FIELDS) {
    const i = findField(names, f);
    if (i === undefined) missing.push(f);
    else cols.push(i);
  }
  if (missing.length) throw new ChirpFramesError("missing_required_field:" + missing.join(","));
  const tI = findField(names, "time");
  if (tI === undefined) throw new ChirpFramesError("missing_required_field:time");
  const lower = names.map((n) => n.trim().toLowerCase());
  let fmI: number | undefined;
  for (const a of FLIGHT_MODE_FLAGS_ALIASES) {
    const i = lower.indexOf(a);
    if (i >= 0) {
      fmI = i;
      break;
    }
  }

  const min = log.getMinTime();
  const max = log.getMaxTime();
  const chunks =
    Number.isFinite(min) && Number.isFinite(max) && max >= min ? log.getChunksInTimeRange(min, max) : [];
  let total = 0;
  for (const c of chunks) total += c.frames.length;

  const time = new Float64Array(total);
  const vals = REQUIRED_FIELDS.map(() => new Float64Array(total));
  const flags = fmI !== undefined ? new Int32Array(total) : null;
  let n = 0;
  let malformed = 0;
  for (const c of chunks) {
    for (const frame of c.frames) {
      const t = frame[tI];
      let ok = typeof t === "number" && Number.isFinite(t);
      for (let k = 0; ok && k < cols.length; k++) {
        const v = frame[cols[k]!];
        ok = typeof v === "number" && Number.isFinite(v);
      }
      if (!ok) {
        malformed++;
        continue;
      }
      time[n] = t as number;
      for (let k = 0; k < cols.length; k++) vals[k]![n] = frame[cols[k]!] as number;
      if (flags) {
        const f = frame[fmI!];
        // Before the first S-frame FlightLog yields null; the CSV prints an empty
        // cell, which the reference decodes as -1 ("keep previous state").
        flags[n] = typeof f === "number" && Number.isFinite(f) ? Math.trunc(f) : -1;
      }
      n++;
    }
  }
  const warnings: string[] = [];
  if (malformed) warnings.push("malformed_csv_rows_skipped");
  if (fmI === undefined) warnings.push("flight_mode_flags_column_missing");
  const cut = (a: Float64Array) => (n === total ? a : a.slice(0, n));
  return {
    timeUs: cut(time),
    setpoint: [cut(vals[0]!), cut(vals[1]!), cut(vals[2]!)],
    gyroAdc: [cut(vals[3]!), cut(vals[4]!), cut(vals[5]!)],
    debug: [cut(vals[6]!), cut(vals[7]!), cut(vals[8]!), cut(vals[9]!)],
    flightModeFlags: flags ? (n === total ? flags : flags.slice(0, n)) : null,
    malformedRows: malformed,
    warnings,
    subsampled: false,
  };
}
