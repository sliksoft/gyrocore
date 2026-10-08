/**
 * Compare browser FlightLog-normalized output against native blackbox_decode CSV.
 * Node/test-only — not bundled into the PWA shell.
 *
 * Parity is sample-exact: rows are joined on (loopIteration, time) and every
 * compared channel must match bit-for-bit. The only rows allowed to exist on one
 * side are the ones `predictNativeDesyncExclusions` predicts native drops (see
 * docs/browser-blackbox-decoder.md "Canonical sample inclusion").
 */

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { FlightLog, type FlightLogEventRecord } from "@bf-blackbox/flightlog.js";
import { readLogHeaders } from "./headers";
import { normalizeFromFlightLog, selectSeriesFields } from "./normalizeFromFlightLog";
import type { MetadataKey, NormalizedDecodedLog } from "./types";

/**
 * Event types whose payload the vendored blackbox-tools `parseEventFrame`
 * (third_party/betaflight/blackbox-tools/src/parser.c) consumes. Every other type
 * only has its type byte read, leaving the payload in the frame stream.
 */
export const NATIVE_PARSED_EVENT_TYPES: ReadonlySet<number> = new Set([0, 13, 14, 255]);
const EVENT_DISARM = 15;
const EVENT_FLIGHT_MODE = 30;
const FRAME_MARKERS: ReadonlySet<number> = new Set(Array.from("IPESGH", (c) => c.charCodeAt(0)));
const MARKER_E = 0x45;

/** First byte of an unsigned variable-byte encoding. */
function firstVbByte(v: number): number {
  return v > 0x7f ? (v & 0x7f) | 0x80 : v;
}

export type NativeDesyncWindow = {
  eventType: number;
  eventTimeUs: number;
  /** Inclusive start / exclusive end indices into the browser sample arrays. */
  startIndex: number;
  endIndex: number;
};

export type NativeExclusionPrediction = {
  /** 1 where native blackbox_decode is predicted to drop the browser sample. */
  excluded: Uint8Array;
  windows: NativeDesyncWindow[];
  /** Events whose native effect is not modelled; any mismatch near them must FAIL. */
  unmodeled: string[];
};

/**
 * Predict which valid frames native blackbox_decode drops.
 *
 * Native skips the payload of events it does not parse (FLIGHT_MODE, DISARM). When
 * the first leftover payload byte is not a frame marker, the parser sets
 * `mainStreamIsValid = false`; P-frames cannot resynchronise, so every main frame is
 * dropped until the next I-frame (loopIteration % I-interval === 0). A leftover 0x45
 * ('E') happens to re-enter event parsing and does not desync.
 */
export function predictNativeDesyncExclusions(
  loopIteration: ArrayLike<number>,
  timeUs: ArrayLike<number>,
  events: FlightLogEventRecord[],
  frameIntervalI: number,
): NativeExclusionPrediction {
  const n = timeUs.length;
  const excluded = new Uint8Array(n);
  const windows: NativeDesyncWindow[] = [];
  const unmodeled: string[] = [];
  const iInterval = frameIntervalI > 0 ? frameIntervalI : 1;
  const isIFrame = (i: number) => loopIteration[i]! % iInterval === 0;

  for (const ev of events) {
    if (NATIVE_PARSED_EVENT_TYPES.has(ev.event)) continue;
    let payload: number | undefined;
    if (ev.event === EVENT_FLIGHT_MODE) payload = Number(ev.data.newFlags);
    else if (ev.event === EVENT_DISARM) payload = Number(ev.data.reason);
    if (payload === undefined || !Number.isFinite(payload)) {
      unmodeled.push(`event_${ev.event}@${ev.time ?? "trailing"}`);
      continue;
    }
    const lead = firstVbByte(payload);
    if (FRAME_MARKERS.has(lead)) {
      const lastFlags = Number(ev.data.lastFlags);
      const harmlessE =
        lead === MARKER_E &&
        ev.event === EVENT_FLIGHT_MODE &&
        Number.isFinite(lastFlags) &&
        !NATIVE_PARSED_EVENT_TYPES.has(firstVbByte(lastFlags));
      if (!harmlessE) unmodeled.push(`event_${ev.event}_marker_0x${lead.toString(16)}@${ev.time}`);
      continue;
    }
    // Trailing event (after the last main frame): nothing left to drop.
    if (ev.time === undefined) continue;
    let start = 0;
    while (start < n && timeUs[start]! < ev.time) start++;
    if (start >= n || isIFrame(start)) continue;
    let end = start;
    while (end < n && !isIFrame(end)) end++;
    excluded.fill(1, start, end);
    windows.push({ eventType: ev.event, eventTimeUs: ev.time, startIndex: start, endIndex: end });
  }
  return { excluded, windows, unmodeled };
}

export type NativeCsv = { headers: string[]; columns: Map<string, Float64Array>; rowCount: number };

/** Parse native CSV into columns keyed by base field name (unit suffix stripped). */
export function parseNativeCsv(text: string): NativeCsv {
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (!lines.length) return { headers: [], columns: new Map(), rowCount: 0 };
  const headers = lines[0]!.split(",").map((h) => h.trim().replace(/\s*\(.*\)$/, ""));
  const rowCount = lines.length - 1;
  const cols = headers.map(() => new Float64Array(rowCount));
  for (let r = 0; r < rowCount; r++) {
    const cells = lines[r + 1]!.split(",");
    for (let c = 0; c < headers.length; c++) cols[c]![r] = Number(cells[c]);
  }
  return { headers, columns: new Map(headers.map((h, i) => [h, cols[i]!])), rowCount };
}

function nativeDecode(bblPath: string, logIndex0: number): { csv: string; stderr: string; ms: number } {
  const t0 = Date.now();
  // Raw units so every column is the decoded integer FlightLog also exposes.
  const proc = spawnSync(
    "blackbox_decode",
    [
      "--stdout",
      "--unit-vbat",
      "raw",
      "--unit-amperage",
      "raw",
      "--unit-flags",
      "raw",
      "--index",
      String(logIndex0 + 1),
      bblPath,
    ],
    { encoding: "utf8", maxBuffer: 512 * 1024 * 1024 },
  );
  const ms = Date.now() - t0;
  if (proc.error) throw proc.error;
  if (!proc.stdout) throw new Error(`native_decode_failed:${proc.stderr || proc.status}`);
  return { csv: proc.stdout, stderr: proc.stderr || "", ms };
}

export type ChannelStats = {
  field: string;
  status: "pass" | "fail" | "missing_browser" | "missing_native";
  alignedSamples: number;
  maxAbsError: number | null;
  meanAbsError: number | null;
  /** null when either side is constant (Pearson undefined). */
  correlation: number | null;
};

export type GroupReport = {
  group: ChannelGroup;
  status: "pass" | "fail" | "absent_in_log";
  channels: ChannelStats[];
};

export type ChannelGroup = "timestamps" | "gyro" | "setpoint" | "motors" | "pid" | "debug" | "rc";

const GROUP_PATTERNS: Record<ChannelGroup, RegExp> = {
  timestamps: /^time$/,
  gyro: /^gyroADC\[\d+\]$/,
  setpoint: /^setpoint\[\d+\]$/,
  motors: /^motor\[\d+\]$/,
  pid: /^axis[PIDF]\[\d+\]$/,
  debug: /^debug\[\d+\]$/,
  rc: /^rcCommand\[\d+\]$/,
};

export type SampleAlignment = {
  browserSamples: number;
  nativeSamples: number;
  aligned: number;
  browserOnly: number;
  nativeOnly: number;
  predictedNativeExclusions: number;
  /** browser-only set === predicted set, and nothing native-only. */
  exact: boolean;
  /** Pairs of indices (browser, native) for aligned samples. */
  browserIndex: Int32Array;
  nativeIndex: Int32Array;
};

/** Merge-join two (loopIteration, time)-ordered sample streams. */
export function alignSamples(
  browserIter: ArrayLike<number>,
  browserTime: ArrayLike<number>,
  nativeIter: ArrayLike<number>,
  nativeTime: ArrayLike<number>,
  predictedExcluded: Uint8Array,
): SampleAlignment {
  const bn = browserTime.length;
  const nn = nativeTime.length;
  const bIdx: number[] = [];
  const nIdx: number[] = [];
  let browserOnly = 0;
  let nativeOnly = 0;
  let unpredicted = 0;
  let i = 0;
  let j = 0;
  while (i < bn || j < nn) {
    const cmp =
      i >= bn
        ? 1
        : j >= nn
          ? -1
          : browserIter[i]! - nativeIter[j]! || browserTime[i]! - nativeTime[j]!;
    if (cmp === 0) {
      if (predictedExcluded[i]) unpredicted++;
      bIdx.push(i++);
      nIdx.push(j++);
    } else if (cmp < 0) {
      if (!predictedExcluded[i]) unpredicted++;
      browserOnly++;
      i++;
    } else {
      nativeOnly++;
      j++;
    }
  }
  let predicted = 0;
  for (let k = 0; k < bn; k++) predicted += predictedExcluded[k]!;
  return {
    browserSamples: bn,
    nativeSamples: nn,
    aligned: bIdx.length,
    browserOnly,
    nativeOnly,
    predictedNativeExclusions: predicted,
    exact: unpredicted === 0 && nativeOnly === 0,
    browserIndex: Int32Array.from(bIdx),
    nativeIndex: Int32Array.from(nIdx),
  };
}

export function compareChannel(
  field: string,
  browser: Float64Array | undefined,
  native: Float64Array | undefined,
  alignment: Pick<SampleAlignment, "browserIndex" | "nativeIndex">,
): ChannelStats {
  const empty = { alignedSamples: 0, maxAbsError: null, meanAbsError: null, correlation: null };
  if (!native) return { field, status: "missing_native", ...empty };
  if (!browser) return { field, status: "missing_browser", ...empty };
  const { browserIndex, nativeIndex } = alignment;
  const n = browserIndex.length;
  let maxAbs = 0;
  let sumAbs = 0;
  let nonComparable = 0;
  let sa = 0,
    sb = 0,
    saa = 0,
    sbb = 0,
    sab = 0;
  for (let k = 0; k < n; k++) {
    const x = browser[browserIndex[k]!]!;
    const y = native[nativeIndex[k]!]!;
    const d = Math.abs(x - y);
    if (Number.isNaN(d)) nonComparable++;
    else if (d > maxAbs) maxAbs = d;
    sumAbs += d;
    sa += x;
    sb += y;
    saa += x * x;
    sbb += y * y;
    sab += x * y;
  }
  const denom = Math.sqrt((n * saa - sa * sa) * (n * sbb - sb * sb));
  const correlation = n > 1 && denom > 0 ? (n * sab - sa * sb) / denom : null;
  return {
    field,
    status: n > 0 && maxAbs === 0 && nonComparable === 0 ? "pass" : "fail",
    alignedSamples: n,
    maxAbsError: nonComparable ? NaN : maxAbs,
    meanAbsError: n ? sumAbs / n : null,
    correlation,
  };
}

export type MetadataParity = {
  status: "pass" | "warn" | "fail";
  presence: NormalizedDecodedLog["metadata"]["presence"];
  parserMissing: MetadataKey[];
  absentInLog: MetadataKey[];
  nativeStartMatches: boolean | null;
};

export type ParityReport = {
  ok: boolean;
  logIndex: number;
  embeddedLogs: { browser: number; native: number | null; status: "pass" | "fail" };
  /** Informational: decoder-computed columns legitimately differ (e.g. native energyCumulative). */
  fields: { browserOnly: string[]; nativeOnly: string[] };
  samples: Omit<SampleAlignment, "browserIndex" | "nativeIndex"> & {
    windows: NativeDesyncWindow[];
    unmodeledEvents: string[];
  };
  groups: GroupReport[];
  metadata: MetadataParity;
  timingsMs: { native: number; browser: number };
};

function eventsForOpenLog(fl: FlightLog): FlightLogEventRecord[] {
  const chunks = fl.getChunksInTimeRange(fl.getMinTime(), fl.getMaxTime());
  const out: FlightLogEventRecord[] = [];
  for (const c of chunks) for (const e of c.events ?? []) out.push(e);
  return out;
}

function parseNativeClock(s: string): number {
  // "mm:ss.mmm" → µs
  const m = /^(\d+):(\d+)\.(\d+)$/.exec(s);
  if (!m) return NaN;
  return (Number(m[1]) * 60 + Number(m[2])) * 1e6 + Number(m[3]!.padEnd(3, "0")) * 1e3;
}

export function runBrowserNativeParity(opts: { bblPath: string; logIndex?: number }): ParityReport {
  const logIndex = opts.logIndex ?? 0;
  const bytes = new Uint8Array(readFileSync(opts.bblPath));

  const tB0 = Date.now();
  const fl = new FlightLog(bytes);
  const browser = normalizeFromFlightLog(fl, {
    filename: opts.bblPath.split(/[/\\]/).pop() || "flight.bbl",
    sizeBytes: bytes.byteLength,
    selectedIndex: logIndex,
    includeSeries: true,
    rawHeadersForLog: (i) => readLogHeaders(bytes, i),
  });
  const browserMs = Date.now() - tB0;
  if (browser.embedded.selectedIndex !== logIndex) {
    throw new Error(`browser_selected_${browser.embedded.selectedIndex}_expected_${logIndex}`);
  }
  // normalizeFromFlightLog leaves the selected log open.
  const events = eventsForOpenLog(fl);

  const native = nativeDecode(opts.bblPath, logIndex);
  const csv = parseNativeCsv(native.csv);

  const m = /Log\s+(\d+)\s+of\s+(\d+),\s*start\s+([\d:.]+)/i.exec(native.stderr);
  const nativeLogCount = m ? Number(m[2]) : null;
  const embeddedLogs = {
    browser: browser.embedded.logCount,
    native: nativeLogCount,
    status: nativeLogCount === browser.embedded.logCount ? ("pass" as const) : ("fail" as const),
  };

  const browserFields = new Set(browser.metadata.fieldNames);
  const nativeFields = new Set(csv.headers);
  const fields = {
    browserOnly: [...browserFields].filter((f) => !nativeFields.has(f)),
    nativeOnly: [...nativeFields].filter((f) => !browserFields.has(f)),
  };

  const prediction = predictNativeDesyncExclusions(
    browser.loopIteration,
    browser.timeUs,
    events,
    browser.metadata.frameIntervalI ?? 1,
  );
  const nIter = csv.columns.get("loopIteration") ?? new Float64Array(0);
  const nTime = csv.columns.get("time") ?? new Float64Array(0);
  const alignment = alignSamples(browser.loopIteration, browser.timeUs, nIter, nTime, prediction.excluded);

  const groups: GroupReport[] = (Object.keys(GROUP_PATTERNS) as ChannelGroup[]).map((group) => {
    const re = GROUP_PATTERNS[group];
    const names = new Set<string>([
      ...csv.headers.filter((h) => re.test(h)),
      ...selectSeriesFields(browser.metadata.fieldNames).filter((f) => re.test(f)),
    ]);
    if (group === "timestamps") names.add("time");
    const channels = [...names].map((name) =>
      compareChannel(
        name,
        name === "time" ? browser.timeUs : browser.series[name],
        csv.columns.get(name),
        alignment,
      ),
    );
    const status: GroupReport["status"] = !channels.length
      ? "absent_in_log"
      : channels.every((c) => c.status === "pass")
        ? "pass"
        : "fail";
    return { group, status, channels };
  });

  const presence = browser.metadata.presence;
  const keys = Object.keys(presence) as MetadataKey[];
  const parserMissing = keys.filter((k) => presence[k] === "PARSER_MISSING");
  const absentInLog = keys.filter((k) => presence[k] !== "PRESENT");
  const nativeStartUs = m ? parseNativeClock(m[3]!) : NaN;
  const browserStartUs = browser.timeUs[0];
  // Native prints mm:ss.mmm (truncated to ms).
  const nativeStartMatches =
    Number.isFinite(nativeStartUs) && browserStartUs !== undefined
      ? Math.floor(browserStartUs / 1000) * 1000 === nativeStartUs
      : null;
  const metadata: MetadataParity = {
    status:
      parserMissing.length || nativeStartMatches === false || !keys.length
        ? "fail"
        : absentInLog.length
          ? "warn"
          : "pass",
    presence,
    parserMissing,
    absentInLog,
    nativeStartMatches,
  };

  const { browserIndex: _b, nativeIndex: _n, ...samples } = alignment;
  const ok =
    embeddedLogs.status === "pass" &&
    alignment.exact &&
    groups.every((g) => g.status !== "fail") &&
    groups.find((g) => g.group === "timestamps")?.status === "pass" &&
    groups.find((g) => g.group === "gyro")?.status === "pass" &&
    metadata.status !== "fail";

  return {
    ok,
    logIndex,
    embeddedLogs,
    fields,
    samples: { ...samples, windows: prediction.windows, unmodeledEvents: prediction.unmodeled },
    groups,
    metadata,
    timingsMs: { native: native.ms, browser: browserMs },
  };
}

export function summarizeParity(report: ParityReport): string {
  const s = report.samples;
  const lines = [
    `log=${report.logIndex} ok=${report.ok} embedded=${report.embeddedLogs.browser}/${report.embeddedLogs.native}`,
    `samples browser=${s.browserSamples} native=${s.nativeSamples} aligned=${s.aligned} browserOnly=${s.browserOnly} predicted=${s.predictedNativeExclusions} nativeOnly=${s.nativeOnly} exact=${s.exact} windows=${JSON.stringify(s.windows)} unmodeled=${JSON.stringify(s.unmodeledEvents)}`,
    `fields browserOnly=${JSON.stringify(report.fields.browserOnly)} nativeOnly=${JSON.stringify(report.fields.nativeOnly)}`,
  ];
  for (const g of report.groups) {
    const maxAbs = Math.max(0, ...g.channels.map((c) => c.maxAbsError ?? Infinity));
    const meanAbs = g.channels.length
      ? g.channels.reduce((a, c) => a + (c.meanAbsError ?? Infinity), 0) / g.channels.length
      : null;
    const corrs = g.channels.map((c) => c.correlation).filter((c): c is number => c != null);
    const minCorr = corrs.length ? Math.min(...corrs) : null;
    lines.push(
      `${g.group} ${g.status} channels=${g.channels.length} aligned=${g.channels[0]?.alignedSamples ?? 0} maxAbs=${g.channels.length ? maxAbs : "n/a"} meanAbs=${meanAbs ?? "n/a"} minCorr=${minCorr ?? "n/a"}${g.channels.some((c) => c.status !== "pass") ? ` bad=${JSON.stringify(g.channels.filter((c) => c.status !== "pass").map((c) => `${c.field}:${c.status}`))}` : ""}`,
    );
  }
  lines.push(
    `metadata ${report.metadata.status} parserMissing=${JSON.stringify(report.metadata.parserMissing)} notPresent=${JSON.stringify(report.metadata.absentInLog.map((k) => `${k}:${report.metadata.presence[k]}`))} nativeStart=${report.metadata.nativeStartMatches}`,
  );
  return lines.join("\n");
}
