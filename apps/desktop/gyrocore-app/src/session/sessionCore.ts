/**
 * Browser analysis session state (runs inside the session Web Worker; kept free of
 * worker globals so Vitest can drive it directly).
 *
 * The BBL is decoded once on `open`; `analyze` reuses that FlightLog for the
 * selected embedded log (metadata + CHIRP), so Begin analysis never decodes the
 * file again. Nothing leaves the worker except the normalized summary and the
 * CHIRP result.
 */

import { FlightLog } from "@bf-blackbox/flightlog.js";
import { transferablesOf, runChirpOnLog } from "@/chirp/runChirp";
import { readLogHeaders } from "@/decode/headers";
import { normalizeFromFlightLog, type FlightLogLike } from "@/decode/normalizeFromFlightLog";
import type { SessionRequest, SessionResponse } from "./types";

type Loaded = { bytes: Uint8Array; log: FlightLogLike; filename: string };

export function createSessionCore(build: (bytes: Uint8Array) => FlightLogLike = (b) => new FlightLog(b) as unknown as FlightLogLike) {
  let loaded: Loaded | null = null;
  let flightLogBuilds = 0;

  const summarize = (l: Loaded, selectedIndex: number | null) =>
    normalizeFromFlightLog(l.log, {
      filename: l.filename,
      sizeBytes: l.bytes.byteLength,
      selectedIndex,
      includeSeries: false,
      rawHeadersForLog: (i) => readLogHeaders(l.bytes, i),
    });

  function handle(req: SessionRequest): { response: SessionResponse; transfer: Transferable[] } {
    try {
      if (req.type === "open") {
        const t0 = performance.now();
        if (!(req.buffer instanceof ArrayBuffer)) throw new Error("missing_array_buffer");
        const bytes = new Uint8Array(req.buffer);
        const log = build(bytes);
        flightLogBuilds++;
        if (log.getLogCount() < 1) throw new Error("no_embedded_logs");
        loaded = { bytes, log, filename: req.filename || "flight.bbl" };
        const tIndex = performance.now() - t0;
        const decoded = summarize(loaded, null);
        const timingsMs = { index: tIndex, normalize: performance.now() - t0 - tIndex, total: performance.now() - t0 };
        return { response: { id: req.id, ok: true, type: "open", decoded, timingsMs, flightLogBuilds }, transfer: [] };
      }
      if (!loaded) throw new Error("session_not_open");
      const count = loaded.log.getLogCount();
      if (!Number.isInteger(req.logIndex) || req.logIndex < 0 || req.logIndex >= count) {
        throw new Error(`invalid_log_index:${req.logIndex}`);
      }
      const decoded = summarize(loaded, req.logIndex);
      const analysis = runChirpOnLog(loaded.log, loaded.bytes, { filename: loaded.filename, logIndex: req.logIndex });
      return {
        response: { id: req.id, ok: true, type: "analyze", decoded, analysis, flightLogBuilds },
        transfer: transferablesOf(analysis),
      };
    } catch (err) {
      return { response: { id: req.id, ok: false, error: String((err as Error)?.message ?? err) }, transfer: [] };
    }
  }

  return { handle, flightLogBuilds: () => flightLogBuilds };
}
