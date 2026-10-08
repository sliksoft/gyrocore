import {
  FIRMWARE_TYPE_BASEFLIGHT,
  FIRMWARE_TYPE_BETAFLIGHT,
  FIRMWARE_TYPE_CLEANFLIGHT,
  FIRMWARE_TYPE_INAV,
} from "@bf-blackbox/flightlog_fielddefs.js";
import type {
  DecodedFlightSummary,
  MetadataKey,
  MetadataPresence,
  NormalizedDecodedLog,
} from "./types";

/** Minimal FlightLog surface used by the adapter (constructor lives in BF tree). */
export type FlightLogLike = {
  getLogCount: () => number;
  getLogError: (index: number) => unknown;
  openLog: (index: number) => boolean;
  getMainFieldNames: () => string[];
  getMainFieldIndexByName: (name: string) => number | undefined;
  getMinTime: (index?: number) => number;
  getMaxTime: (index?: number) => number;
  getSysConfig: () => Record<string, unknown>;
  getChunksInTimeRange: (start: number, end: number) => Array<{ frames: number[][] }>;
};

/**
 * Main-frame channels carried in the normalized contract: every logged axis/motor/debug
 * slot for gyro, setpoint, motors, RC, PID P/I/D/F and debug.
 */
const SERIES_FIELD_PATTERN = /^(gyroADC|setpoint|motor|rcCommand|axisP|axisI|axisD|axisF|debug)\[\d+\]$/;

const FIRMWARE_TYPE_NAMES: Record<number, string> = {
  [FIRMWARE_TYPE_BASEFLIGHT]: "Baseflight",
  [FIRMWARE_TYPE_CLEANFLIGHT]: "Cleanflight",
  [FIRMWARE_TYPE_BETAFLIGHT]: "Betaflight",
  [FIRMWARE_TYPE_INAV]: "INAV",
};

/** Betaflight writes this when the RTC was never set; it is not a real start time. */
const UNSET_LOG_START_DATETIME = /^0000-01-01T/;

function recommendIndex(flights: DecodedFlightSummary[]): number {
  if (!flights.length) return 0;
  let best = flights[0]!;
  for (const f of flights) {
    const dur = f.durationUs ?? 0;
    const bestDur = best.durationUs ?? 0;
    if (dur > bestDur || (dur === bestDur && f.sampleCount > best.sampleCount)) {
      best = f;
    }
  }
  return best.index;
}

function countFrames(log: FlightLogLike): number {
  const min = log.getMinTime();
  const max = log.getMaxTime();
  if (!Number.isFinite(min) || !Number.isFinite(max) || max < min) return 0;
  const chunks = log.getChunksInTimeRange(min, max);
  let n = 0;
  for (const c of chunks) n += c.frames.length;
  return n;
}

export function selectSeriesFields(fieldNames: string[]): string[] {
  return fieldNames.filter((name) => SERIES_FIELD_PATTERN.test(name));
}

function extractSeries(
  log: FlightLogLike,
  fieldNames: string[],
): { timeUs: Float64Array; loopIteration: Float64Array; series: Record<string, Float64Array> } {
  const min = log.getMinTime();
  const max = log.getMaxTime();
  const chunks = log.getChunksInTimeRange(min, max);
  const frames: number[][] = [];
  for (const c of chunks) {
    for (const f of c.frames) frames.push(f);
  }
  const n = frames.length;
  const timeIdx = log.getMainFieldIndexByName("time");
  const iterIdx = log.getMainFieldIndexByName("loopIteration");
  const timeUs = new Float64Array(n);
  const loopIteration = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    timeUs[i] = timeIdx !== undefined ? Number(frames[i]![timeIdx]) : i;
    loopIteration[i] = iterIdx !== undefined ? Number(frames[i]![iterIdx]) : i;
  }

  const series: Record<string, Float64Array> = {};
  for (const name of selectSeriesFields(fieldNames)) {
    const idx = log.getMainFieldIndexByName(name);
    if (idx === undefined) continue;
    const arr = new Float64Array(n);
    for (let i = 0; i < n; i++) arr[i] = Number(frames[i]![idx]);
    series[name] = arr;
  }
  return { timeUs, loopIteration, series };
}

const str = (v: unknown): string | undefined =>
  typeof v === "string" && v.trim().length > 0 ? v : undefined;
const num = (v: unknown): number | undefined => {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "" && Number.isFinite(Number(v))) return Number(v);
  return undefined;
};

/**
 * Raw header names that carry each metadata key. FlightLog renames some headers
 * (e.g. `motor_pwm_protocol` → `fast_pwm_protocol`), so both spellings are listed.
 */
const METADATA_HEADERS: Record<MetadataKey, string[]> = {
  firmwareType: ["Firmware type", "Firmware revision"],
  firmwareVersion: ["Firmware revision"],
  firmwareRevision: ["Firmware revision"],
  firmwareDate: ["Firmware date"],
  boardInformation: ["Board information"],
  craftName: ["Craft name"],
  looptimeUs: ["looptime"],
  pidProcessDenom: ["pid_process_denom"],
  frameIntervalI: ["I interval"],
  frameIntervalPNum: ["P interval"],
  frameIntervalPDenom: ["P interval"],
  gyroScaleRaw: ["gyro_scale", "gyro.scale"],
  motorProtocol: ["motor_pwm_protocol", "fast_pwm_protocol"],
  debugMode: ["debug_mode"],
  dataVersion: ["Data version"],
  logStartDatetime: ["Log start datetime"],
};

function firstHeader(raw: Record<string, string>, names: string[]): string | undefined {
  for (const n of names) {
    const v = raw[n];
    if (v !== undefined && v.trim().length > 0) return v.trim();
  }
  return undefined;
}

function buildMetadata(
  sys: Record<string, unknown>,
  rawHeaders: Record<string, string> | undefined,
): Omit<NormalizedDecodedLog["metadata"], "fieldNames" | "sampleRateHzEstimate"> {
  const raw = rawHeaders ?? {};
  const fwTypeNum = num(sys.firmwareType);
  const rawLogStart = str(sys["Log start datetime"]);
  const values: Record<MetadataKey, string | number | undefined> = {
    firmwareType: fwTypeNum !== undefined ? FIRMWARE_TYPE_NAMES[fwTypeNum] : str(sys.firmwareType),
    firmwareVersion: str(sys.firmwareVersion),
    firmwareRevision: str(sys["Firmware revision"]),
    firmwareDate: str(sys["Firmware date"]),
    boardInformation: str(sys["Board information"]),
    craftName: str(sys["Craft name"]) ?? str(sys.craftName),
    looptimeUs: num(sys.looptime),
    pidProcessDenom: num(sys.pid_process_denom),
    frameIntervalI: num(sys.frameIntervalI),
    frameIntervalPNum: num(sys.frameIntervalPNum),
    frameIntervalPDenom: num(sys.frameIntervalPDenom),
    // FlightLog converts gyro_scale to rad/µs and does not keep Data version; take both from raw headers.
    gyroScaleRaw: firstHeader(raw, METADATA_HEADERS.gyroScaleRaw),
    motorProtocol: num(sys.fast_pwm_protocol) ?? num(sys.motor_pwm_protocol),
    debugMode: num(sys.debug_mode),
    dataVersion: num(firstHeader(raw, METADATA_HEADERS.dataVersion)),
    logStartDatetime:
      rawLogStart && !UNSET_LOG_START_DATETIME.test(rawLogStart) ? rawLogStart : undefined,
  };

  const presence: Partial<Record<MetadataKey, MetadataPresence>> = {};
  if (rawHeaders) {
    for (const key of Object.keys(METADATA_HEADERS) as MetadataKey[]) {
      const logged = firstHeader(rawHeaders, METADATA_HEADERS[key]);
      if (logged === undefined) presence[key] = "ABSENT_IN_LOG";
      else if (key === "logStartDatetime" && UNSET_LOG_START_DATETIME.test(logged))
        presence[key] = "UNSET_SENTINEL";
      else presence[key] = values[key] !== undefined ? "PRESENT" : "PARSER_MISSING";
    }
  }

  return {
    firmwareType: values.firmwareType as string | undefined,
    firmwareVersion: values.firmwareVersion as string | undefined,
    firmwareRevision: values.firmwareRevision as string | undefined,
    firmwareDate: values.firmwareDate as string | undefined,
    boardInformation: values.boardInformation as string | undefined,
    craftName: values.craftName as string | undefined,
    looptimeUs: values.looptimeUs as number | undefined,
    pidProcessDenom: values.pidProcessDenom as number | undefined,
    frameIntervalI: values.frameIntervalI as number | undefined,
    frameIntervalPNum: values.frameIntervalPNum as number | undefined,
    frameIntervalPDenom: values.frameIntervalPDenom as number | undefined,
    gyroScaleRaw: values.gyroScaleRaw as string | undefined,
    motorProtocol: values.motorProtocol as number | undefined,
    debugMode: values.debugMode as number | undefined,
    dataVersion: values.dataVersion as number | undefined,
    logStartDatetime: values.logStartDatetime as string | undefined,
    presence,
  };
}

export function normalizeFromFlightLog(
  log: FlightLogLike,
  opts: {
    filename: string;
    sizeBytes: number;
    selectedIndex?: number | null;
    includeSeries?: boolean;
    /**
     * Resolves raw `H` headers for an embedded log (see `readLogHeaders`); enables
     * ABSENT_IN_LOG vs PARSER_MISSING metadata provenance.
     */
    rawHeadersForLog?: (logIndex: number) => Record<string, string>;
  },
): NormalizedDecodedLog {
  const logCount = log.getLogCount();
  if (logCount < 1) {
    throw new Error("no_embedded_logs");
  }
  const flights: DecodedFlightSummary[] = [];

  for (let i = 0; i < logCount; i++) {
    const err = log.getLogError(i);
    if (err) {
      flights.push({
        index: i,
        label: `log ${i}`,
        startTimeUs: null,
        endTimeUs: null,
        durationUs: null,
        sampleCount: 0,
        error: String(err),
      });
      continue;
    }
    const opened = log.openLog(i);
    if (!opened) {
      flights.push({
        index: i,
        label: `log ${i}`,
        startTimeUs: null,
        endTimeUs: null,
        durationUs: null,
        sampleCount: 0,
        error: "open_failed",
      });
      continue;
    }
    const start = log.getMinTime();
    const end = log.getMaxTime();
    // Full frame enumeration is expensive — only when series extraction is requested.
    const sampleCount = opts.includeSeries ? countFrames(log) : 0;
    flights.push({
      index: i,
      label: `log ${i}`,
      startTimeUs: Number.isFinite(start) ? start : null,
      endTimeUs: Number.isFinite(end) ? end : null,
      durationUs: Number.isFinite(start) && Number.isFinite(end) ? end - start : null,
      sampleCount,
    });
  }

  const recommendedIndex = recommendIndex(flights);
  const selectedIndex =
    opts.selectedIndex != null && opts.selectedIndex >= 0 && opts.selectedIndex < logCount
      ? opts.selectedIndex
      : recommendedIndex;

  if (!log.openLog(selectedIndex)) {
    throw new Error(`failed_to_open_log_index:${selectedIndex}`);
  }

  const fieldNames = log.getMainFieldNames().slice();
  const sys = log.getSysConfig() || {};
  const { timeUs, loopIteration, series } = opts.includeSeries
    ? extractSeries(log, fieldNames)
    : { timeUs: new Float64Array(0), loopIteration: new Float64Array(0), series: {} };

  let sampleRateHzEstimate: number | null = null;
  if (timeUs.length >= 2) {
    const dt = (timeUs[timeUs.length - 1]! - timeUs[0]!) / (timeUs.length - 1);
    if (dt > 0) sampleRateHzEstimate = 1_000_000 / dt;
  } else {
    const selected = flights[selectedIndex];
    if (selected?.durationUs && selected.sampleCount > 1) {
      sampleRateHzEstimate = (selected.sampleCount - 1) / (selected.durationUs / 1_000_000);
    }
  }

  return {
    schemaVersion: 1,
    source: {
      filename: opts.filename,
      sizeBytes: opts.sizeBytes,
      decoder: "betaflight-flightlog-js",
      licenseNote: "GPL-3.0 (vendored Betaflight blackbox-log-viewer)",
    },
    embedded: {
      logCount,
      selectedIndex,
      recommendedIndex,
      flights,
    },
    metadata: {
      ...buildMetadata(sys, opts.rawHeadersForLog?.(selectedIndex)),
      sampleRateHzEstimate,
      fieldNames,
    },
    timeUs,
    loopIteration,
    series,
  };
}
