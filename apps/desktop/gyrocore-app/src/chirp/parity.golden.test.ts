// @vitest-environment node
/**
 * CHIRP_BROWSER_WU1 primary gate: browser CHIRP vs the Python reference.
 *
 * - BBL layer: every WU7 fixture decoded by FlightLog in-browser vs
 *   `identify_chirp_system_from_bbl` (native blackbox_decode) goldens.
 * - Frame layer: identical frame tables through both pipelines for edge cases
 *   without a BBL fixture (no CHIRP, gaps, resets, NaN timestamps, ...).
 *
 * Goldens: tests/fixtures/chirp/browser/*.json.gz
 * (tools/chirp_reference/make_browser_golden.py). Set CHIRP_PARITY_REPORT=<path>
 * to write the per-series error statistics.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import type { ChirpFrames } from "./frames";
import { compareChirpResults, type ParityReport } from "./parityCompare";
import { identifyChirpSystem } from "./pipeline";
import { chirpRejection, runChirpOnBytes } from "./runChirp";
import { parseChirpSysConfig } from "./sysconfig";

const FIXTURES = fileURLToPath(new URL("../../../../../tests/fixtures/chirp/", import.meta.url));

type Json = Record<string, any>;
const loadGz = (rel: string): Json => JSON.parse(gunzipSync(readFileSync(FIXTURES + rel)).toString("utf8"));

const bblGolden = loadGz("browser/bbl_golden.json.gz");
const frameGolden = loadGz("browser/frame_cases.json.gz");
const reports: Record<string, ParityReport> = {};

function framesFromColumns(cols: Record<string, Array<number | null>>): ChirpFrames {
  const f = (k: string) => Float64Array.from(cols[k]!, (v) => (v === null ? NaN : v));
  const hasFlags = Array.isArray(cols.flags);
  return {
    timeUs: f("time"),
    setpoint: [f("sp0"), f("sp1"), f("sp2")],
    gyroAdc: [f("g0"), f("g1"), f("g2")],
    debug: [f("d0"), f("d1"), f("d2"), f("d3")],
    flightModeFlags: hasFlags ? Int32Array.from(cols.flags!, (v) => v ?? -1) : null,
    malformedRows: 0,
    warnings: hasFlags ? [] : ["flight_mode_flags_column_missing"],
    subsampled: false,
  };
}

function expectParity(name: string, reference: unknown, browser: unknown) {
  const report = compareChirpResults(reference, browser);
  reports[name] = report;
  expect(report.mismatches, `${name} mismatches`).toEqual([]);
}

describe("browser CHIRP parity vs Python reference — WU7 BBL fixtures", () => {
  for (const [caseId, entry] of Object.entries(bblGolden.cases as Record<string, Json>)) {
    it(caseId, () => {
      const bytes = new Uint8Array(gunzipSync(readFileSync(FIXTURES + "wu7/" + entry.bbl)));
      const analysis = runChirpOnBytes(bytes, { filename: `${caseId}.bbl`, logIndex: null });
      expectParity(`bbl:${caseId}`, entry.result, analysis.result);
      expect(analysis.source.inputPolicy).toBe("full_frame");
      // Never usable without real series; never a rejection without a reason.
      if (analysis.rejection === null) {
        expect(analysis.result.usable).toBe(true);
        const ax = Object.values(analysis.result.axes).find((a) => a?.usable)!;
        expect(ax.transfer_function!.magnitude_db.length).toBeGreaterThan(0);
        expect(ax.transfer_function!.phase_deg.length).toBe(ax.transfer_function!.frequencies_hz.length);
        expect(ax.transfer_function!.coherence.length).toBe(ax.transfer_function!.frequencies_hz.length);
      } else {
        expect(analysis.result.usable).toBe(false);
        expect(analysis.rejection.code.length).toBeGreaterThan(0);
      }
    });
  }
});

describe("browser CHIRP parity vs Python reference — frame-level edge cases", () => {
  for (const c of frameGolden.cases as Json[]) {
    it(c.case_id, () => {
      const sysconfig = parseChirpSysConfig(c.headers as Array<[string, string]>);
      const result = identifyChirpSystem({ frames: framesFromColumns(c.columns), sysconfig });
      expectParity(`frames:${c.case_id}`, c.result, result);
      expect(chirpRejection(result) === null).toBe(result.usable);
    });
  }
});

describe("parity report", () => {
  it("writes per-series statistics when requested", () => {
    const out = process.env.CHIRP_PARITY_REPORT;
    if (out) writeFileSync(out, JSON.stringify(reports, null, 1));
    expect(Object.keys(reports).length).toBe(
      Object.keys(bblGolden.cases).length + (frameGolden.cases as Json[]).length,
    );
  });
});
