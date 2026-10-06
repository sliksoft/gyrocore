import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import passFixture from "./test/fixtures/pass.json";
import warnFixture from "./test/fixtures/warn.json";
import blockFixture from "./test/fixtures/block.json";
import noChirpFixture from "./test/fixtures/no_chirp.json";
import mergeFixture from "./test/fixtures/merge_review.json";
import noAutotuneFixture from "./test/fixtures/no_autotune.json";

const fixtures: Record<string, unknown> = {
  pass: passFixture,
  warn: warnFixture,
  block: blockFixture,
  no_chirp: noChirpFixture,
  merge_review: mergeFixture,
  no_autotune: noAutotuneFixture,
};

function demoBtn(id: string) {
  const buttons = screen.getAllByTestId(`demo-${id}`);
  return buttons[0];
}

describe("GyroCore desktop shell", () => {
  afterEach(() => {
    cleanup();
    delete window.__GYROCORE_WORKER__;
  });

  beforeEach(() => {
    window.__GYROCORE_WORKER__ = async <T,>(op: string, params: Record<string, unknown> = {}) => {
      if (op === "ping") return { pong: true } as T;
      if (op === "list_demos") return { scenarios: Object.keys(fixtures) } as T;
      if (op === "demo") {
        const scenario = String(params.scenario || "pass");
        return (fixtures[scenario] || fixtures.pass) as T;
      }
      throw new Error(`unexpected_op:${op}`);
    };
  });

  it("starts and shows open screen", () => {
    render(<App />);
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByTestId("analyze-btn")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Open Blackbox Log/i })).toBeInTheDocument();
  });

  it("loads demo fixture and renders overview + blackbox", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(demoBtn("pass"));
    await waitFor(() => expect(screen.getByText(/Craft \/ firmware/i)).toBeInTheDocument());
    await user.click(screen.getByTestId("nav-blackbox"));
    expect(screen.getByTestId("viewer-frame")).toBeInTheDocument();
    expect(screen.getByText(/blackbox-log-viewer/i)).toBeInTheDocument();
  });

  it("shows WU13 diagnostics summaries for pass demo", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(demoBtn("pass"));
    await user.click(screen.getByTestId("nav-diagnostics"));
    expect(await screen.findByTestId("diagnostics-page")).toBeInTheDocument();
    expect(screen.getByTestId("diag-filter")).toBeInTheDocument();
    expect(screen.getByTestId("diag-throttle")).toBeInTheDocument();
    expect(screen.getByTestId("diag-verification")).toBeInTheDocument();
    expect(screen.getByText(/Actionable:/i)).toBeInTheDocument();
  });

  it("shows CHIRP available graphs for pass demo", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(demoBtn("pass"));
    await user.click(screen.getByTestId("nav-chirp"));
    expect(await screen.findByTestId("chirp-available")).toBeInTheDocument();
    expect(screen.getByText("Magnitude")).toBeInTheDocument();
    expect(screen.getByText("Phase")).toBeInTheDocument();
    expect(screen.getByText("Coherence")).toBeInTheDocument();
  });

  it("shows CHIRP unavailable cleanly", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(demoBtn("no_chirp"));
    await user.click(screen.getByTestId("nav-chirp"));
    expect(await screen.findByTestId("chirp-unavailable")).toBeInTheDocument();
  });

  it("renders tune stages separately", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(demoBtn("pass"));
    await user.click(screen.getByTestId("nav-tune"));
    expect(await screen.findByText("CURRENT")).toBeInTheDocument();
    expect(screen.getByText("WU9 ABSOLUTE PROPOSAL")).toBeInTheDocument();
    expect(screen.getByText("WU10 SAFE / CLAMPED TARGET")).toBeInTheDocument();
  });

  it("safety PASS / WARN / BLOCK", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(demoBtn("pass"));
    await user.click(screen.getByTestId("nav-safety"));
    expect(await screen.findByTestId("safety-page")).toBeInTheDocument();

    await user.click(screen.getByTestId("nav-open"));
    await user.click(demoBtn("warn"));
    await user.click(screen.getByTestId("nav-safety"));
    expect(await screen.findByTestId("safety-page")).toBeInTheDocument();

    await user.click(screen.getByTestId("nav-open"));
    await user.click(demoBtn("block"));
    await user.click(screen.getByTestId("nav-safety"));
    expect(await screen.findByTestId("safety-page")).toBeInTheDocument();
  });

  it("authorized CLI only for PASS; WARN preview; BLOCK none", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(demoBtn("pass"));
    await user.click(screen.getByTestId("nav-cli"));
    expect(await screen.findByTestId("apply-cli-panel")).toBeInTheDocument();
    expect(screen.getByTestId("rollback-cli-panel")).toBeInTheDocument();
    expect(screen.getByTestId("no-fc-apply")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Apply to FC$/i })).toBeNull();

    await user.click(screen.getByTestId("nav-open"));
    await user.click(demoBtn("warn"));
    await user.click(screen.getByTestId("nav-cli"));
    expect(await screen.findByTestId("preview-cli-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("apply-cli-panel")).toBeNull();

    await user.click(screen.getByTestId("nav-open"));
    await user.click(demoBtn("block"));
    await user.click(screen.getByTestId("nav-cli"));
    expect(await screen.findByTestId("denied-cli-panel")).toBeInTheDocument();
    expect(screen.queryByTestId("apply-cli-panel")).toBeNull();
  });

  it("copy buttons call clipboard with WU11 text only", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", {
      ...navigator,
      clipboard: { writeText },
    });
    render(<App />);
    await user.click(demoBtn("pass"));
    await user.click(screen.getByTestId("nav-cli"));
    const cli = await screen.findByTestId("cli-page");
    await user.click(within(cli).getByTestId("copy-apply"));
    expect(writeText).toHaveBeenCalled();
    expect(writeText.mock.calls[0][0]).toBe((passFixture as { cli: { apply_cli: string } }).cli.apply_cli);
    await user.click(within(cli).getByTestId("copy-rollback"));
    expect(writeText.mock.calls[1][0]).toBe((passFixture as { cli: { rollback_cli: string } }).cli.rollback_cli);
    vi.unstubAllGlobals();
  });

  it("analysis page renders", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(demoBtn("pass"));
    await user.click(screen.getByTestId("nav-analysis"));
    expect(await screen.findByText(/FFT \/ spectral/i)).toBeInTheDocument();
  });

  it("compare page renders deltas", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(demoBtn("pass"));
    await user.click(screen.getByTestId("nav-compare"));
    expect(await screen.findByText(/Current vs Final Safe Target/i)).toBeInTheDocument();
  });

  it("shows error state on open failure", async () => {
    window.__GYROCORE_WORKER__ = async () => {
      throw new Error("invalid file");
    };
    const user = userEvent.setup();
    render(<App />);
    await user.click(demoBtn("pass"));
    expect(await screen.findByTestId("open-error")).toHaveTextContent(/invalid file/i);
  });
});
