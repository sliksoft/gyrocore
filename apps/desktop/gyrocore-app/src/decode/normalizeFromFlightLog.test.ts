import { describe, expect, it } from "vitest";
import { normalizeFromFlightLog, type FlightLogLike } from "./normalizeFromFlightLog";

function fakeLog(count: number): FlightLogLike {
  let open = 0;
  return {
    getLogCount: () => count,
    getLogError: () => false,
    openLog: (i) => {
      open = i;
      return true;
    },
    getMainFieldNames: () => ["time", "gyroADC[0]", "setpoint[0]"],
    getMainFieldIndexByName: (n) => ({ time: 0, "gyroADC[0]": 1, "setpoint[0]": 2 })[n],
    getMinTime: () => 1000 + open * 10,
    getMaxTime: () => 2000 + open * 10,
    getSysConfig: () => ({ firmwareType: "Betaflight", firmwareVersion: "4.5.0", craftName: "test" }),
    getChunksInTimeRange: () => [
      {
        frames: [
          [0, 1, 2],
          [1, 2, 3],
          [2, 3, 4],
        ],
      },
    ],
  };
}

describe("normalizeFromFlightLog", () => {
  it("builds multi-log summaries and recommends longest duration", () => {
    const out = normalizeFromFlightLog(fakeLog(2), {
      filename: "x.bbl",
      sizeBytes: 10,
      includeSeries: true,
    });
    expect(out.embedded.logCount).toBe(2);
    expect(out.embedded.flights).toHaveLength(2);
    expect(out.metadata.fieldNames).toContain("gyroADC[0]");
    expect(out.series["gyroADC[0]"]?.length).toBe(3);
    expect(out.source.decoder).toBe("betaflight-flightlog-js");
  });

  it("rejects empty logs", () => {
    const empty = fakeLog(0);
    expect(() =>
      normalizeFromFlightLog(empty, { filename: "x.bbl", sizeBytes: 1, includeSeries: false }),
    ).toThrow(/no_embedded_logs/);
  });
});

