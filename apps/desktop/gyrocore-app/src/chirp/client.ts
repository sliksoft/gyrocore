import type { ChirpBrowserAnalysis, ChirpRequest, ChirpResponse } from "./types";

export type AnalyzeChirpOptions = {
  logIndex?: number | null;
  /** Injected worker factory for tests. */
  createWorker?: () => Worker;
};

/**
 * Run browser CHIRP analysis in a dedicated Web Worker (no upload, no Tauri).
 * The worker decodes the log itself so full-frame series never reach the main thread.
 */
export async function analyzeChirpFile(
  file: File,
  options: AnalyzeChirpOptions = {},
): Promise<ChirpBrowserAnalysis> {
  return analyzeChirpBuffer(await file.arrayBuffer(), file.name, options);
}

export async function analyzeChirpBuffer(
  buffer: ArrayBuffer,
  filename: string,
  options: AnalyzeChirpOptions = {},
): Promise<ChirpBrowserAnalysis> {
  const tStart = performance.now();
  const worker =
    options.createWorker?.() ?? new Worker(new URL("./chirpAnalysis.worker.ts", import.meta.url), { type: "module" });
  const workerStartMs = performance.now() - tStart;
  const request: ChirpRequest = { buffer, filename, logIndex: options.logIndex ?? null };
  try {
    const response = await new Promise<ChirpResponse>((resolve, reject) => {
      const onMessage = (ev: MessageEvent<ChirpResponse>) => {
        cleanup();
        resolve(ev.data);
      };
      const onError = (err: ErrorEvent) => {
        cleanup();
        reject(new Error(err.message || "chirp_worker_error"));
      };
      const cleanup = () => {
        worker.removeEventListener("message", onMessage as EventListener);
        worker.removeEventListener("error", onError);
      };
      worker.addEventListener("message", onMessage as EventListener);
      worker.addEventListener("error", onError);
      worker.postMessage(request, [buffer]);
    });
    if (!response.ok) throw new Error(response.error);
    response.analysis.timingsMs.worker_start = workerStartMs;
    response.analysis.timingsMs.round_trip = performance.now() - tStart;
    return response.analysis;
  } finally {
    worker.terminate();
  }
}
