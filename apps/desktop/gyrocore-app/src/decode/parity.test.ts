import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { runBrowserNativeParity, summarizeParity } from "./parity";

/** Optional local multi-log BBL for live parity (not committed). */
const LOCAL_BBL =
  process.env.GYROCORE_BBL_FIXTURE ||
  "/home/sliksoft/GyroCore/BTFL_BLACKBOX_LOG_AIR65_C_20261005_224215_BETAFPVG473.BBL";

describe("browser vs native blackbox_decode parity (local multi-log fixture)", () => {
  it.skipIf(!existsSync(LOCAL_BBL))(
    "is sample-exact on every embedded log after the native desync exclusion rule",
    () => {
      for (const logIndex of [0, 1, 2]) {
        const report = runBrowserNativeParity({ bblPath: LOCAL_BBL, logIndex });
        console.log(`PARITY\n${summarizeParity(report)}`);
        console.log("TIMINGS_MS", report.timingsMs);
        expect(report.embeddedLogs.status).toBe("pass");
        expect(report.samples.exact).toBe(true);
        expect(report.samples.nativeOnly).toBe(0);
        // FLIGHT_MODE events with a non-marker payload byte make native drop frames.
        expect(report.samples.browserOnly).toBe(report.samples.predictedNativeExclusions);
        expect(report.samples.windows.length).toBeGreaterThan(0);
        for (const g of report.groups) expect(g.status, g.group).toBe("pass");
        expect(report.metadata.parserMissing).toEqual([]);
        expect(report.ok).toBe(true);
      }
    },
    300_000,
  );
});
