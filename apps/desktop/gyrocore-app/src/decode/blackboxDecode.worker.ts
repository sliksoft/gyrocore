/// <reference lib="webworker" />

import { FlightLog } from "@bf-blackbox/flightlog.js";
import { readLogHeaders } from "./headers";
import { normalizeFromFlightLog } from "./normalizeFromFlightLog";
import type { DecodeRequest, DecodeResponse } from "./types";

const ctx: DedicatedWorkerGlobalScope = self as unknown as DedicatedWorkerGlobalScope;

ctx.onmessage = (ev: MessageEvent<DecodeRequest>) => {
  const started = performance.now();
  const timingsMs: Record<string, number> = {};
  try {
    const { buffer, filename, logIndex, includeSeries } = ev.data;
    if (!buffer || !(buffer instanceof ArrayBuffer)) {
      throw new Error("missing_array_buffer");
    }
    const tRead = performance.now();
    const bytes = new Uint8Array(buffer);
    timingsMs.read = performance.now() - tRead;

    const tIndex = performance.now();
    const log = new FlightLog(bytes);
    const count = log.getLogCount();
    if (count < 1) throw new Error("no_embedded_logs");
    timingsMs.index = performance.now() - tIndex;

    const tNorm = performance.now();
    const result = normalizeFromFlightLog(log, {
      filename: filename || "flight.bbl",
      sizeBytes: bytes.byteLength,
      selectedIndex: logIndex ?? null,
      includeSeries: includeSeries !== false,
      rawHeadersForLog: (i) => readLogHeaders(bytes, i),
    });
    timingsMs.normalize = performance.now() - tNorm;
    timingsMs.total = performance.now() - started;

    const response: DecodeResponse = { ok: true, result, timingsMs };
    ctx.postMessage(response);
  } catch (err) {
    timingsMs.total = performance.now() - started;
    const response: DecodeResponse = {
      ok: false,
      error: String(err || "decode_failed"),
      timingsMs,
    };
    ctx.postMessage(response);
  }
};
