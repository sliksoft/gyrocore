/**
 * Pure browser CHIRP entry: BBL bytes -> FlightLog (every valid main frame of
 * the selected log) -> CHIRP frame table -> identifyChirpSystem -> contract.
 *
 * Runs inside the CHIRP Web Worker; kept free of worker globals so Vitest can
 * exercise it directly. No network, no Tauri, no file paths.
 */

import { FlightLog } from "@bf-blackbox/flightlog.js";
import { readLogHeaders } from "@/decode/headers";
import { normalizeFromFlightLog, type FlightLogLike } from "@/decode/normalizeFromFlightLog";
import { ChirpFramesError, chirpFramesFromFlightLog } from "./frames";
import { identifyChirpSystem, UPSTREAM_PROVENANCE } from "./pipeline";
import { parseChirpSysConfig, readHeaderPairs, sysConfigToDict, validateChirpDebugMode } from "./sysconfig";
import {
  AXIS_NAMES,
  type ChirpAxisResult,
  type ChirpBrowserAnalysis,
  type ChirpRejection,
  type ChirpSystemIdResult,
} from "./types";

const USABLE_STATUSES: ReadonlySet<string> = new Set(["ok", "usable_with_warnings"]);

/**
 * CHIRP contract invariants for a usable axis: the violated invariant's code, or
 * null when the axis may be reported as available.
 *
 * - frequency / magnitude / phase / coherence all non-empty and equal length
 * - a valid usable frequency range (finite, 0 <= lo <= hi, inside the analysis band)
 * - a usable mask over the same bins with at least one usable bin
 * - finite frequency / magnitude / phase and coherence in [0, 1] on every usable bin
 *   (floored bins outside the usable band are legitimately -Infinity dB)
 */
export function chirpAxisViolation(ax: ChirpAxisResult): string | null {
  const tf = ax.transfer_function;
  if (!tf) return "chirp_series_empty";
  const n = tf.frequencies_hz.length;
  if (!n || !tf.magnitude_db.length || !tf.phase_deg.length || !tf.coherence.length) return "chirp_series_empty";
  if (tf.magnitude_db.length !== n || tf.phase_deg.length !== n || tf.coherence.length !== n) {
    return "chirp_series_length_mismatch";
  }
  const range = ax.quality.usable_range_hz;
  const [bandLo, bandHi] = ax.quality.analysis_band_hz;
  if (
    !range ||
    !Number.isFinite(range[0]) ||
    !Number.isFinite(range[1]) ||
    !(range[0] >= 0 && range[0] <= range[1]) ||
    range[0] < bandLo ||
    range[1] > bandHi
  ) {
    return "chirp_invalid_frequency_range";
  }
  const mask = ax.usable_mask;
  if (!mask || mask.length !== n) return "chirp_invalid_usable_band";
  let bins = 0;
  for (let k = 0; k < n; k++) {
    if (!mask[k]) continue;
    bins++;
    const coh = tf.coherence[k]!;
    if (
      !Number.isFinite(tf.frequencies_hz[k]!) ||
      !Number.isFinite(tf.magnitude_db[k]!) ||
      !Number.isFinite(tf.phase_deg[k]!) ||
      !(coh >= 0 && coh <= 1)
    ) {
      return "chirp_nonfinite_usable_band";
    }
  }
  return bins ? null : "chirp_invalid_usable_band";
}

/** First usable axis that satisfies every CHIRP contract invariant. */
export function primaryUsableAxis(result: ChirpSystemIdResult) {
  for (const name of AXIS_NAMES) {
    const ax = result.axes[name];
    if (ax?.usable && chirpAxisViolation(ax) === null) return ax;
  }
  return null;
}

/** Structured rejection; null only for a usable result whose status and series satisfy the contract. */
export function chirpRejection(result: ChirpSystemIdResult): ChirpRejection | null {
  if (result.status === "error") {
    return { code: (result.errors[0] ?? "chirp_error").split(":")[0]!, detail: result.errors.join("; ") };
  }
  if (!result.detected) return { code: "no_chirp_segments", detail: "No CHIRP-active segment in the selected log." };
  if (!result.usable) {
    return { code: "chirp_unusable", detail: result.errors.join("; ") || "No axis passed the CHIRP validity gates." };
  }
  if (!USABLE_STATUSES.has(result.status)) {
    return { code: "chirp_status_inconsistent", detail: `Usable result with status "${result.status}".` };
  }
  if (!primaryUsableAxis(result)) {
    const usable = AXIS_NAMES.map((name) => result.axes[name]).filter((ax) => ax?.usable);
    const code = (usable.length ? chirpAxisViolation(usable[0]!) : null) ?? "chirp_series_empty";
    return { code, detail: "Usable status without valid magnitude/phase/coherence series." };
  }
  return null;
}

function errorOnly(code: string, sysconfig: ReturnType<typeof parseChirpSysConfig> | null): ChirpSystemIdResult {
  return {
    status: "error",
    usable: false,
    detected: false,
    analysis_only: true,
    tuning_recommendations: null,
    sysconfig: sysconfig ? sysConfigToDict(sysconfig) : null,
    extraction: null,
    axes: {},
    warnings: [],
    errors: [code],
    provenance: { ...UPSTREAM_PROVENANCE },
  };
}

/** Same embedded-log choice as the decode worker (explicit index, else recommended). */
function chooseLogIndex(log: FlightLogLike, bytes: Uint8Array, filename: string, requested: number | null | undefined) {
  const count = log.getLogCount();
  if (requested != null && requested >= 0 && requested < count) return requested;
  return normalizeFromFlightLog(log, {
    filename,
    sizeBytes: bytes.byteLength,
    includeSeries: false,
    rawHeadersForLog: (i) => readLogHeaders(bytes, i),
  }).embedded.recommendedIndex;
}

export function runChirpOnBytes(
  bytes: Uint8Array,
  opts: { filename: string; logIndex?: number | null },
): ChirpBrowserAnalysis {
  const t0 = performance.now();
  const log = new FlightLog(bytes) as unknown as FlightLogLike;
  return runChirpOnLog(log, bytes, opts, performance.now() - t0);
}

/**
 * CHIRP on an already-indexed FlightLog of `bytes` (the browser session reuses the
 * FlightLog built at decode time instead of decoding the file a second time).
 */
export function runChirpOnLog(
  log: FlightLogLike,
  bytes: Uint8Array,
  opts: { filename: string; logIndex?: number | null },
  indexMs = 0,
): ChirpBrowserAnalysis {
  const timingsMs: Record<string, number> = {};
  const t0 = performance.now() - indexMs;
  const logCount = log.getLogCount();
  if (logCount < 1) throw new Error("no_embedded_logs");
  const logIndex = chooseLogIndex(log, bytes, opts.filename, opts.logIndex);
  if (!log.openLog(logIndex)) throw new Error(`failed_to_open_log_index:${logIndex}`);
  timingsMs.index = performance.now() - t0;

  // Mirror the reference ordering: debug-mode check, then frame-table columns.
  const tHeaders = performance.now();
  let sysconfig: ReturnType<typeof parseChirpSysConfig> | null = null;
  let result: ChirpSystemIdResult | null = null;
  try {
    sysconfig = parseChirpSysConfig(readHeaderPairs(bytes, logIndex));
  } catch (err) {
    result = errorOnly(`invalid_headers:${String((err as Error).message ?? err)}`, null);
  }
  if (!result && sysconfig) {
    const [, , err] = validateChirpDebugMode(sysconfig, null);
    if (err) result = errorOnly(err, sysconfig);
  }
  timingsMs.headers = performance.now() - tHeaders;

  let framesDecoded = 0;
  if (!result) {
    const tFrames = performance.now();
    try {
      const frames = chirpFramesFromFlightLog(log);
      framesDecoded = frames.timeUs.length;
      timingsMs.segment_extraction = performance.now() - tFrames;
      const tCompute = performance.now();
      result = identifyChirpSystem({ frames, sysconfig });
      timingsMs.compute = performance.now() - tCompute;
    } catch (err) {
      if (!(err instanceof ChirpFramesError)) throw err;
      result = errorOnly(err.message, sysconfig);
    }
  }
  timingsMs.total = performance.now() - t0;
  return {
    schemaVersion: 1,
    engine: "gyrocore-browser-chirp",
    result,
    rejection: chirpRejection(result),
    source: {
      filename: opts.filename,
      sizeBytes: bytes.byteLength,
      logIndex,
      logCount,
      decoder: "betaflight-flightlog-js",
      framesDecoded,
      inputPolicy: "full_frame",
    },
    timingsMs,
  };
}

/** Typed-array buffers of the result, for zero-copy `postMessage` transfer. */
export function transferablesOf(analysis: ChirpBrowserAnalysis): ArrayBuffer[] {
  const out = new Set<ArrayBuffer>();
  for (const ax of Object.values(analysis.result.axes)) {
    if (!ax) continue;
    const tf = ax.transfer_function;
    const arrays = [
      tf?.frequencies_hz,
      tf?.h_real,
      tf?.h_imag,
      tf?.magnitude_db,
      tf?.phase_deg,
      tf?.coherence,
      ax.usable_mask,
      ax.step_response?.time_ms,
      ax.step_response?.response,
    ];
    for (const a of arrays) if (a && a.buffer instanceof ArrayBuffer) out.add(a.buffer);
  }
  return [...out];
}
