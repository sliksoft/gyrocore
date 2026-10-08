import { existsSync, readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { FlightLog } from "@bf-blackbox/flightlog.js";
import { normalizeFromFlightLog } from "./normalizeFromFlightLog";

const LOCAL_BBL =
  process.env.GYROCORE_BBL_FIXTURE ||
  "/home/sliksoft/GyroCore/BTFL_BLACKBOX_LOG_AIR65_C_20261005_224215_BETAFPVG473.BBL";

describe("FlightLog browser decoder smoke", () => {
  it("rejects malformed bytes without network", () => {
    const fetchSpy = globalThis.fetch;
    // @ts-expect-error force-detect accidental fetch
    globalThis.fetch = () => {
      throw new Error("unexpected_network");
    };
    try {
      expect(() => new FlightLog(new Uint8Array([0, 1, 2, 3, 4]))).not.toThrow();
      const log = new FlightLog(new Uint8Array([0, 1, 2, 3, 4]));
      expect(log.getLogCount()).toBe(0);
      expect(() =>
        normalizeFromFlightLog(log, { filename: "bad.bbl", sizeBytes: 5, includeSeries: false }),
      ).toThrow(/no_embedded_logs/);
    } finally {
      globalThis.fetch = fetchSpy;
    }
  });

  it("indexes multi-log user fixture when present", () => {
    if (!existsSync(LOCAL_BBL)) return;
    const bytes = new Uint8Array(readFileSync(LOCAL_BBL));
    const t0 = performance.now();
    const log = new FlightLog(bytes);
    const indexMs = performance.now() - t0;
    expect(log.getLogCount()).toBeGreaterThanOrEqual(2);
    const t1 = performance.now();
    const out = normalizeFromFlightLog(log, {
      filename: "fixture.bbl",
      sizeBytes: bytes.byteLength,
      includeSeries: false,
    });
    const normalizeMs = performance.now() - t1;
    expect(out.embedded.logCount).toBe(log.getLogCount());
    expect(out.embedded.recommendedIndex).toBeGreaterThanOrEqual(0);
    console.log("PERF_MULTILOG_MS", { indexMs, normalizeMs, sizeBytes: bytes.byteLength, logs: out.embedded.logCount });
  });
});
