import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { bridge } from "@/bridge/client";
import type { WorkspacePayload } from "@/bridge/types";
import { chirpDisplay } from "@/lib/chirpStatus";
import { fixtureFile, multiLogFile, sessionLog } from "@/test/inProcessSession";
import { OpenPage } from "./OpenPage";

const fetchSpy = vi.fn();

vi.mock("@/session/client", async () => ({ BrowserSession: (await import("@/test/inProcessSession")).InProcessSession }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => undefined) }));

const cliFile = () => new File(["# diff all\n# Betaflight / STM32F405 (S405) 4.5.0\nset debug_mode = CHIRP\n"], "tune.txt", { type: "text/plain" });

describe("OpenPage browser file selection", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    delete window.__GYROCORE_WORKER__;
  });

  beforeEach(() => {
    sessionLog.sessions.length = 0;
    sessionLog.holdOpen = null;
    vi.mocked(invoke).mockClear();
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

  async function pick(user: ReturnType<typeof userEvent.setup>, testId: string, file: File) {
    await user.upload(screen.getByTestId(testId), file);
  }

  describe("Begin analysis gating", () => {
    it("neither file -> disabled", () => {
      render(<OpenPage onLoaded={() => undefined} />);
      expect(screen.getByTestId("analyze-btn")).toBeDisabled();
    });

    it("BBL only (decoded) -> disabled", async () => {
      const user = userEvent.setup();
      render(<OpenPage onLoaded={() => undefined} />);
      await pick(user, "bbl-file-input", fixtureFile("clean_single_axis"));
      await waitFor(() => expect(screen.getByTestId("decode-status")).toBeInTheDocument());
      expect(screen.getByTestId("analyze-btn")).toBeDisabled();
      expect(screen.queryByTestId("files-ready")).toBeNull();
    });

    it("CLI only -> disabled", async () => {
      const user = userEvent.setup();
      render(<OpenPage onLoaded={() => undefined} />);
      await pick(user, "cli-file-input", cliFile());
      expect(screen.getByTestId("cli-selected")).toHaveTextContent("tune.txt");
      expect(screen.getByTestId("analyze-btn")).toBeDisabled();
    });

    it("BBL + CLI before decode finishes -> disabled; after decode -> enabled", async () => {
      let release!: () => void;
      sessionLog.holdOpen = new Promise((r) => (release = r));
      const user = userEvent.setup();
      render(<OpenPage onLoaded={() => undefined} />);
      await pick(user, "bbl-file-input", fixtureFile("clean_single_axis"));
      await pick(user, "cli-file-input", cliFile());
      expect(screen.getByTestId("files-ready")).toHaveTextContent(/Waiting for the local Blackbox decode/);
      expect(screen.getByTestId("analyze-btn")).toBeDisabled();
      release();
      sessionLog.holdOpen = null;
      await waitFor(() => expect(screen.getByTestId("analyze-btn")).toBeEnabled());
      expect(screen.getByTestId("files-ready")).toHaveTextContent("Ready for local browser analysis.");
      expect(screen.getByTestId("files-ready")).toHaveTextContent(/nothing is uploaded, no FC connection/);
      expect(screen.getByTestId("files-ready")).not.toHaveTextContent(/stays disabled|backend pending/i);
    });

    it("failed decode -> disabled with the decode error", async () => {
      const user = userEvent.setup();
      render(<OpenPage onLoaded={() => undefined} />);
      await pick(user, "cli-file-input", cliFile());
      await pick(user, "bbl-file-input", new File([new Uint8Array([1, 2, 3])], "bad.bbl"));
      expect(await screen.findByTestId("open-error")).toHaveTextContent("no_embedded_logs");
      expect(screen.getByTestId("analyze-btn")).toBeDisabled();
    });
  });

  async function begin(bbl: File, logIndex?: number): Promise<WorkspacePayload> {
    const user = userEvent.setup();
    const onLoaded = vi.fn();
    render(<OpenPage onLoaded={onLoaded} />);
    await pick(user, "bbl-file-input", bbl);
    await waitFor(() => expect(screen.getByTestId("decode-status")).toBeInTheDocument());
    if (logIndex != null) await user.selectOptions(screen.getByTestId("log-index"), String(logIndex));
    await pick(user, "cli-file-input", cliFile());
    await waitFor(() => expect(screen.getByTestId("analyze-btn")).toBeEnabled());
    await user.click(screen.getByTestId("analyze-btn"));
    await waitFor(() => expect(onLoaded).toHaveBeenCalledTimes(1));
    expect(onLoaded.mock.calls[0]![1]).toBeNull();
    return onLoaded.mock.calls[0]![0] as WorkspacePayload;
  }

  it("Begin analysis creates the browser workspace from the existing decode (no second decode)", async () => {
    const ws = await begin(fixtureFile("clean_single_axis", "Flight.BBL"));
    expect(ws.kind).toBe("gyrocore_browser_workspace");
    expect(ws.demo).toBe(false);
    expect(ws.overview).toMatchObject({ bbl_filename: "Flight.BBL", cli_filename: "tune.txt", log_index: 0, log_count: 1 });
    expect(ws.blackbox).toMatchObject({ source: "browser", filename: "Flight.BBL", selected_log_index: 0 });
    expect((ws.blackbox.fields_hint as string[]).length).toBeGreaterThan(5);
    expect(ws.chirp).toMatchObject({ available: true, status: "ok" });
    expect(ws.cli.firmware_provenance).toMatchObject({ filename: "tune.txt", firmware: "Betaflight / STM32F405 (S405) 4.5.0" });
    expect([ws.analysis, ws.tune, ws.safety, ws.compare]).toEqual([null, null, null, null]);
    expect(ws.capabilities).toMatchObject({ blackboxDecode: "available", chirpAnalysis: "available", tune: "unavailable", safety: "unavailable", cliApply: "unavailable", generalAnalysis: "unavailable", compare: "unavailable" });
    expect(sessionLog.sessions).toHaveLength(1);
    expect(sessionLog.sessions[0]!.core.flightLogBuilds()).toBe(1);
  });

  it("multi-log: recommended log is the default, manual selection wins and is preserved everywhere", async () => {
    const ws = await begin(multiLogFile(["clean_single_axis", "three_axis_sequence", "poor_coherence"]), 2);
    expect(sessionLog.sessions[0]!.analyzed).toEqual([2]);
    expect(ws.overview).toMatchObject({ log_index: 2, log_count: 3 });
    expect(ws.blackbox).toMatchObject({ selected_log_index: 2, log_count: 3 });
    expect(ws.scenario).toBe("browser · log 3/3");
    expect(ws.chirp).toMatchObject({ available: false, reason: "chirp_unusable" });
    const flights = ws.blackbox.flights as Array<{ index: number; durationUs: number }>;
    expect(ws.overview.log_duration_s).toBe(Number((flights[2]!.durationUs / 1e6).toFixed(2)));
    expect(sessionLog.sessions[0]!.core.flightLogBuilds()).toBe(1);
  });

  it.each([
    ["clean_single_axis", "PASS", null],
    ["repeated_axis", "WARN", null],
    ["poor_coherence", "NOT AVAILABLE", "chirp_unusable"],
    ["mode_events", "NOT AVAILABLE", "not_chirp_debug_mode"],
  ])("%s: workspace opens with CHIRP %s", async (name, badge, reason) => {
    const ws = await begin(fixtureFile(name));
    expect(ws.kind).toBe("gyrocore_browser_workspace");
    expect(chirpDisplay(ws.chirp)).toMatchObject({ badge, ...(reason ? { reason } : {}) });
  });

  it("browser Begin never calls Tauri, the bridge, demo fixtures or the network", async () => {
    const analyze = vi.spyOn(bridge, "analyze");
    const loadDemo = vi.spyOn(bridge, "loadDemo");
    await begin(fixtureFile("clean_single_axis"));
    expect(vi.mocked(invoke)).not.toHaveBeenCalled();
    expect(analyze).not.toHaveBeenCalled();
    expect(loadDemo).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
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
    // Replacing and removing the BBL releases its session (bytes leave worker memory).
    expect(sessionLog.sessions).toHaveLength(2);
    expect(sessionLog.sessions.every((x) => x.disposed)).toBe(true);
  });
});
