/**
 * Minimal runtime capability boundary for PWA-first GyroCore.
 * Tauri remains a temporary fallback host — not the product architecture.
 */

export type RuntimeMode = "browser" | "tauri";

export type AnalysisCapability =
  | "unavailable" // browser/PWA: native Core not migrated yet
  | "tauri-worker"; // temporary desktop host

export type RuntimeCapabilities = {
  mode: RuntimeMode;
  analysis: AnalysisCapability;
  /** Absolute OS paths usable by the Python worker. */
  nativePaths: boolean;
  /** Browser File objects from <input type="file">. */
  browserFiles: boolean;
};

export function isTauriRuntime(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as Window & {
    __TAURI_INTERNALS__?: unknown;
    __TAURI__?: unknown;
    isTauri?: boolean;
  };
  return Boolean(w.__TAURI_INTERNALS__ || w.__TAURI__ || w.isTauri);
}

export function getRuntimeCapabilities(): RuntimeCapabilities {
  if (isTauriRuntime()) {
    return {
      mode: "tauri",
      analysis: "tauri-worker",
      nativePaths: true,
      browserFiles: true,
    };
  }
  return {
    mode: "browser",
    analysis: "unavailable",
    nativePaths: false,
    browserFiles: true,
  };
}
