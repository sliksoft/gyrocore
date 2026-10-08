import type { SessionAnalyzeResult, SessionOpenResult, SessionRequest, SessionResponse } from "./types";

type Pending = { resolve: (r: SessionResponse) => void; reject: (e: Error) => void };
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown ? Omit<T, K> : never;

/**
 * One local browser analysis session per selected BBL, backed by a dedicated Web
 * Worker that decodes the file once and keeps it in worker memory. No upload,
 * no Tauri, no service-worker caching: the bytes live only in that worker and are
 * released on `dispose()`.
 */
export class BrowserSession {
  private readonly worker: Worker;
  private readonly pending = new Map<number, Pending>();
  private seq = 0;
  private disposed = false;

  constructor(createWorker?: () => Worker) {
    this.worker =
      createWorker?.() ?? new Worker(new URL("./browserSession.worker.ts", import.meta.url), { type: "module" });
    this.worker.addEventListener("message", (ev: MessageEvent<SessionResponse>) => {
      const p = this.pending.get(ev.data.id);
      if (!p) return;
      this.pending.delete(ev.data.id);
      p.resolve(ev.data);
    });
    this.worker.addEventListener("error", (ev: ErrorEvent) => this.failAll(ev.message || "session_worker_error"));
  }

  /** Decode the BBL once (the ArrayBuffer is transferred, not copied). */
  async open(file: File): Promise<SessionOpenResult> {
    const buffer = await file.arrayBuffer();
    const r = await this.request({ type: "open", buffer, filename: file.name }, [buffer]);
    if (r.type !== "open") throw new Error("session_protocol_error");
    return { decoded: r.decoded, timingsMs: r.timingsMs, flightLogBuilds: r.flightLogBuilds };
  }

  /** Metadata + CHIRP for one embedded log, from the already-decoded file. */
  async analyze(logIndex: number): Promise<SessionAnalyzeResult> {
    const t0 = performance.now();
    const r = await this.request({ type: "analyze", logIndex });
    if (r.type !== "analyze") throw new Error("session_protocol_error");
    r.analysis.timingsMs.round_trip = performance.now() - t0;
    return { decoded: r.decoded, analysis: r.analysis, flightLogBuilds: r.flightLogBuilds };
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.worker.terminate();
    this.failAll("session_disposed");
  }

  get isDisposed() {
    return this.disposed;
  }

  private request(
    req: DistributiveOmit<SessionRequest, "id">,
    transfer: Transferable[] = [],
  ): Promise<Extract<SessionResponse, { ok: true }>> {
    if (this.disposed) return Promise.reject(new Error("session_disposed"));
    const id = ++this.seq;
    return new Promise((resolve, reject) => {
      this.pending.set(id, {
        resolve: (r) => (r.ok ? resolve(r) : reject(new Error(r.error))),
        reject,
      });
      this.worker.postMessage({ ...req, id } as SessionRequest, transfer);
    });
  }

  private failAll(message: string) {
    for (const p of this.pending.values()) p.reject(new Error(message));
    this.pending.clear();
  }
}
