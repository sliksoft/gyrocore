/**
 * Minimal runtime capability boundary for PWA-first GyroCore.
 * Tauri remains a temporary fallback host — not the product architecture.
 */

export type RuntimeMode = "browser" | "tauri";

export type AnalysisCapability =
  | "unavailable" // browser/PWA: native Core not migrated yet
  | "tauri-worker"; // temporary desktop host

/**
 * Per-feature availability. `analysis` above stays the general Python-Core
 * pipeline; browser features are listed individually so a migrated piece
 * (decode, CHIRP) never implies the whole analysis is complete.
 */
export type FeatureCapabilities = {
  blackboxDecode: "browser-worker" | "tauri-worker";
  cliSelection: "browser-file" | "native-path";
  /** CHIRP / system-ID analysis; results still carry their own validity state. */
  chirpAnalysis: "browser-worker" | "tauri-worker";
  /** Resonance / noise / quality analysis — NOT migrated to the browser. */
  generalAnalysis: "unavailable" | "tauri-worker";
  /** PID / filter tune generation — NOT migrated to the browser. */
  tune: "unavailable" | "tauri-worker";
  /** Mechanical / tuning-output safety verdict — NOT migrated to the browser. */
  safety: "unavailable" | "tauri-worker";
  /** Current vs safe-target compare (needs Tune + Safety). */
  compare: "unavailable" | "tauri-worker";
  /** Authorized apply / rollback CLI generation. */
  cliApply: "unavailable" | "tauri-worker";
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
        generalAnalysis: "tauri-worker",
        tune: "tauri-worker",
        safety: "tauri-worker",
        compare: "tauri-worker",
        cliApply: "tauri-worker",
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
      generalAnalysis: "unavailable",
      tune: "unavailable",
      safety: "unavailable",
      compare: "unavailable",
      cliApply: "unavailable",
    },
    nativePaths: false,
    browserFiles: true,
  };
}

/** Workspace-facing view of the feature map: what this workspace can and cannot show. */
export function featureAvailability(features: FeatureCapabilities): Record<keyof FeatureCapabilities, "available" | "unavailable"> {
  const out = {} as Record<keyof FeatureCapabilities, "available" | "unavailable">;
  for (const [k, v] of Object.entries(features) as Array<[keyof FeatureCapabilities, string]>) {
    out[k] = v === "unavailable" ? "unavailable" : "available";
  }
  return out;
}
