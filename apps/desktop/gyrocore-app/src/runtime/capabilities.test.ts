import { afterEach, describe, expect, it } from "vitest";
import { getRuntimeCapabilities, isTauriRuntime } from "./capabilities";

describe("runtime capabilities", () => {
  afterEach(() => {
    delete (window as { __TAURI__?: unknown }).__TAURI__;
    delete (window as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
  });

  it("detects browser mode without Tauri", () => {
    expect(isTauriRuntime()).toBe(false);
    const caps = getRuntimeCapabilities();
    expect(caps.mode).toBe("browser");
    expect(caps.analysis).toBe("unavailable");
    expect(caps.nativePaths).toBe(false);
    expect(caps.browserFiles).toBe(true);
  });

  it("detects tauri mode when internals exist", () => {
    (window as { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
    expect(isTauriRuntime()).toBe(true);
    const caps = getRuntimeCapabilities();
    expect(caps.mode).toBe("tauri");
    expect(caps.analysis).toBe("tauri-worker");
    expect(caps.nativePaths).toBe(true);
  });
});
