import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { runBrowserNativeParity, summarizeParity } from "./parity";

/** Optional local multi-log BBL for live parity (not committed). */
const LOCAL_BBL =
  process.env.GYROCORE_BBL_FIXTURE ||
  "/home/sliksoft/GyroCore/BTFL_BLACKBOX_LOG_AIR65_C_20261005_224215_BETAFPVG473.BBL";

/** Full valid frame counts of the local fixture's three logs. */
const EXPECTED_FRAMES = [51669, 36657, 246358];

describe("browser vs native blackbox_decode parity (local multi-log fixture)", () => {
  it.skipIf(!existsSync(LOCAL_BBL))(
    "is full-frame sample-exact on every embedded log (patched native)",
    () => {
      for (const logIndex of [0, 1, 2]) {
        const report = runBrowserNativeParity({ bblPath: LOCAL_BBL, logIndex });
        console.log(`PARITY\n${summarizeParity(report)}`);
        console.log("TIMINGS_MS", report.timingsMs);
        expect(report.embeddedLogs.status).toBe("pass");
        expect(report.samples.unpatchedNativeSignature, "blackbox_decode on PATH is unpatched").toBe(false);
        expect(report.samples.exact).toBe(true);
        expect(report.samples.browserSamples).toBe(EXPECTED_FRAMES[logIndex]);
        expect(report.samples.nativeSamples).toBe(EXPECTED_FRAMES[logIndex]);
        // These logs contain FLIGHT_MODE events an unpatched decoder loses frames on.
        expect(report.samples.predictedNativeExclusions).toBeGreaterThan(0);
        for (const g of report.groups) expect(g.status, g.group).toBe("pass");
        expect(report.metadata.parserMissing).toEqual([]);
        expect(report.ok).toBe(true);
      }
    },
    300_000,
  );
});
