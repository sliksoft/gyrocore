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
import { AXIS_NAMES, type ChirpBrowserAnalysis, type ChirpRejection, type ChirpSystemIdResult } from "./types";

/** First usable axis with non-empty, equal-length magnitude/phase/coherence series. */
export function primaryUsableAxis(result: ChirpSystemIdResult) {
  for (const name of AXIS_NAMES) {
    const ax = result.axes[name];
    const tf = ax?.transfer_function;
    if (!ax?.usable || !tf) continue;
    const n = tf.frequencies_hz.length;
    if (n > 0 && tf.magnitude_db.length === n && tf.phase_deg.length === n && tf.coherence.length === n) return ax;
  }
  return null;
}

/** Structured rejection; null only for a usable result that has real series. */
export function chirpRejection(result: ChirpSystemIdResult): ChirpRejection | null {
  if (result.status === "error") {
    return { code: (result.errors[0] ?? "chirp_error").split(":")[0]!, detail: result.errors.join("; ") };
  }
  if (!result.detected) return { code: "no_chirp_segments", detail: "No CHIRP-active segment in the selected log." };
  if (!result.usable) {
    return { code: "chirp_unusable", detail: result.errors.join("; ") || "No axis passed the CHIRP validity gates." };
  }
  if (!primaryUsableAxis(result)) {
    return { code: "chirp_series_empty", detail: "Usable status without magnitude/phase/coherence series." };
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
  const timingsMs: Record<string, number> = {};
  const t0 = performance.now();
  const log = new FlightLog(bytes) as unknown as FlightLogLike;
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
