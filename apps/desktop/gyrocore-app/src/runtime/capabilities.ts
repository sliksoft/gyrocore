/**
 * Minimal runtime capability boundary for PWA-first GyroCore.
 * Tauri remains a temporary fallback host — not the product architecture.
 */

export type RuntimeMode = "browser" | "tauri";

export type AnalysisCapability =
  | "unavailable" // browser/PWA: native Core not migrated yet
  | "tauri-worker"; // temporary desktop host

/**
 * Per-feature availability. `analysis` above stays the general Tune/Safety
 * pipeline; browser features are listed individually so a migrated piece
 * (CHIRP) never implies the whole analysis is complete.
 */
export type FeatureCapabilities = {
  blackboxDecode: "browser-worker" | "tauri-worker";
  cliSelection: "browser-file" | "native-path";
  /** CHIRP / system-ID analysis; results still carry their own validity state. */
  chirpAnalysis: "browser-worker" | "tauri-worker";
  /** Final Tune / PID / Safety generation — NOT migrated to the browser. */
  tuneSafety: "unavailable" | "tauri-worker";
};

export type RuntimeCapabilities = {
  mode: RuntimeMode;
  analysis: AnalysisCapability;
  features: FeatureCapabilities;
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
      features: {
        blackboxDecode: "tauri-worker",
        cliSelection: "native-path",
        chirpAnalysis: "tauri-worker",
        tuneSafety: "tauri-worker",
      },
      nativePaths: true,
      browserFiles: true,
    };
  }
  return {
    mode: "browser",
    analysis: "unavailable",
    features: {
      blackboxDecode: "browser-worker",
      cliSelection: "browser-file",
      chirpAnalysis: "browser-worker",
      tuneSafety: "unavailable",
    },
    nativePaths: false,
    browserFiles: true,
  };
}
