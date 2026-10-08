import { describe, expect, it } from "vitest";
import type { ChirpPayload } from "@/bridge/types";
import { chirpDisplay } from "./chirpStatus";

const series = (n: number) => ({
  magnitude: Array.from({ length: n }, (_, i) => ({ hz: i + 1, db: -3 })),
  phase: Array.from({ length: n }, (_, i) => ({ hz: i + 1, deg: -30 })),
  coherence: Array.from({ length: n }, (_, i) => ({ hz: i + 1, value: 0.9 })),
});
const usable = (status?: string): ChirpPayload => ({ available: true, status, ...series(12) });

describe("canonical CHIRP status mapping", () => {
  it.each([
    ["ok", "PASS"],
    ["usable_with_warnings", "WARN"],
  ])("%s -> %s (chartable)", (status, badge) => {
    expect(chirpDisplay(usable(status))).toEqual({ badge, chartable: true, reason: null });
  });

  it.each([
    ["unusable", "chirp_status_unusable"],
    ["error", "chirp_status_error"],
    ["PASS", "chirp_status_PASS"],
    [undefined, "chirp_status_missing"],
  ])("available=true with status %s is never PASS", (status, reason) => {
    expect(chirpDisplay(usable(status))).toEqual({ badge: "NOT AVAILABLE", chartable: false, reason });
  });

  it("rejected payload -> NOT AVAILABLE with its reason", () => {
    const c: ChirpPayload = { available: false, status: "unusable", reason: "chirp_unusable", magnitude: [], phase: [], coherence: [] };
    expect(chirpDisplay(c)).toEqual({ badge: "NOT AVAILABLE", chartable: false, reason: "chirp_unusable" });
  });

  it("missing payload -> NOT AVAILABLE", () => {
    expect(chirpDisplay(null).badge).toBe("NOT AVAILABLE");
    expect(chirpDisplay(undefined).reason).toBe("no_chirp_payload");
  });

  it.each([
    ["magnitude", "chirp_series_empty"],
    ["phase", "chirp_series_empty"],
    ["coherence", "chirp_series_empty"],
  ] as const)("available=true with empty %s -> NOT AVAILABLE", (key, reason) => {
    const c = { ...usable("ok"), [key]: [] };
    expect(chirpDisplay(c)).toEqual({ badge: "NOT AVAILABLE", chartable: false, reason });
  });

  it("unequal series lengths -> NOT AVAILABLE", () => {
    const c = { ...usable("ok"), phase: series(11).phase };
    expect(chirpDisplay(c).reason).toBe("chirp_series_length_mismatch");
  });
});
