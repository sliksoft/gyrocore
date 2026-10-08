import { describe, expect, it } from "vitest";
import { findLogStartOffsets, LOG_START_MARKER, readLogHeaders, scanHeaderLines } from "./headers";

const enc = (s: string) => new TextEncoder().encode(s);

function fakeLog(extra: string): string {
  return `${LOG_START_MARKER}\nH Data version:2\nH Craft name:\n${extra}I\x00\x01\x02`;
}

describe("raw header scan", () => {
  const bytes = enc(fakeLog("H Board information:AAAA ONE\n") + fakeLog("H looptime:125\n"));

  it("finds every embedded log start", () => {
    expect(findLogStartOffsets(bytes)).toHaveLength(2);
  });

  it("reads only the selected log's H lines", () => {
    expect(readLogHeaders(bytes, 0)).toMatchObject({ "Data version": "2", "Board information": "AAAA ONE" });
    expect(readLogHeaders(bytes, 0).looptime).toBeUndefined();
    expect(readLogHeaders(bytes, 1)).toMatchObject({ looptime: "125", "Craft name": "" });
    expect(readLogHeaders(bytes, 2)).toEqual({});
  });

  it("stops at the first non-header byte", () => {
    expect(Object.keys(scanHeaderLines(enc("H a:1\nH b:2\nPxx\nH c:3\n"), 0))).toEqual(["a", "b"]);
  });
});
