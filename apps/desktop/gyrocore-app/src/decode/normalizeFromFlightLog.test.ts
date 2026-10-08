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

function sysLog(sys: Record<string, unknown>, fields: string[] = ["loopIteration", "time"]): FlightLogLike {
  return {
    ...fakeLog(1),
    getMainFieldNames: () => fields,
    getMainFieldIndexByName: (n) => (fields.indexOf(n) >= 0 ? fields.indexOf(n) : undefined),
    getSysConfig: () => sys,
    getChunksInTimeRange: () => [{ frames: [fields.map((_, i) => i * 10), fields.map((_, i) => i * 10 + 1)] }],
  };
}

const RAW_HEADERS = {
  "Firmware type": "Cleanflight",
  "Firmware revision": "Betaflight 2026.6.2 (3356aeb02) STM32G474",
  "Firmware date": "Oct  5 2026 17:13:57",
  "Board information": "BEFH BETAFPVG473",
  "Craft name": "AIR65 C",
  looptime: "125",
  pid_process_denom: "2",
  "I interval": "128",
  "P interval": "1/1",
  gyro_scale: "0x3f800000",
  motor_pwm_protocol: "6",
  debug_mode: "96",
  "Data version": "2",
  "Log start datetime": "0000-01-01T00:00:00.000+00:00",
};

const FLIGHTLOG_SYS = {
  firmwareType: 3,
  firmwareVersion: "2026.6.2",
  "Firmware revision": RAW_HEADERS["Firmware revision"],
  "Firmware date": RAW_HEADERS["Firmware date"],
  "Board information": RAW_HEADERS["Board information"],
  "Craft name": "AIR65 C",
  looptime: 125,
  pid_process_denom: 2,
  frameIntervalI: 128,
  frameIntervalPNum: 1,
  frameIntervalPDenom: 1,
  gyroScale: 1.7453292519943295e-8,
  fast_pwm_protocol: 6,
  debug_mode: 96,
  "Log start datetime": RAW_HEADERS["Log start datetime"],
};

describe("normalizeFromFlightLog metadata", () => {
  it("maps FlightLog sysConfig keys (numeric firmware type, renamed headers)", () => {
    const out = normalizeFromFlightLog(sysLog(FLIGHTLOG_SYS), {
      filename: "x.bbl",
      sizeBytes: 1,
      rawHeadersForLog: () => RAW_HEADERS,
    });
    expect(out.metadata).toMatchObject({
      firmwareType: "Betaflight",
      firmwareVersion: "2026.6.2",
      boardInformation: "BEFH BETAFPVG473",
      craftName: "AIR65 C",
      looptimeUs: 125,
      pidProcessDenom: 2,
      frameIntervalI: 128,
      gyroScaleRaw: "0x3f800000",
      motorProtocol: 6,
      debugMode: 96,
      dataVersion: 2,
    });
    expect(out.metadata.logStartDatetime).toBeUndefined();
    expect(out.metadata.presence.logStartDatetime).toBe("UNSET_SENTINEL");
    const notPresent = Object.entries(out.metadata.presence).filter(([, v]) => v !== "PRESENT");
    expect(notPresent).toEqual([["logStartDatetime", "UNSET_SENTINEL"]]);
  });

  it("flags PARSER_MISSING when a logged header is not surfaced", () => {
    const { "Board information": _drop, ...sys } = FLIGHTLOG_SYS;
    const out = normalizeFromFlightLog(sysLog(sys), {
      filename: "x.bbl",
      sizeBytes: 1,
      rawHeadersForLog: () => RAW_HEADERS,
    });
    expect(out.metadata.presence.boardInformation).toBe("PARSER_MISSING");
  });

  it("marks headers missing or empty in the log as ABSENT_IN_LOG", () => {
    const { gyro_scale: _g, "Craft name": _c, ...raw } = RAW_HEADERS;
    const out = normalizeFromFlightLog(sysLog({ ...FLIGHTLOG_SYS, "Craft name": "" }), {
      filename: "x.bbl",
      sizeBytes: 1,
      rawHeadersForLog: () => ({ ...raw, "Craft name": "" }),
    });
    expect(out.metadata.presence.gyroScaleRaw).toBe("ABSENT_IN_LOG");
    expect(out.metadata.presence.craftName).toBe("ABSENT_IN_LOG");
    expect(out.metadata.craftName).toBeUndefined();
  });

  it("carries all logged PID P/I/D/F, debug and motor slots plus loopIteration", () => {
    const fields = ["loopIteration", "time", "axisP[0]", "axisD[2]", "axisF[1]", "debug[7]", "motor[5]", "gyroUnfilt[0]", "heading[0]"];
    const out = normalizeFromFlightLog(sysLog(FLIGHTLOG_SYS, fields), {
      filename: "x.bbl",
      sizeBytes: 1,
      includeSeries: true,
    });
    expect(Object.keys(out.series).sort()).toEqual(["axisD[2]", "axisF[1]", "axisP[0]", "debug[7]", "motor[5]"]);
    expect([...out.loopIteration]).toEqual([0, 1]);
    expect([...out.timeUs]).toEqual([10, 11]);
    expect(out.metadata.presence).toEqual({});
  });
});

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

