import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OpenPage } from "./OpenPage";

const fetchSpy = vi.fn();

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
    expect(screen.getByTestId("analyze-btn")).toBeDisabled(); // CLI required

    await user.upload(screen.getByTestId("cli-file-input"), cli);
    expect(screen.getByTestId("cli-selected")).toHaveTextContent("tune.TXT");
    expect(screen.getByTestId("files-ready")).toBeInTheDocument();
    expect(screen.getByTestId("analyze-btn")).toBeDisabled(); // analysis unavailable
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
  });
});
