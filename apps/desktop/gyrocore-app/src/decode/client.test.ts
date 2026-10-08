import { describe, expect, it, vi } from "vitest";
import { decodeBlackboxBuffer, decodeBlackboxFile } from "./client";
import type { DecodeRequest, DecodeResponse, NormalizedDecodedLog } from "./types";

function fakeDecoded(filename: string): NormalizedDecodedLog {
  return {
    schemaVersion: 1,
    source: {
      filename,
      sizeBytes: 3,
      decoder: "betaflight-flightlog-js",
      licenseNote: "GPL-3.0 (vendored Betaflight blackbox-log-viewer)",
    },
    embedded: {
      logCount: 2,
      selectedIndex: 1,
      recommendedIndex: 1,
      flights: [
        {
          index: 0,
          label: "log 0",
          startTimeUs: 0,
          endTimeUs: 100,
          durationUs: 100,
          sampleCount: 0,
        },
        {
          index: 1,
          label: "log 1",
          startTimeUs: 0,
          endTimeUs: 500,
          durationUs: 500,
          sampleCount: 0,
        },
      ],
    },
    metadata: { fieldNames: ["time", "gyroADC[0]"] },
    timeUs: new Float64Array(0),
    series: {},
  };
}

function mockWorker(handler: (req: DecodeRequest) => DecodeResponse) {
  return () => {
    const listeners = new Map<string, Set<EventListener>>();
    const worker = {
      addEventListener(type: string, fn: EventListener) {
        if (!listeners.has(type)) listeners.set(type, new Set());
        listeners.get(type)!.add(fn);
      },
      removeEventListener(type: string, fn: EventListener) {
        listeners.get(type)?.delete(fn);
      },
      postMessage(data: DecodeRequest, _transfer?: Transferable[]) {
        const response = handler(data);
        queueMicrotask(() => {
          for (const fn of listeners.get("message") ?? []) {
            fn({ data: response } as MessageEvent);
          }
        });
      },
      terminate: vi.fn(),
    };
    return worker as unknown as Worker;
  };
}

describe("decodeBlackbox client", () => {
  it("transfers buffer to worker and returns normalized multi-log result", async () => {
    const createWorker = mockWorker((req) => {
      expect(req.buffer.byteLength).toBe(3);
      expect(req.filename).toBe("multi.bbl");
      expect(req.includeSeries).toBe(false);
      return { ok: true, result: fakeDecoded(req.filename), timingsMs: { total: 2 } };
    });

    const out = await decodeBlackboxBuffer(new Uint8Array([1, 2, 3]).buffer, "multi.bbl", {
      createWorker,
      includeSeries: false,
    });
    expect(out.result.embedded.logCount).toBe(2);
    expect(out.result.embedded.recommendedIndex).toBe(1);
    expect(out.timingsMs.total).toBe(2);
  });

  it("surfaces worker decode errors for malformed input", async () => {
    const createWorker = mockWorker(() => ({
      ok: false,
      error: "no_embedded_logs",
      timingsMs: { total: 1 },
    }));
    await expect(
      decodeBlackboxBuffer(new ArrayBuffer(4), "bad.bbl", { createWorker }),
    ).rejects.toThrow(/no_embedded_logs/);
  });

  it("reads File without network", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const createWorker = mockWorker((req) => ({
      ok: true,
      result: fakeDecoded(req.filename),
      timingsMs: { total: 1 },
    }));
    const file = new File([new Uint8Array([9, 9])], "f.bbl", { type: "application/octet-stream" });
    const out = await decodeBlackboxFile(file, { createWorker, includeSeries: false });
    expect(out.result.source.filename).toBe("f.bbl");
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
