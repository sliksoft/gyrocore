/**
 * Compare browser FlightLog-normalized output against native blackbox_decode CSV.
 * Node/test-only — not bundled into the PWA shell.
 */

import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { FlightLog } from "@bf-blackbox/flightlog.js";
import { normalizeFromFlightLog } from "./normalizeFromFlightLog";

export type ParityFieldReport = {
  field: string;
  status: "pass" | "fail" | "missing_browser" | "missing_native" | "skipped";
  detail?: string;
};

export type ParityReport = {
  ok: boolean;
  embeddedLogs: ParityFieldReport;
  metadata: ParityFieldReport;
  fields: ParityFieldReport;
  sampleCount: ParityFieldReport;
  timing: ParityFieldReport;
  gyro: ParityFieldReport;
  setpoint: ParityFieldReport;
  motors: ParityFieldReport;
  pidDebug: ParityFieldReport;
  notes: string[];
  timingsMs: { native: number; browser: number };
};

function parseCsv(text: string): { headers: string[]; rows: number[][] } {
  const lines = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
  if (!lines.length) return { headers: [], rows: [] };
  const headers = lines[0]!.split(",").map((h) => h.trim());
  const rows: number[][] = [];
  for (let i = 1; i < lines.length; i++) {
    rows.push(lines[i]!.split(",").map((c) => Number(c)));
  }
  return { headers, rows };
}

function nativeDecode(bblPath: string, logIndex0: number): { csv: string; stderr: string; ms: number } {
  const t0 = Date.now();
  const proc = spawnSync(
    "blackbox_decode",
    ["--stdout", "--index", String(logIndex0 + 1), bblPath],
    { encoding: "utf8", maxBuffer: 256 * 1024 * 1024 },
  );
  const ms = Date.now() - t0;
  if (proc.error) throw proc.error;
  if (!proc.stdout) throw new Error(`native_decode_failed:${proc.stderr || proc.status}`);
  return { csv: proc.stdout, stderr: proc.stderr || "", ms };
}

function corr(a: Float64Array, b: number[], maxN = 8000): number | null {
  const n = Math.min(a.length, b.length, maxN);
  if (n < 10) return null;
  let sa = 0,
    sb = 0,
    saa = 0,
    sbb = 0,
    sab = 0;
  let used = 0;
  for (let i = 0; i < n; i++) {
    const x = a[i]!;
    const y = b[i]!;
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    sa += x;
    sb += y;
    saa += x * x;
    sbb += y * y;
    sab += x * y;
    used++;
  }
  if (used < 10) return null;
  const denom = Math.sqrt((used * saa - sa * sa) * (used * sbb - sb * sb));
  if (denom <= 0) return null;
  return (used * sab - sa * sb) / denom;
}

function col(headers: string[], rows: number[][], name: string): number[] {
  const idx = headers.findIndex(
    (h) => h === name || h.startsWith(`${name} `) || h.startsWith(`${name}(`),
  );
  if (idx < 0) return [];
  return rows.map((r) => r[idx]!);
}

export function runBrowserNativeParity(opts: {
  bblPath: string;
  logIndex?: number;
}): ParityReport {
  const logIndex = opts.logIndex ?? 0;
  const bytes = new Uint8Array(readFileSync(opts.bblPath));
  const notes: string[] = [
    "Absolute unit scales may differ (FlightLog vs blackbox_decode defaults); correlation is the primary parity signal.",
  ];

  const tB0 = Date.now();
  const fl = new FlightLog(bytes);
  const browser = normalizeFromFlightLog(fl, {
    filename: opts.bblPath.split(/[/\\]/).pop() || "flight.bbl",
    sizeBytes: bytes.byteLength,
    selectedIndex: logIndex,
    includeSeries: true,
  });
  const browserMs = Date.now() - tB0;

  const native = nativeDecode(opts.bblPath, logIndex);
  const parsed = parseCsv(native.csv);

  const report: ParityReport = {
    ok: true,
    embeddedLogs: { field: "embedded", status: "pass" },
    metadata: { field: "metadata", status: "pass" },
    fields: { field: "fields", status: "pass" },
    sampleCount: { field: "sample_count", status: "pass" },
    timing: { field: "timing", status: "pass" },
    gyro: { field: "gyro", status: "pass" },
    setpoint: { field: "setpoint", status: "pass" },
    motors: { field: "motors", status: "pass" },
    pidDebug: { field: "pid_debug", status: "pass" },
    notes,
    timingsMs: { native: native.ms, browser: browserMs },
  };

  const m = /Log\s+(\d+)\s+of\s+(\d+)/i.exec(native.stderr);
  if (m) {
    const nativeCount = Number(m[2]);
    if (nativeCount !== browser.embedded.logCount) {
      report.embeddedLogs = {
        field: "embedded",
        status: "fail",
        detail: `browser=${browser.embedded.logCount} native=${nativeCount}`,
      };
      report.ok = false;
    } else {
      report.embeddedLogs = {
        field: "embedded",
        status: "pass",
        detail: `count=${nativeCount}`,
      };
    }
  } else {
    notes.push(`native_stderr_missing_log_of_count; browser_count=${browser.embedded.logCount}`);
  }

  const nativeSamples = parsed.rows.length;
  const browserSamples = browser.timeUs.length;
  const sampleTol = Math.max(5, Math.floor(nativeSamples * 0.02));
  if (Math.abs(nativeSamples - browserSamples) > sampleTol) {
    report.sampleCount = {
      field: "sample_count",
      status: "fail",
      detail: `browser=${browserSamples} native=${nativeSamples}`,
    };
    report.ok = false;
  } else {
    report.sampleCount = {
      field: "sample_count",
      status: "pass",
      detail: `browser=${browserSamples} native=${nativeSamples}`,
    };
  }

  const nativeFields = new Set(parsed.headers.map((h) => h.replace(/\s*\(.*\)$/, "").trim()));
  const overlap = browser.metadata.fieldNames.filter((f) => nativeFields.has(f));
  report.fields =
    overlap.length >= 8
      ? { field: "fields", status: "pass", detail: `overlap=${overlap.length}` }
      : { field: "fields", status: "fail", detail: `overlap=${overlap.length}` };
  if (report.fields.status === "fail") report.ok = false;

  if (browser.metadata.firmwareVersion || browser.metadata.craftName) {
    report.metadata = {
      field: "metadata",
      status: "pass",
      detail: `${browser.metadata.firmwareType || "?"} ${browser.metadata.firmwareVersion || ""}`.trim(),
    };
  } else {
    report.metadata = { field: "metadata", status: "skipped", detail: "sparse_sysconfig" };
    notes.push("browser metadata sparse");
  }

  const compare = (
    slot: "gyro" | "setpoint" | "motors" | "pidDebug" | "timing",
    browserName: string,
    nativeName: string,
    minCorr: number,
  ) => {
    const b = browserName === "time" ? browser.timeUs : browser.series[browserName];
    const n = col(parsed.headers, parsed.rows, nativeName);
    if (!b || !b.length) {
      report[slot] = { field: browserName, status: "missing_browser" };
      if (slot === "gyro" || slot === "timing") report.ok = false;
      return;
    }
    if (!n.length) {
      report[slot] = { field: browserName, status: "missing_native", detail: nativeName };
      return;
    }
    const c = corr(b, n);
    if (c == null || c < minCorr) {
      report[slot] = { field: browserName, status: "fail", detail: `corr=${c}` };
      report.ok = false;
    } else {
      report[slot] = { field: browserName, status: "pass", detail: `corr=${c.toFixed(4)}` };
    }
  };

  compare("timing", "time", "time", 0.999);
  compare("gyro", "gyroADC[0]", "gyroADC[0]", 0.95);
  compare("setpoint", "setpoint[0]", "setpoint[0]", 0.9);
  compare("motors", "motor[0]", "motor[0]", 0.85);
  compare("pidDebug", "axisP[0]", "axisP[0]", 0.85);

  return report;
}

export function summarizeParity(report: ParityReport): string {
  return [
    report.embeddedLogs,
    report.metadata,
    report.fields,
    report.sampleCount,
    report.timing,
    report.gyro,
    report.setpoint,
    report.motors,
    report.pidDebug,
  ]
    .map((r) => `${r.field}:${r.status}${r.detail ? `(${r.detail})` : ""}`)
    .join(" | ");
}
