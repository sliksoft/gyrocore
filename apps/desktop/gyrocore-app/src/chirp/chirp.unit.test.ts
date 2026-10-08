// @vitest-environment node
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { describe, expect, it, vi } from "vitest";
import { complexFftInPlace, realFft } from "./fft";
import { ChirpFramesError, chirpFramesFromFlightLog, type FrameSource } from "./frames";
import { jsRound, npMedian, npRint, npSum } from "./numeric";
import { compareChirpResults, toPlain } from "./parityCompare";
import { chirpAxisViolation, chirpRejection, primaryUsableAxis, runChirpOnBytes, transferablesOf } from "./runChirp";
import type { ChirpResponse, ChirpSystemIdResult } from "./types";
import { chirpPayloadFromAnalysis } from "./workspace";

const WU7 = fileURLToPath(new URL("../../../../../tests/fixtures/chirp/wu7/bbl/", import.meta.url));
const fixture = (name: string) => new Uint8Array(gunzipSync(readFileSync(WU7 + name + ".bbl.gz")));

describe("numeric helpers", () => {
  it("rounding matches JS Math.round and numpy rint", () => {
    expect([jsRound(2.5), jsRound(-2.5), jsRound(256)]).toEqual([3, -2, 256]);
    expect([npRint(0.5), npRint(1.5), npRint(2.5), npRint(2.4999), npRint(3.5)]).toEqual([0, 2, 2, 2, 4]);
  });
  it("median and pairwise sum", () => {
    expect(npMedian([3, 1, 2])).toBe(2);
    expect(npMedian([4, 1, 3, 2])).toBe(2.5);
    const a = Array.from({ length: 20000 }, (_, i) => Math.sin(i) * 1e3);
    let naive = 0;
    for (const v of a) naive += v;
    expect(Math.abs(npSum(a) - naive)).toBeLessThan(1e-8);
  });
});

describe("fft", () => {
  it("radix-2 agrees with a direct DFT", () => {
    const n = 64;
    const x = Float64Array.from({ length: n }, (_, i) => Math.cos(0.3 * i) + 0.2 * Math.sin(1.7 * i));
    const { re, im } = realFft(x);
    for (let k = 0; k <= n / 2; k++) {
      let sr = 0;
      let si = 0;
      for (let t = 0; t < n; t++) {
        sr += x[t]! * Math.cos((-2 * Math.PI * k * t) / n);
        si += x[t]! * Math.sin((-2 * Math.PI * k * t) / n);
      }
      expect(re[k]).toBeCloseTo(sr, 10);
      expect(im[k]).toBeCloseTo(si, 10);
    }
  });
  it("inverse is unnormalized (round trip scales by N)", () => {
    const re = Float64Array.from([1, 2, 3, 4, 5, 6, 7, 8]);
    const im = new Float64Array(8);
    complexFftInPlace(re, im);
    complexFftInPlace(re, im, true);
    expect(Array.from(re, (v) => Math.round(v / 8))).toEqual([1, 2, 3, 4, 5, 6, 7, 8]);
  });
  it("non power-of-two sizes fall back to the direct DFT", () => {
    const re = Float64Array.from([1, 0, 0, 0, 0, 0]);
    const im = new Float64Array(6);
    complexFftInPlace(re, im);
    expect(Array.from(re)).toEqual([1, 1, 1, 1, 1, 1]);
  });
});

describe("frame table (missing / malformed input)", () => {
  const fake = (names: string[], frames: Array<Array<number | null>>): FrameSource => ({
    getMainFieldNames: () => names,
    getMainFieldIndexByName: (n) => (names.indexOf(n) >= 0 ? names.indexOf(n) : undefined),
    getMinTime: () => 0,
    getMaxTime: () => 10,
    getChunksInTimeRange: () => [{ frames: frames as number[][] }],
  });
  const ALL = [
    "loopIteration",
    "time",
    "setpoint[0]",
    "setpoint[1]",
    "setpoint[2]",
    "gyroADC[0]",
    "gyroADC[1]",
    "gyroADC[2]",
    "debug[0]",
    "debug[1]",
    "debug[2]",
    "debug[3]",
    "flightModeFlags",
  ];

  it("rejects a missing required channel with a structured code", () => {
    const names = ALL.filter((n) => n !== "setpoint[1]");
    expect(() => chirpFramesFromFlightLog(fake(names, []))).toThrow(ChirpFramesError);
    expect(() => chirpFramesFromFlightLog(fake(names, []))).toThrow("missing_required_field:setpoint[1]");
  });
  it("skips malformed rows and maps null flags to keep-state", () => {
    const row = (t: number | null, flags: number | null) => [0, t, 1, 2, 3, 4, 5, 6, 0, 0, 0, 0, flags];
    const out = chirpFramesFromFlightLog(fake(ALL, [row(1, null), row(null, 64), row(3, 64)]));
    expect(Array.from(out.timeUs)).toEqual([1, 3]);
    expect(Array.from(out.flightModeFlags!)).toEqual([-1, 64]);
    expect(out.warnings).toContain("malformed_csv_rows_skipped");
  });
});

describe("structured rejection (no empty-array success)", () => {
  it("no CHIRP debug mode -> error rejection, not available", () => {
    const a = runChirpOnBytes(fixture("malformed_wrong_debug_mode"), { filename: "x.bbl" });
    expect(a.result.status).toBe("error");
    expect(a.rejection).toEqual({ code: "not_chirp_debug_mode", detail: "not_chirp_debug_mode" });
    expect(Object.keys(a.result.axes)).toEqual([]);
  });
  it("missing debug field -> missing_required_field", () => {
    const a = runChirpOnBytes(fixture("malformed_missing_debug_field"), { filename: "x.bbl" });
    expect(a.rejection?.code).toBe("missing_required_field");
  });
  it("low quality -> chirp_unusable with gate codes", () => {
    const a = runChirpOnBytes(fixture("poor_coherence"), { filename: "x.bbl" });
    expect(a.rejection?.code).toBe("chirp_unusable");
    expect(a.rejection?.detail).toContain("roll:low_coherence");
  });
  it("valid fixture -> non-empty equal-length series and transferable buffers", () => {
    const a = runChirpOnBytes(fixture("clean_single_axis"), { filename: "x.bbl" });
    expect(a.rejection).toBeNull();
    const ax = primaryUsableAxis(a.result)!;
    const tf = ax.transfer_function!;
    expect(tf.frequencies_hz.length).toBe(257);
    expect(tf.magnitude_db.length).toBe(257);
    expect(tf.phase_deg.length).toBe(257);
    expect(tf.coherence.length).toBe(257);
    expect(a.source.framesDecoded).toBeGreaterThan(2000);
    expect(transferablesOf(a).length).toBeGreaterThanOrEqual(6);
  });
  it("usable result stripped of series is never treated as success", () => {
    const a = runChirpOnBytes(fixture("clean_single_axis"), { filename: "x.bbl" });
    const broken: ChirpSystemIdResult = structuredClone(a.result);
    const roll = broken.axes.roll!;
    roll.transfer_function = { ...roll.transfer_function!, magnitude_db: new Float64Array(0) };
    expect(primaryUsableAxis(broken)).toBeNull();
    expect(chirpRejection(broken)?.code).toBe("chirp_series_empty");
  });
});

describe("parity comparator detects deviations (mutation check)", () => {
  const base = runChirpOnBytes(fixture("clean_single_axis"), { filename: "x.bbl" }).result;
  const ref = toPlain(base) as Record<string, any>;
  it("identical results pass", () => {
    expect(compareChirpResults(ref, base).mismatches).toEqual([]);
  });
  it("in-band magnitude drift of 1e-6 dB fails", () => {
    const mutated = structuredClone(base);
    mutated.axes.roll!.transfer_function!.magnitude_db[20] += 1e-6;
    expect(compareChirpResults(ref, mutated).mismatches.join()).toMatch(/magnitude_db\[20\]/);
  });
  it("flipped gate / changed warning / mask bit fail", () => {
    const m1 = structuredClone(base);
    m1.axes.roll!.quality.gates[0]!.passed = false;
    expect(compareChirpResults(ref, m1).mismatches.length).toBeGreaterThan(0);
    const m2 = structuredClone(base);
    m2.warnings = ["extra"];
    expect(compareChirpResults(ref, m2).mismatches.length).toBeGreaterThan(0);
    const m3 = structuredClone(base);
    m3.axes.roll!.usable_mask![10] ^= 1;
    expect(compareChirpResults(ref, m3).mismatches.join()).toMatch(/usable_mask/);
  });
});

describe("no network / no Tauri", () => {
  it("garbage bytes reject without network or Tauri", () => {
    const fetchSpy = vi.fn(() => {
      throw new Error("unexpected_network");
    });
    const prev = globalThis.fetch;
    globalThis.fetch = fetchSpy as unknown as typeof fetch;
    try {
      expect(() => runChirpOnBytes(new Uint8Array([1, 2, 3]), { filename: "bad.bbl" })).toThrow("no_embedded_logs");
      runChirpOnBytes(fixture("clean_single_axis"), { filename: "x.bbl" });
      expect(fetchSpy).not.toHaveBeenCalled();
      expect((globalThis as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__).toBeUndefined();
    } finally {
      globalThis.fetch = prev;
    }
  });
});

describe("CHIRP contract invariants (usable => valid series)", () => {
  const valid = () => structuredClone(runChirpOnBytes(fixture("clean_single_axis"), { filename: "x.bbl" }).result);
  const firstUsableBin = (r: ChirpSystemIdResult) => r.axes.roll!.usable_mask!.indexOf(1);

  it("valid fixture satisfies every invariant", () => {
    const r = valid();
    expect(chirpAxisViolation(r.axes.roll!)).toBeNull();
    expect(chirpRejection(r)).toBeNull();
  });

  it("-Infinity dB outside the usable band is legitimate (floored bins)", () => {
    const r = valid();
    const k = r.axes.roll!.usable_mask!.indexOf(0);
    r.axes.roll!.transfer_function!.magnitude_db[k] = -Infinity;
    expect(chirpRejection(r)).toBeNull();
  });

  const mutations: Array<[string, (r: ChirpSystemIdResult) => void, string]> = [
    ["empty frequency", (r) => void (r.axes.roll!.transfer_function!.frequencies_hz = new Float64Array(0)), "chirp_series_empty"],
    ["empty phase", (r) => void (r.axes.roll!.transfer_function!.phase_deg = new Float64Array(0)), "chirp_series_empty"],
    ["empty coherence", (r) => void (r.axes.roll!.transfer_function!.coherence = new Float64Array(0)), "chirp_series_empty"],
    ["no transfer function", (r) => void delete r.axes.roll!.transfer_function, "chirp_series_empty"],
    [
      "unequal lengths",
      (r) => void (r.axes.roll!.transfer_function!.phase_deg = r.axes.roll!.transfer_function!.phase_deg.subarray(1)),
      "chirp_series_length_mismatch",
    ],
    ["NaN magnitude in usable band", (r) => void (r.axes.roll!.transfer_function!.magnitude_db[firstUsableBin(r)] = NaN), "chirp_nonfinite_usable_band"],
    ["-Infinity magnitude in usable band", (r) => void (r.axes.roll!.transfer_function!.magnitude_db[firstUsableBin(r)] = -Infinity), "chirp_nonfinite_usable_band"],
    ["Infinity phase in usable band", (r) => void (r.axes.roll!.transfer_function!.phase_deg[firstUsableBin(r)] = Infinity), "chirp_nonfinite_usable_band"],
    ["coherence > 1 in usable band", (r) => void (r.axes.roll!.transfer_function!.coherence[firstUsableBin(r)] = 1.5), "chirp_nonfinite_usable_band"],
    ["no usable range", (r) => void (r.axes.roll!.quality.usable_range_hz = null), "chirp_invalid_frequency_range"],
    ["inverted usable range", (r) => void (r.axes.roll!.quality.usable_range_hz = [100, 10]), "chirp_invalid_frequency_range"],
    ["range outside analysis band", (r) => void (r.axes.roll!.quality.usable_range_hz = [1, 1e6]), "chirp_invalid_frequency_range"],
    ["NaN range", (r) => void (r.axes.roll!.quality.usable_range_hz = [NaN, 50]), "chirp_invalid_frequency_range"],
    ["no usable mask", (r) => void delete r.axes.roll!.usable_mask, "chirp_invalid_usable_band"],
    ["empty usable mask", (r) => void r.axes.roll!.usable_mask!.fill(0), "chirp_invalid_usable_band"],
    ["usable but status unusable", (r) => void (r.status = "unusable"), "chirp_status_inconsistent"],
    ["usable but status error-free unknown", (r) => void (r.status = "pass" as ChirpSystemIdResult["status"]), "chirp_status_inconsistent"],
  ];

  it.each(mutations)("%s -> explicit rejection", (_label, mutate, code) => {
    const r = valid();
    mutate(r);
    expect(chirpRejection(r)?.code).toBe(code);
    expect(primaryUsableAxis(r) === null || code === "chirp_status_inconsistent").toBe(true);
  });

  it.each(mutations)("%s -> workspace payload is not available", (_label, mutate) => {
    const a = runChirpOnBytes(fixture("clean_single_axis"), { filename: "x.bbl" });
    const r = structuredClone(a.result);
    mutate(r);
    const c = chirpPayloadFromAnalysis({ ...a, result: r, rejection: chirpRejection(r) });
    expect(c.available).toBe(false);
    expect(c.magnitude).toEqual([]);
  });
});
