import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import App from "./App";
import { multiLogFile, sessionLog } from "@/test/inProcessSession";

vi.mock("@/session/client", async () => ({ BrowserSession: (await import("@/test/inProcessSession")).InProcessSession }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(async () => undefined) }));

const fetchSpy = vi.fn();

describe("browser workspace inside the app shell", () => {
  beforeEach(() => {
    sessionLog.sessions.length = 0;
    fetchSpy.mockReset();
    vi.stubGlobal("fetch", fetchSpy);
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("Begin analysis opens a real workspace that survives Overview -> Blackbox -> CHIRP -> CLI navigation", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.upload(screen.getByTestId("bbl-file-input"), multiLogFile(["clean_single_axis", "three_axis_sequence", "poor_coherence"]));
    await waitFor(() => expect(screen.getByTestId("decode-status")).toBeInTheDocument());
    await user.selectOptions(screen.getByTestId("log-index"), "1");
    await user.upload(screen.getByTestId("cli-file-input"), new File(["# Betaflight / STM32F405 (S405) 4.5.0\n"], "tune.txt"));
    await waitFor(() => expect(screen.getByTestId("analyze-btn")).toBeEnabled());
    await user.click(screen.getByTestId("analyze-btn"));

    // Overview: real files, log, decode, CHIRP status.
    const overview = await screen.findByText("BBL");
    const main = overview.closest("main")!;
    const kv = (label: string) => within(main).getByText(label, { selector: "dt" }).nextElementSibling?.textContent;
    expect(kv("BBL")).toBe("multi.bbl");
    expect(kv("CLI")).toBe("tune.txt");
    expect(kv("Log index")).toBe("1 of 3");
    expect(kv("Decode")).toMatch(/^decoded in browser · \d+ frames$/);
    expect(kv("CHIRP")).toBe("PASS");
    expect(kv("Final safety")).toBe("NOT AVAILABLE");

    for (let round = 0; round < 2; round++) {
      await user.click(screen.getByTestId("nav-blackbox"));
      const bb = await screen.findByTestId("blackbox-browser");
      expect(within(bb).getByText("multi.bbl")).toBeInTheDocument();
      expect(within(bb).getByText("1 of 3")).toBeInTheDocument();
      expect(within(screen.getByTestId("blackbox-flights")).getByText(/^▶ 1: /)).toBeInTheDocument();
      expect(screen.queryByTestId("viewer-frame")).toBeNull(); // no localhost viewer host

      await user.click(screen.getByTestId("nav-chirp"));
      const chirp = await screen.findByTestId("chirp-available");
      expect(within(chirp).getByText("PASS", { exact: true })).toBeInTheDocument();
      for (const label of ["Magnitude", "Phase", "Coherence"]) expect(within(chirp).getByRole("img", { name: label })).toBeInTheDocument();

      await user.click(screen.getByTestId("nav-cli"));
      const cli = await screen.findByTestId("cli-page");
      expect(within(cli).getAllByText("NOT AVAILABLE").length).toBeGreaterThan(0);
      expect(within(cli).getByText(/tune\.txt/)).toBeInTheDocument();
      expect(screen.queryByTestId("apply-cli-panel")).toBeNull();
      expect(screen.queryByTestId("copy-apply")).toBeNull();

      await user.click(screen.getByTestId("nav-overview"));
      expect(await screen.findByText("1 of 3")).toBeInTheDocument();
    }

    for (const [nav, testId] of [
      ["nav-tune", "tune-unavailable"],
      ["nav-safety", "safety-unavailable"],
      ["nav-analysis", "analysis-unavailable"],
      ["nav-compare", "compare-unavailable"],
    ] as const) {
      await user.click(screen.getByTestId(nav));
      const empty = await screen.findByTestId(testId);
      expect(empty).toHaveTextContent(/not available in the browser yet/i);
      expect(within(empty.parentElement!).getByText("NOT AVAILABLE")).toBeInTheDocument(); // header badge of the same card
    }

    expect(sessionLog.sessions).toHaveLength(1);
    expect(sessionLog.sessions[0]!.core.flightLogBuilds()).toBe(1);
    expect(sessionLog.sessions[0]!.analyzed).toEqual([1]);
    expect(vi.mocked(invoke)).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled(); // no demo fixture fallback, no upload
  });
});
