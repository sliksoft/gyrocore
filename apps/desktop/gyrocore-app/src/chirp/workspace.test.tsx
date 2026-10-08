import { cleanup, render, screen } from "@testing-library/react";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { gunzipSync } from "node:zlib";
import { afterEach, describe, expect, it } from "vitest";
import type { WorkspacePayload } from "@/bridge/types";
import { chirpDisplay } from "@/lib/chirpStatus";
import { ChirpPage } from "@/pages/ChirpPage";
import { OverviewPage } from "@/pages/OverviewPage";
import { getRuntimeCapabilities } from "@/runtime/capabilities";
import { createSessionCore } from "@/session/sessionCore";
import { runChirpOnBytes } from "./runChirp";
import { browserWorkspace, chirpPayloadFromAnalysis, cliContextFromText } from "./workspace";

// jsdom env: import.meta.url is not a file: URL, resolve from the module directory.
const WU7 = join(__dirname, "../../../../../tests/fixtures/chirp/wu7/bbl/");
const analyze = (name: string) =>
  runChirpOnBytes(new Uint8Array(gunzipSync(readFileSync(WU7 + name + ".bbl.gz"))), { filename: `${name}.bbl` });

const CLI_TEXT = "# diff all\n# version\n# Betaflight / STM32G47X (S47X) 2026.6.2 Oct  1 2026\nboard_name BETAFPVG473\nset debug_mode = CHIRP\n";

/** Workspace exactly as the Open page builds it: one session decode, then analyse. */
function workspace(name: string): WorkspacePayload {
  const bytes = new Uint8Array(gunzipSync(readFileSync(WU7 + name + ".bbl.gz")));
  const core = createSessionCore();
  const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
  core.handle({ id: 1, type: "open", buffer, filename: `${name}.bbl` });
  const r = core.handle({ id: 2, type: "analyze", logIndex: 0 }).response;
  if (!r.ok || r.type !== "analyze") throw new Error(r.ok ? "protocol" : r.error);
  return browserWorkspace({
    decoded: r.decoded,
    analysis: r.analysis,
    bbl: { name: `${name}.bbl`, sizeBytes: bytes.byteLength },
    cli: cliContextFromText("cli.txt", CLI_TEXT.length, CLI_TEXT),
    features: getRuntimeCapabilities().features,
  });
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
    expect(ws.cli).toMatchObject({ state: "NOT AVAILABLE", authorized: false, actionable: false });
    expect(ws.cli.apply_cli).toBeUndefined();
    expect(ws.cli.rollback_cli).toBeUndefined();
    expect(Object.values(ws.controls).every((v) => v === false)).toBe(true);
    expect(ws.overview.chirp_detected).toBe(true);
    expect(ws.overview.final_safety).toBeUndefined();
    expect(ws.demo).toBe(false);
  });

  it("browser workspace carries the real decode, files, log and CLI context", () => {
    const ws = workspace("clean_single_axis");
    expect(ws.overview).toMatchObject({ bbl_filename: "clean_single_axis.bbl", cli_filename: "cli.txt", log_index: 0, log_count: 1 });
    expect(ws.blackbox).toMatchObject({ source: "browser", filename: "clean_single_axis.bbl", selected_log_index: 0, log_count: 1 });
    expect((ws.blackbox.fields_hint as string[]).length).toBeGreaterThan(5);
    expect(ws.blackbox.frames_decoded).toBeGreaterThan(2000);
    expect(ws.cli.firmware_provenance).toEqual({
      filename: "cli.txt",
      size_bytes: CLI_TEXT.length,
      lines: 5,
      firmware: "Betaflight / STM32G47X (S47X) 2026.6.2 Oct  1 2026",
      board_name: "BETAFPVG473",
      debug_mode: "CHIRP",
    });
    expect(ws.capabilities).toEqual({
      blackboxDecode: "available",
      cliSelection: "available",
      chirpAnalysis: "available",
      generalAnalysis: "unavailable",
      tune: "unavailable",
      safety: "unavailable",
      compare: "unavailable",
      cliApply: "unavailable",
    });
  });

  it("refuses a workspace whose decode and CHIRP refer to different logs", () => {
    const bytes = new Uint8Array(gunzipSync(readFileSync(WU7 + "clean_single_axis.bbl.gz")));
    const core = createSessionCore();
    core.handle({ id: 1, type: "open", buffer: bytes.buffer as ArrayBuffer, filename: "x.bbl" });
    const r = core.handle({ id: 2, type: "analyze", logIndex: 0 }).response;
    if (!r.ok || r.type !== "analyze") throw new Error("protocol");
    const decoded = { ...r.decoded, embedded: { ...r.decoded.embedded, selectedIndex: 1 } };
    expect(() =>
      browserWorkspace({
        decoded,
        analysis: r.analysis,
        bbl: { name: "x.bbl", sizeBytes: 1 },
        cli: cliContextFromText("cli.txt", 0, ""),
        features: getRuntimeCapabilities().features,
      }),
    ).toThrow("workspace_log_mismatch");
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
