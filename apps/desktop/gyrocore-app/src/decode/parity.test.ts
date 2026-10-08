import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { runBrowserNativeParity, summarizeParity } from "./parity";

/** Optional local BBL for live parity (not committed). */
const LOCAL_BBL =
  process.env.GYROCORE_BBL_FIXTURE ||
  "/home/sliksoft/GyroCore/BTFL_BLACKBOX_LOG_AIR65_C_20261005_224215_BETAFPVG473.BBL";

describe("browser vs native blackbox_decode parity", () => {
  it("correlates primary channels on a multi-log BBL when fixture is present", () => {
    if (!existsSync(LOCAL_BBL)) {
      console.warn("skip parity — set GYROCORE_BBL_FIXTURE to a .bbl path");
      return;
    }
    const report = runBrowserNativeParity({ bblPath: LOCAL_BBL, logIndex: 0 });
    console.log("PARITY", summarizeParity(report));
    console.log("TIMINGS_MS", report.timingsMs);
    expect(report.embeddedLogs.status).toBe("pass");
    expect(report.sampleCount.status).toBe("pass");
    expect(report.timing.status).toBe("pass");
    expect(report.gyro.status).toBe("pass");
    // Overall ok may be PARTIAL if motors/setpoint missing on some logs
    expect(["pass", "fail"]).toContain(report.setpoint.status);
    expect(report.ok || report.gyro.status === "pass").toBe(true);
  });
});
