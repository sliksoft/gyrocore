// @vitest-environment node
import { describe, expect, it } from "vitest";
import { alignSamples, compareChannel, predictNativeDesyncExclusions } from "./parity";

/** 10 frames, loopIteration 0..9, time = 1000 + 100*i, I-interval 4 (I at 0, 4, 8). */
const iter = Float64Array.from({ length: 10 }, (_, i) => i);
const time = Float64Array.from({ length: 10 }, (_, i) => 1000 + 100 * i);
const excludedIdx = (p: { excluded: Uint8Array }) =>
  [...p.excluded].flatMap((v, i) => (v ? [i] : []));

describe("predictNativeDesyncExclusions", () => {
  it("FLIGHT_MODE with non-marker payload (0x44 'D') drops P-frames until next I-frame", () => {
    const p = predictNativeDesyncExclusions(
      iter,
      time,
      [{ event: 30, data: { newFlags: 68, lastFlags: 69 }, time: 1500 }],
      4,
    );
    expect(excludedIdx(p)).toEqual([5, 6, 7]);
    expect(p.windows).toEqual([{ eventType: 30, eventTimeUs: 1500, startIndex: 5, endIndex: 8 }]);
    expect(p.unmodeled).toEqual([]);
  });

  it("mid-log FLIGHT_MODE (newFlags=5) is excluded only up to the resync I-frame", () => {
    const p = predictNativeDesyncExclusions(
      iter,
      time,
      [{ event: 30, data: { newFlags: 5, lastFlags: 69 }, time: 1100 }],
      4,
    );
    expect(excludedIdx(p)).toEqual([1, 2, 3]);
  });

  it("payload 0x45 ('E') re-enters event parsing and does not desync", () => {
    const p = predictNativeDesyncExclusions(
      iter,
      time,
      [{ event: 30, data: { newFlags: 69, lastFlags: 5 }, time: 1500 }],
      4,
    );
    expect(excludedIdx(p)).toEqual([]);
    expect(p.unmodeled).toEqual([]);
  });

  it("no exclusion when the next frame is an I-frame, or the event trails the log", () => {
    const p = predictNativeDesyncExclusions(
      iter,
      time,
      [
        { event: 30, data: { newFlags: 68, lastFlags: 69 }, time: 1400 },
        { event: 15, data: { reason: 4 } },
      ],
      4,
    );
    expect(excludedIdx(p)).toEqual([]);
  });

  it("events native parses fully are ignored; other marker payloads are reported unmodeled", () => {
    const p = predictNativeDesyncExclusions(
      iter,
      time,
      [
        { event: 0, data: { time: 900 }, time: 900 },
        { event: 30, data: { newFlags: 0x50, lastFlags: 0 }, time: 1500 },
        { event: 42, data: {}, time: 1600 },
      ],
      4,
    );
    expect(excludedIdx(p)).toEqual([]);
    expect(p.unmodeled).toHaveLength(2);
  });
});

describe("alignSamples", () => {
  const predicted = new Uint8Array(10);
  predicted.fill(1, 5, 8);
  const keep = [0, 1, 2, 3, 4, 8, 9];
  const nIter = keep.map((i) => iter[i]!);
  const nTime = keep.map((i) => time[i]!);

  it("is exact when browser-only rows equal the predicted exclusions", () => {
    const a = alignSamples(iter, time, nIter, nTime, predicted);
    expect(a).toMatchObject({ aligned: 7, browserOnly: 3, nativeOnly: 0, predictedNativeExclusions: 3, exact: true });
    expect([...a.browserIndex]).toEqual(keep);
  });

  it("fails on an unpredicted browser-only row", () => {
    const a = alignSamples(iter, time, nIter.slice(1), nTime.slice(1), predicted);
    expect(a.exact).toBe(false);
  });

  it("fails on a native-only row", () => {
    const a = alignSamples(iter, time, [...nIter, 10], [...nTime, 2000], predicted);
    expect(a.nativeOnly).toBe(1);
    expect(a.exact).toBe(false);
  });

  it("fails when a predicted exclusion is actually present natively", () => {
    const a = alignSamples(iter, time, iter, time, predicted);
    expect(a.exact).toBe(false);
  });
});

describe("compareChannel", () => {
  const alignment = { browserIndex: Int32Array.of(0, 1, 2), nativeIndex: Int32Array.of(0, 1, 2) };

  it("passes only on exact equality and reports error stats", () => {
    const ok = compareChannel("gyroADC[0]", Float64Array.of(1, 2, 3), Float64Array.of(1, 2, 3), alignment);
    expect(ok).toMatchObject({ status: "pass", maxAbsError: 0, meanAbsError: 0, correlation: 1 });
    const bad = compareChannel("gyroADC[0]", Float64Array.of(1, 2, 3), Float64Array.of(1, 2, 4), alignment);
    expect(bad).toMatchObject({ status: "fail", maxAbsError: 1 });
  });

  it("constant channels pass with undefined correlation", () => {
    const c = compareChannel("debug[7]", Float64Array.of(0, 0, 0), Float64Array.of(0, 0, 0), alignment);
    expect(c).toMatchObject({ status: "pass", correlation: null });
  });

  it("distinguishes missing sides", () => {
    expect(compareChannel("axisF[0]", undefined, Float64Array.of(1), alignment).status).toBe("missing_browser");
    expect(compareChannel("axisF[0]", Float64Array.of(1), undefined, alignment).status).toBe("missing_native");
  });

  it("NaN on either side fails", () => {
    const c = compareChannel("motor[0]", Float64Array.of(1, NaN, 3), Float64Array.of(1, 2, 3), alignment);
    expect(c.status).toBe("fail");
  });
});
