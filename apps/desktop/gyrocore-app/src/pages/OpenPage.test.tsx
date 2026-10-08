import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { analyzeChirpFile } from "@/chirp/client";
import { decodeBlackboxFile } from "@/decode/client";
import { OpenPage } from "./OpenPage";

const fetchSpy = vi.fn();

vi.mock("@/decode/client", () => ({
  decodeBlackboxFile: vi.fn(async (file: File) => ({
    timingsMs: { total: 1 },
    result: {
      schemaVersion: 1,
      source: {
        filename: file.name,
        sizeBytes: file.size,
        decoder: "betaflight-flightlog-js",
        licenseNote: "GPL-3.0 (vendored Betaflight blackbox-log-viewer)",
      },
      embedded: {
        logCount: 2,
        selectedIndex: 1,
        recommendedIndex: 1,
        flights: [
          {
            index: 0,
            label: "log 0",
            startTimeUs: 0,
            endTimeUs: 1000,
            durationUs: 1000,
            sampleCount: 0,
          },
          {
            index: 1,
            label: "log 1",
            startTimeUs: 0,
            endTimeUs: 5000,
            durationUs: 5000,
            sampleCount: 0,
          },
        ],
      },
      metadata: {
        firmwareType: "Betaflight",
        firmwareVersion: "4.5.0",
        fieldNames: ["time", "gyroADC[0]"],
      },
      timeUs: new Float64Array(0),
      series: {},
    },
  })),
}));

vi.mock("@/chirp/client", () => ({
  analyzeChirpFile: vi.fn(async (file: File) => ({
    schemaVersion: 1,
    engine: "gyrocore-browser-chirp",
    result: {
      status: "unusable",
      usable: false,
      detected: false,
      analysis_only: true,
      tuning_recommendations: null,
      sysconfig: null,
      extraction: null,
      axes: {},
      warnings: ["no_chirp_segments_detected"],
      errors: ["no_chirp_segments"],
      provenance: {},
    },
    rejection: { code: "no_chirp_segments", detail: "No CHIRP-active segment in the selected log." },
    source: {
      filename: file.name,
      sizeBytes: file.size,
      logIndex: 1,
      logCount: 2,
      decoder: "betaflight-flightlog-js",
      framesDecoded: 10,
      inputPolicy: "full_frame",
    },
    timingsMs: { total: 1 },
  })),
}));

describe("OpenPage browser file selection", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    delete window.__GYROCORE_WORKER__;
  });

  beforeEach(() => {
    fetchSpy.mockReset();
    vi.stubGlobal("fetch", fetchSpy);
    window.__GYROCORE_WORKER__ = async <T,>(op: string) => {
      if (op === "list_demos") {
        return { scenarios: ["pass"] } as T;
      }
      throw new Error(`unexpected_op:${op}`);
    };
  });

  it("starts in browser mode with choosers and disabled analyze", () => {
    render(<OpenPage onLoaded={() => undefined} />);
    expect(screen.getByTestId("open-page")).toHaveAttribute("data-runtime", "browser");
    expect(screen.getByTestId("choose-bbl")).toBeInTheDocument();
    expect(screen.getByTestId("choose-cli")).toBeInTheDocument();
    expect(screen.getByTestId("analyze-btn")).toBeDisabled();
    expect(screen.queryByTestId("log-path")).toBeNull();
  });

  it("selects BBL and CLI without network upload", async () => {
    const user = userEvent.setup();
    render(<OpenPage onLoaded={() => undefined} />);

    const bbl = new File([new Uint8Array([1, 2, 3])], "Flight.BBL", { type: "application/octet-stream" });
    const cli = new File(["# dump"], "tune.TXT", { type: "text/plain" });

    await user.upload(screen.getByTestId("bbl-file-input"), bbl);
    expect(screen.getByTestId("bbl-selected")).toHaveTextContent("Flight.BBL");
    await waitFor(() => expect(screen.getByTestId("decode-status")).toBeInTheDocument());
    expect(screen.getByTestId("decode-status")).toHaveTextContent(/analysis migration not yet complete/i);
    expect(screen.getByTestId("log-index")).toBeInTheDocument();
    expect(screen.getByTestId("analyze-btn")).toBeDisabled(); // CLI required
    expect(vi.mocked(decodeBlackboxFile)).toHaveBeenCalled();

    await user.upload(screen.getByTestId("cli-file-input"), cli);
    expect(screen.getByTestId("cli-selected")).toHaveTextContent("tune.TXT");
    expect(screen.getByTestId("files-ready")).toBeInTheDocument();
    expect(screen.getByTestId("analyze-btn")).toBeEnabled(); // browser CHIRP analysis
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("runs browser CHIRP analysis locally and loads a CHIRP-only workspace", async () => {
    const user = userEvent.setup();
    const onLoaded = vi.fn();
    render(<OpenPage onLoaded={onLoaded} />);
    await user.upload(
      screen.getByTestId("bbl-file-input"),
      new File([new Uint8Array([1, 2])], "Flight.BBL", { type: "application/octet-stream" }),
    );
    await waitFor(() => expect(screen.getByTestId("decode-status")).toBeInTheDocument());
    await user.upload(screen.getByTestId("cli-file-input"), new File(["# dump"], "tune.txt", { type: "text/plain" }));
    await user.click(screen.getByTestId("analyze-btn"));
    await waitFor(() => expect(onLoaded).toHaveBeenCalled());
    expect(vi.mocked(analyzeChirpFile)).toHaveBeenCalledWith(expect.any(File), { logIndex: 1 });
    const ws = onLoaded.mock.calls[0]![0];
    expect(ws.kind).toBe("gyrocore_browser_workspace");
    expect(ws.chirp).toMatchObject({ available: false, reason: "no_chirp_segments", magnitude: [] });
    expect(ws.tune).toBeNull();
    expect(ws.safety).toBeNull();
    expect(ws.cli).toMatchObject({ authorized: false, actionable: false });
    expect(ws.overview.final_safety).toBeUndefined();
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("keeps analyze disabled when only CLI is missing after decode", async () => {
    const user = userEvent.setup();
    render(<OpenPage onLoaded={() => undefined} />);
    await user.upload(
      screen.getByTestId("bbl-file-input"),
      new File([new Uint8Array([1])], "only.bbl", { type: "application/octet-stream" }),
    );
    await waitFor(() => expect(screen.getByTestId("decode-status")).toBeInTheDocument());
    expect(screen.getByTestId("analyze-btn")).toBeDisabled();
    expect(screen.queryByTestId("files-ready")).toBeNull();
  });

  it("rejects unsupported extensions case-insensitively messaging", async () => {
    render(<OpenPage onLoaded={() => undefined} />);
    const bad = new File([""], "notes.md", { type: "text/plain" });
    const input = screen.getByTestId("bbl-file-input") as HTMLInputElement;
    const files = {
      0: bad,
      length: 1,
      item: (i: number) => (i === 0 ? bad : null),
      *[Symbol.iterator]() {
        yield bad;
      },
    } as unknown as FileList;
    Object.defineProperty(input, "files", { configurable: true, value: files });
    fireEvent.change(input);
    expect(await screen.findByTestId("open-error")).toHaveTextContent(/Unsupported Blackbox/i);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("supports replace and remove without exposing OS paths", async () => {
    const user = userEvent.setup();
    render(<OpenPage onLoaded={() => undefined} />);
    await user.upload(
      screen.getByTestId("bbl-file-input"),
      new File([new Uint8Array([9])], "a.bbl", { type: "application/octet-stream" }),
    );
    expect(screen.getByTestId("bbl-selected").textContent).not.toMatch(/^\/|^[A-Za-z]:\\/);
    await user.upload(
      screen.getByTestId("bbl-file-input"),
      new File([new Uint8Array([8, 8])], "b.bfl", { type: "application/octet-stream" }),
    );
    expect(screen.getByTestId("bbl-selected")).toHaveTextContent("b.bfl");
    await user.click(screen.getByTestId("remove-bbl"));
    await waitFor(() => expect(screen.getByTestId("choose-bbl")).toBeInTheDocument());
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});
