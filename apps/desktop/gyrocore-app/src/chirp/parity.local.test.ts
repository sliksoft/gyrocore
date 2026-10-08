// @vitest-environment node
/**
 * Opt-in parity check on a private / local log (never required by CI).
 * See tools/chirp_reference/make_browser_golden.py `--local`.
 */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";
import { compareChirpResults } from "./parityCompare";
import { runChirpOnBytes } from "./runChirp";

const GOLDEN = process.env.GYROCORE_CHIRP_LOCAL_GOLDEN;
const BBL = process.env.GYROCORE_CHIRP_LOCAL_BBL;

describe.skipIf(!GOLDEN || !BBL)("browser CHIRP parity — local log", () => {
  it("matches the Python reference", () => {
    const golden = JSON.parse(gunzipSync(readFileSync(GOLDEN!)).toString("utf8"));
    const bytes = new Uint8Array(readFileSync(BBL!));
    expect(createHash("sha256").update(bytes).digest("hex")).toBe(golden.bbl_sha256);
    const analysis = runChirpOnBytes(bytes, { filename: "local.bbl", logIndex: golden.log_index });
    const report = compareChirpResults(golden.result, analysis.result);
    if (process.env.CHIRP_PARITY_REPORT) {
      writeFileSync(process.env.CHIRP_PARITY_REPORT, JSON.stringify(report, null, 1));
    }
    expect(report.mismatches).toEqual([]);
  });
});
