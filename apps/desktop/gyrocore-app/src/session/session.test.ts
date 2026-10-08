// @vitest-environment node
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { describe, expect, it, vi } from "vitest";
import { toPlain } from "@/chirp/parityCompare";
import { runChirpOnBytes } from "@/chirp/runChirp";
import { BrowserSession } from "./client";
import { createSessionCore } from "./sessionCore";
import type { SessionRequest, SessionResponse } from "./types";

const WU7 = new URL("../../../../../tests/fixtures/chirp/wu7/bbl/", import.meta.url);
const fixture = (name: string) => new Uint8Array(gunzipSync(readFileSync(new URL(`${name}.bbl.gz`, WU7))));
const PARTS = ["clean_single_axis", "three_axis_sequence", "poor_coherence"] as const;
const multi = () => {
  const parts = PARTS.map(fixture);
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) out.set(p, (o += p.length) - p.length);
  return out;
};
const bufferOf = (u: Uint8Array) => u.buffer.slice(u.byteOffset, u.byteOffset + u.byteLength) as ArrayBuffer;

function ok<T extends SessionResponse>(r: T) {
  if (!r.ok) throw new Error(r.error);
  return r;
}

describe("browser session: decode once, analyse any embedded log", () => {
  it("reused FlightLog gives the same CHIRP result as a fresh decode, in any log order (no cross-log leakage)", () => {
    const bytes = multi();
    const core = createSessionCore();
    const opened = ok(core.handle({ id: 1, type: "open", buffer: bufferOf(bytes), filename: "multi.bbl" }).response);
    if (opened.type !== "open") throw new Error("protocol");
    expect(opened.decoded.embedded.logCount).toBe(3);

    let id = 2;
    for (const i of [2, 0, 1, 1, 0]) {
      const r = ok(core.handle({ id: id++, type: "analyze", logIndex: i }).response);
      if (r.type !== "analyze") throw new Error("protocol");
      const fresh = runChirpOnBytes(bytes, { filename: "multi.bbl", logIndex: i });
      expect(toPlain(r.analysis.result)).toEqual(toPlain(fresh.result));
      expect(r.analysis.rejection).toEqual(fresh.rejection);
      expect(r.analysis.source).toEqual(fresh.source);
      // Workspace metadata is for the selected log, never the recommended one.
      expect(r.decoded.embedded.selectedIndex).toBe(i);
      expect(r.analysis.source.logIndex).toBe(i);
      expect(r.flightLogBuilds).toBe(1);
    }
    expect(core.flightLogBuilds()).toBe(1);
  });

  it("each embedded log keeps its own verdict (1 axis / 3 axes / rejected)", () => {
    const core = createSessionCore();
    core.handle({ id: 1, type: "open", buffer: bufferOf(multi()), filename: "multi.bbl" });
    const axes = [0, 1, 2].map((i) => {
      const r = ok(core.handle({ id: 10 + i, type: "analyze", logIndex: i }).response);
      if (r.type !== "analyze") throw new Error("protocol");
      return [Object.keys(r.analysis.result.axes).length, r.analysis.rejection?.code ?? null];
    });
    expect(axes).toEqual([
      [1, null],
      [3, null],
      [1, "chirp_unusable"],
    ]);
  });

  it("rejects analyse before open and out-of-range log indices", () => {
    const core = createSessionCore();
    expect(core.handle({ id: 1, type: "analyze", logIndex: 0 }).response).toEqual({ id: 1, ok: false, error: "session_not_open" });
    core.handle({ id: 2, type: "open", buffer: bufferOf(fixture("clean_single_axis")), filename: "x.bbl" });
    for (const bad of [-1, 1, 0.5]) {
      expect(core.handle({ id: 3, type: "analyze", logIndex: bad }).response).toMatchObject({ ok: false, error: `invalid_log_index:${bad}` });
    }
  });

  it("transfers the CHIRP series buffers instead of cloning them", () => {
    const core = createSessionCore();
    core.handle({ id: 1, type: "open", buffer: bufferOf(fixture("clean_single_axis")), filename: "x.bbl" });
    expect(core.handle({ id: 2, type: "analyze", logIndex: 0 }).transfer.length).toBeGreaterThanOrEqual(6);
  });
});

/** In-process stand-in for the session Web Worker (same core, async messages). */
function fakeWorker(opts: { crash?: boolean } = {}) {
  const core = createSessionCore();
  const listeners: Record<string, Array<(ev: unknown) => void>> = { message: [], error: [] };
  const posted: SessionRequest[] = [];
  const w = {
    posted,
    terminated: false,
    addEventListener: (t: string, fn: (ev: unknown) => void) => listeners[t]!.push(fn),
    removeEventListener: vi.fn(),
    terminate() {
      this.terminated = true;
    },
    postMessage(req: SessionRequest) {
      posted.push(req);
      queueMicrotask(() => {
        if (opts.crash) return listeners.error!.forEach((fn) => fn({ message: "boom" }));
        const { response } = core.handle(req);
        listeners.message!.forEach((fn) => fn({ data: response }));
      });
    },
  };
  return w;
}

describe("BrowserSession client", () => {
  const file = (bytes: Uint8Array, name: string) => new File([bufferOf(bytes)], name);

  it("open + analyze over one worker: one decode, selected log, CHIRP result, no network", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const w = fakeWorker();
    const s = new BrowserSession(() => w as unknown as Worker);
    const opened = await s.open(file(multi(), "multi.bbl"));
    expect(opened.decoded.embedded.logCount).toBe(3);
    const r = await s.analyze(1);
    expect(r.analysis.source).toMatchObject({ logIndex: 1, logCount: 3 });
    expect(r.decoded.embedded.selectedIndex).toBe(1);
    expect(r.flightLogBuilds).toBe(1);
    expect(w.posted.map((p) => p.type)).toEqual(["open", "analyze"]);
    expect(fetchSpy).not.toHaveBeenCalled();
    s.dispose();
    expect(w.terminated).toBe(true);
    fetchSpy.mockRestore();
  });

  it("worker errors and disposal reject pending requests", async () => {
    const crashing = new BrowserSession(() => fakeWorker({ crash: true }) as unknown as Worker);
    await expect(crashing.open(file(fixture("clean_single_axis"), "x.bbl"))).rejects.toThrow("boom");

    const s = new BrowserSession(() => fakeWorker() as unknown as Worker);
    const pending = s.open(file(fixture("clean_single_axis"), "x.bbl"));
    s.dispose();
    await expect(pending).rejects.toThrow("session_disposed");
    await expect(s.analyze(0)).rejects.toThrow("session_disposed");
  });

  it("analysis errors surface as rejections", async () => {
    const s = new BrowserSession(() => fakeWorker() as unknown as Worker);
    await s.open(file(fixture("clean_single_axis"), "x.bbl"));
    await expect(s.analyze(4)).rejects.toThrow("invalid_log_index:4");
  });
});
