import { cleanup, render, screen } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gunzipSync } from "node:zlib";
import { afterEach, describe, expect, it } from "vitest";
import type { WorkspacePayload } from "@/bridge/types";
import { chirpDisplay } from "@/lib/chirpStatus";
import { ChirpPage } from "@/pages/ChirpPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { runChirpOnBytes } from "./runChirp";
import { browserChirpWorkspace, chirpPayloadFromAnalysis } from "./workspace";

// jsdom env: import.meta.url is not a file: URL, resolve from the module directory.
const WU7 = join(__dirname, "../../../../../tests/fixtures/chirp/wu7/bbl/");
const analyze = (name: string) =>
  runChirpOnBytes(new Uint8Array(gunzipSync(readFileSync(WU7 + name + ".bbl.gz"))), { filename: `${name}.bbl` });

function workspace(name: string): WorkspacePayload {
  return browserChirpWorkspace({ analysis: analyze(name), decoded: null, bblName: `${name}.bbl`, cliName: "cli.txt" });
}

afterEach(cleanup);

describe("browser CHIRP -> UI payload", () => {
  it("valid CHIRP: available with non-empty, aligned series over the analysis band", () => {
    const c = chirpPayloadFromAnalysis(analyze("clean_single_axis"));
    expect(c.available).toBe(true);
    expect(c.status).toBe("ok");
    expect(c.axis).toBe("roll");
    expect(c.sample_rate_hz).toBe(1000);
    expect(c.magnitude.length).toBeGreaterThan(8);
    expect(c.phase.length).toBe(c.magnitude.length);
    expect(c.coherence.length).toBe(c.magnitude.length);
    expect(c.magnitude[0]!.hz).toBeGreaterThanOrEqual(2);
    expect(c.magnitude.at(-1)!.hz).toBeLessThanOrEqual(200);
    expect(c.usable_frequency_hz).toMatchObject({ min: expect.any(Number), max: expect.any(Number) });
  });

  it.each([
    ["malformed_wrong_debug_mode", "not_chirp_debug_mode"],
    ["weak_excitation", "chirp_unusable"],
    ["poor_coherence", "chirp_unusable"],
    ["insufficient_samples", "chirp_unusable"],
  ])("%s: explicit rejection, no series, never available", (name, code) => {
    const c = chirpPayloadFromAnalysis(analyze(name));
    expect(c).toMatchObject({ available: false, reason: code, magnitude: [], phase: [], coherence: [] });
    expect(c.warnings!.length).toBeGreaterThan(0);
  });

  it("browser workspace never claims Tune / Safety / CLI", () => {
    const ws = workspace("clean_single_axis");
    expect(ws.tune).toBeNull();
    expect(ws.safety).toBeNull();
    expect(ws.compare).toBeNull();
    expect(ws.analysis).toBeNull();
    expect(ws.cli).toMatchObject({ authorized: false, actionable: false });
    expect(Object.values(ws.controls).every((v) => v === false)).toBe(true);
    expect(ws.overview.chirp_detected).toBe(true);
    expect(ws.overview.final_safety).toBeUndefined();
  });
});

describe("ChirpPage with browser results", () => {
  it("valid CHIRP renders charts and the status badge", () => {
    render(<ChirpPage ws={workspace("clean_single_axis")} />);
    expect(screen.getByTestId("chirp-available")).toBeInTheDocument();
    expect(screen.getByText("Magnitude")).toBeInTheDocument();
    expect(screen.getByText("PASS")).toBeInTheDocument();
  });

  it("usable_with_warnings shows WARN, not PASS", () => {
    render(<ChirpPage ws={workspace("repeated_axis")} />);
    expect(screen.getByTestId("chirp-available")).toBeInTheDocument();
    expect(screen.getByText("WARN")).toBeInTheDocument();
    expect(screen.queryByText("PASS")).toBeNull();
  });

  it("rejection explains itself with no charts", () => {
    render(<ChirpPage ws={workspace("poor_coherence")} />);
    expect(screen.getByTestId("chirp-unavailable")).toBeInTheDocument();
    expect(screen.getByText("chirp_unusable")).toBeInTheDocument();
    expect(screen.queryByText("Magnitude")).toBeNull();
  });

  it("available=true with empty arrays is shown as unavailable (no false PASS)", () => {
    const ws = workspace("clean_single_axis");
    ws.chirp = { ...ws.chirp!, available: true, magnitude: [], phase: [], coherence: [] };
    render(<ChirpPage ws={ws} />);
    expect(screen.getByTestId("chirp-unavailable")).toBeInTheDocument();
    expect(screen.getByText("chirp_series_empty")).toBeInTheDocument();
    expect(screen.queryByText("PASS")).toBeNull();
  });
});

describe("one CHIRP status everywhere (Overview == CHIRP page)", () => {
  const overviewChirpBadge = (ws: WorkspacePayload) => {
    const { container } = render(<OverviewPage ws={ws} />);
    const dt = [...container.querySelectorAll("dt")].find((el) => el.textContent === "CHIRP");
    const text = dt?.nextElementSibling?.textContent?.trim();
    cleanup();
    return text;
  };
  const chirpPageBadge = (ws: WorkspacePayload) => {
    render(<ChirpPage ws={ws} />);
    const badge = ["PASS", "WARN", "NOT AVAILABLE"].find((b) => screen.queryByText(b));
    cleanup();
    return badge;
  };
  const fixtures = readdirSync(WU7)
    .filter((f) => f.endsWith(".bbl.gz"))
    .map((f) => f.replace(".bbl.gz", ""));

  it.each(fixtures)("%s", (name) => {
    const ws = workspace(name);
    const expected = { ok: "PASS", usable_with_warnings: "WARN" }[ws.chirp?.available ? ws.chirp.status! : ""] ?? "NOT AVAILABLE";
    expect(chirpDisplay(ws.chirp).badge).toBe(expected);
    expect(chirpPageBadge(ws)).toBe(expected);
    expect(overviewChirpBadge(ws)).toBe(expected);
  });

  it("usable_with_warnings is WARN on the Overview too (was PASS)", () => {
    expect(overviewChirpBadge(workspace("repeated_axis"))).toBe("WARN");
  });

  it("available=true with empty arrays is NOT AVAILABLE on the Overview too", () => {
    const ws = workspace("clean_single_axis");
    ws.chirp = { ...ws.chirp!, magnitude: [], phase: [], coherence: [] };
    expect(overviewChirpBadge(ws)).toBe("NOT AVAILABLE");
  });
});
