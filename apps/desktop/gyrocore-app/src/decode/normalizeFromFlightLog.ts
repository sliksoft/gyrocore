import type { DecodedFlightSummary, NormalizedDecodedLog } from "./types";

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

const SERIES_CANDIDATES = [
  "gyroADC[0]",
  "gyroADC[1]",
  "gyroADC[2]",
  "setpoint[0]",
  "setpoint[1]",
  "setpoint[2]",
  "motor[0]",
  "motor[1]",
  "motor[2]",
  "motor[3]",
  "rcCommand[0]",
  "rcCommand[1]",
  "rcCommand[2]",
  "rcCommand[3]",
  "axisP[0]",
  "axisP[1]",
  "axisP[2]",
  "axisI[0]",
  "axisI[1]",
  "axisI[2]",
  "axisD[0]",
  "axisD[1]",
  "debug[0]",
  "debug[1]",
  "debug[2]",
  "debug[3]",
] as const;

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

function extractSeries(
  log: FlightLogLike,
  fieldNames: string[],
): { timeUs: Float64Array; series: Record<string, Float64Array> } {
  const min = log.getMinTime();
  const max = log.getMaxTime();
  const chunks = log.getChunksInTimeRange(min, max);
  const frames: number[][] = [];
  for (const c of chunks) {
    for (const f of c.frames) frames.push(f);
  }
  const n = frames.length;
  const timeIdx = log.getMainFieldIndexByName("time");
  const timeUs = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    timeUs[i] = timeIdx !== undefined ? Number(frames[i]![timeIdx]) : i;
  }

  const series: Record<string, Float64Array> = {};
  for (const name of SERIES_CANDIDATES) {
    if (!fieldNames.includes(name)) continue;
    const idx = log.getMainFieldIndexByName(name);
    if (idx === undefined) continue;
    const arr = new Float64Array(n);
    for (let i = 0; i < n; i++) arr[i] = Number(frames[i]![idx]);
    series[name] = arr;
  }
  return { timeUs, series };
}

export function normalizeFromFlightLog(
  log: FlightLogLike,
  opts: {
    filename: string;
    sizeBytes: number;
    selectedIndex?: number | null;
    includeSeries?: boolean;
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
  const { timeUs, series } = opts.includeSeries
    ? extractSeries(log, fieldNames)
    : { timeUs: new Float64Array(0), series: {} };

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
      firmwareType: typeof sys.firmwareType === "string" ? sys.firmwareType : undefined,
      firmwareVersion: typeof sys.firmwareVersion === "string" ? sys.firmwareVersion : undefined,
      craftName: typeof sys.craftName === "string" ? sys.craftName : undefined,
      sampleRateHzEstimate,
      fieldNames,
    },
    timeUs,
    series,
  };
}
