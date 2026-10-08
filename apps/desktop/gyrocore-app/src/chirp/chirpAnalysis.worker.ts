/// <reference lib="webworker" />

import { runChirpOnBytes, transferablesOf } from "./runChirp";
import type { ChirpRequest, ChirpResponse } from "./types";

const ctx: DedicatedWorkerGlobalScope = self as unknown as DedicatedWorkerGlobalScope;

ctx.onmessage = (ev: MessageEvent<ChirpRequest>) => {
  const started = performance.now();
  try {
    const { buffer, filename, logIndex } = ev.data;
    if (!buffer || !(buffer instanceof ArrayBuffer)) throw new Error("missing_array_buffer");
    const analysis = runChirpOnBytes(new Uint8Array(buffer), { filename: filename || "flight.bbl", logIndex });
    analysis.timingsMs.worker_total = performance.now() - started;
    const response: ChirpResponse = { ok: true, analysis };
    // Transfer the series buffers instead of structured-cloning them.
    ctx.postMessage(response, transferablesOf(analysis));
  } catch (err) {
    const response: ChirpResponse = {
      ok: false,
      error: String((err as Error)?.message ?? err ?? "chirp_failed"),
      timingsMs: { worker_total: performance.now() - started },
    };
    ctx.postMessage(response);
  }
};
