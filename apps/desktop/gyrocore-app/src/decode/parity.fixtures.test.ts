// @vitest-environment node
/**
 * Committed-fixture parity and multi-log boundary proofs (run in CI, where
 * blackbox_decode is on PATH). Uses gzipped synthetic CHIRP logs from tests/fixtures.
 */
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { afterAll, describe, expect, it } from "vitest";
import { FlightLog } from "@bf-blackbox/flightlog.js";
import { findLogStartOffsets, readLogHeaders } from "./headers";
import { normalizeFromFlightLog } from "./normalizeFromFlightLog";
import { runBrowserNativeParity, summarizeParity } from "./parity";
import type { NormalizedDecodedLog } from "./types";

const FIXTURES = fileURLToPath(new URL("../../../../../tests/fixtures/chirp/wu7/bbl", import.meta.url));
const HAS_NATIVE = spawnSync("blackbox_decode", ["--help"]).error === undefined;

const workDir = mkdtempSync(join(tmpdir(), "gyrocore-parity-"));
const written: string[] = [];
afterAll(() => {
  for (const f of written) unlinkSync(f);
});

function fixtureBytes(name: string): Uint8Array {
  return new Uint8Array(gunzipSync(readFileSync(join(FIXTURES, `${name}.bbl.gz`))));
}

function writeTemp(name: string, bytes: Uint8Array): string {
  const p = join(workDir, name);
  writeFileSync(p, bytes);
  written.push(p);
  return p;
}

function decode(bytes: Uint8Array, logIndex: number | null): NormalizedDecodedLog {
  return normalizeFromFlightLog(new FlightLog(bytes), {
    filename: "x.bbl",
    sizeBytes: bytes.byteLength,
    selectedIndex: logIndex,
    includeSeries: true,
    rawHeadersForLog: (i) => readLogHeaders(bytes, i),
  });
}

const MULTILOG_PARTS = ["clean_single_axis", "three_axis_sequence", "known_gain"] as const;

function multilogBytes(): Uint8Array {
  const parts = MULTILOG_PARTS.map(fixtureBytes);
  const out = new Uint8Array(parts.reduce((n, p) => n + p.byteLength, 0));
  let off = 0;
  for (const p of parts) {
    out.set(p, off);
    off += p.byteLength;
  }
  return out;
}

describe.skipIf(!HAS_NATIVE)("committed fixture parity vs native blackbox_decode", () => {
  it("clean_single_axis is sample-exact; axisP is absent in the log, not dropped", () => {
    const path = writeTemp("clean_single_axis.bbl", fixtureBytes("clean_single_axis"));
    const report = runBrowserNativeParity({ bblPath: path, logIndex: 0 });
    console.log(`PARITY\n${summarizeParity(report)}`);
    expect(report.ok).toBe(true);
    expect(report.samples.browserSamples).toBe(report.samples.nativeSamples);
    expect(report.samples.aligned).toBe(report.samples.nativeSamples);
    // The synthetic CHIRP log logs no PID terms: absent on both sides.
    expect(report.groups.find((g) => g.group === "pid")?.status).toBe("absent_in_log");
    for (const g of ["timestamps", "gyro", "setpoint", "motors", "debug"]) {
      expect(report.groups.find((r) => r.group === g)?.status, g).toBe("pass");
    }
    expect(report.metadata.parserMissing).toEqual([]);
  });

  it("each log of a concatenated 3-log file matches native for that index", () => {
    const path = writeTemp("multilog.bbl", multilogBytes());
    for (let i = 0; i < MULTILOG_PARTS.length; i++) {
      const report = runBrowserNativeParity({ bblPath: path, logIndex: i });
      expect(report.embeddedLogs, `log ${i}`).toEqual({ browser: 3, native: 3, status: "pass" });
      expect(report.ok, summarizeParity(report)).toBe(true);
    }
  });
});

describe("multi-log boundaries (browser decoder)", () => {
  const bytes = multilogBytes();
  const standalone = MULTILOG_PARTS.map((name) => decode(fixtureBytes(name), 0));

  it("finds exactly one log start per concatenated part", () => {
    expect(findLogStartOffsets(bytes)).toHaveLength(MULTILOG_PARTS.length);
    expect(decode(bytes, 0).embedded.logCount).toBe(MULTILOG_PARTS.length);
  });

  it("selecting log i yields exactly the standalone decode of part i (no neighbour leakage)", () => {
    for (let i = 0; i < MULTILOG_PARTS.length; i++) {
      const sel = decode(bytes, i);
      const ref = standalone[i]!;
      expect(sel.embedded.selectedIndex).toBe(i);
      expect(sel.timeUs).toEqual(ref.timeUs);
      expect(sel.loopIteration).toEqual(ref.loopIteration);
      expect(Object.keys(sel.series).sort()).toEqual(Object.keys(ref.series).sort());
      for (const k of Object.keys(ref.series)) expect(sel.series[k], k).toEqual(ref.series[k]);
      const flight = sel.embedded.flights[i]!;
      expect(flight.sampleCount).toBe(ref.timeUs.length);
      expect(flight.startTimeUs).toBe(ref.timeUs[0]);
      expect(flight.endTimeUs).toBe(ref.timeUs[ref.timeUs.length - 1]);
      expect(sel.metadata.boardInformation).toBe(ref.metadata.boardInformation);
    }
  });

  it("explicit selection overrides the recommended log", () => {
    const rec = decode(bytes, null).embedded.recommendedIndex;
    // three_axis_sequence is the longest part.
    expect(rec).toBe(1);
    for (let i = 0; i < MULTILOG_PARTS.length; i++) expect(decode(bytes, i).embedded.selectedIndex).toBe(i);
  });
});
