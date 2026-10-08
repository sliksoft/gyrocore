import type { DecodeRequest, DecodeResponse, NormalizedDecodedLog } from "./types";

export type DecodeBlackboxOptions = {
  logIndex?: number | null;
  includeSeries?: boolean;
  /** Injected worker factory for tests. */
  createWorker?: () => Worker;
};

/**
 * Decode a browser File in a Web Worker (no upload, no Tauri, no absolute paths).
 */
export async function decodeBlackboxFile(
  file: File,
  options: DecodeBlackboxOptions = {},
): Promise<{ result: NormalizedDecodedLog; timingsMs: Record<string, number> }> {
  const buffer = await file.arrayBuffer();
  return decodeBlackboxBuffer(buffer, file.name, options);
}

export async function decodeBlackboxBuffer(
  buffer: ArrayBuffer,
  filename: string,
  options: DecodeBlackboxOptions = {},
): Promise<{ result: NormalizedDecodedLog; timingsMs: Record<string, number> }> {
  const worker =
    options.createWorker?.() ??
    new Worker(new URL("./blackboxDecode.worker.ts", import.meta.url), { type: "module" });

  const request: DecodeRequest = {
    buffer,
    filename,
    logIndex: options.logIndex ?? null,
    includeSeries: options.includeSeries !== false,
  };

  try {
    const response = await new Promise<DecodeResponse>((resolve, reject) => {
      const onMessage = (ev: MessageEvent<DecodeResponse>) => {
        cleanup();
        resolve(ev.data);
      };
      const onError = (err: ErrorEvent) => {
        cleanup();
        reject(new Error(err.message || "decode_worker_error"));
      };
      const cleanup = () => {
        worker.removeEventListener("message", onMessage as EventListener);
        worker.removeEventListener("error", onError);
      };
      worker.addEventListener("message", onMessage as EventListener);
      worker.addEventListener("error", onError);
      // Transfer ownership of the ArrayBuffer to avoid a giant structured clone.
      worker.postMessage(request, [buffer]);
    });

    if (!response.ok) {
      throw new Error(response.error);
    }
    return { result: response.result, timingsMs: response.timingsMs };
  } finally {
    worker.terminate();
  }
}
