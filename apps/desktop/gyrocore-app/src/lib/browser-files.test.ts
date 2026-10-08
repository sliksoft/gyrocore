import { describe, expect, it } from "vitest";
import {
  extensionOf,
  formatBytes,
  isSupportedBlackboxName,
  isSupportedCliName,
} from "./browser-files";

describe("browser-files", () => {
  it("validates blackbox extensions case-insensitively", () => {
    expect(isSupportedBlackboxName("flight.BBL")).toBe(true);
    expect(isSupportedBlackboxName("flight.bfl")).toBe(true);
    expect(isSupportedBlackboxName("flight.CSV")).toBe(true);
    expect(isSupportedBlackboxName("flight.txt")).toBe(false);
  });

  it("validates CLI extensions case-insensitively", () => {
    for (const name of ["dump.txt", "x.TEXT", "a.cli", "b.DIFF", "c.cfg", "d.CONF"]) {
      expect(isSupportedCliName(name)).toBe(true);
    }
    expect(isSupportedCliName("flight.bbl")).toBe(false);
  });

  it("parses extension and formats sizes", () => {
    expect(extensionOf("a.Bbl")).toBe(".bbl");
    expect(formatBytes(512)).toBe("512 bytes");
    expect(formatBytes(2048)).toMatch(/KB/);
  });
});
