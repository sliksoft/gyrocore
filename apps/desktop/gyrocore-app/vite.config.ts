import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { VitePWA } from "vite-plugin-pwa";
import { fileURLToPath, URL } from "node:url";
// @ts-expect-error type error without @types/node package
import process from "node:process";

const host = process.env.TAURI_DEV_HOST;
const repoRoot = fileURLToPath(new URL("../../..", import.meta.url));
const bfBlackboxSrc = fileURLToPath(
  new URL("../../../third_party/betaflight/blackbox-log-viewer/src", import.meta.url),
);
const fieldsPresenterStub = fileURLToPath(
  new URL("./src/decode/bf-stubs/flightlog_fields_presenter.js", import.meta.url),
);
const piniaStub = fileURLToPath(new URL("./src/decode/bf-stubs/pinia.js", import.meta.url));
const settingsStoreStub = fileURLToPath(
  new URL("./src/decode/bf-stubs/settings-store.js", import.meta.url),
);

function stubFlightLogUiDeps() {
  return {
    name: "gyrocore-stub-flightlog-ui-deps",
    enforce: "pre" as const,
    resolveId(id: string) {
      if (id.includes("flightlog_fields_presenter")) {
        return fieldsPresenterStub;
      }
      if (id === "pinia" || id.endsWith("/pinia") || id.endsWith("/pinia.js")) {
        return piniaStub;
      }
      if (id.includes("stores/settings")) {
        return settingsStoreStub;
      }
      return null;
    },
  };
}

// https://vite.dev/config/
export default defineConfig(() => ({
  plugins: [
    stubFlightLogUiDeps(),
    react(),
    tailwindcss(),
    VitePWA({
      registerType: "prompt",
      includeAssets: ["favicon.png", "favicon-32.png", "apple-touch-icon.png"],
      manifest: {
        name: "GyroCore",
        short_name: "GyroCore",
        description:
          "Betaflight Blackbox analysis and safe tuning in the browser. Logs stay on your device.",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#080c15",
        theme_color: "#080c15",
        lang: "en",
        icons: [
          {
            src: "/pwa-192x192.png",
            sizes: "192x192",
            type: "image/png",
          },
          {
            src: "/pwa-512x512.png",
            sizes: "512x512",
            type: "image/png",
          },
          {
            src: "/pwa-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // App shell / static assets only — never user BBL/CLI/decoded data.
        globPatterns: ["**/*.{js,css,html,ico,png,svg,woff,woff2,json}"],
        navigateFallback: "/index.html",
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
        runtimeCaching: [],
      },
      devOptions: {
        enabled: false,
      },
    }),
  ],
  resolve: {
    alias: [
      { find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) },
      // GPL-3.0 vendored Betaflight Blackbox Log Viewer (see docs/browser-blackbox-decoder.md)
      { find: "@bf-blackbox", replacement: bfBlackboxSrc },
      { find: "semver", replacement: fileURLToPath(new URL("./node_modules/semver", import.meta.url)) },
      { find: "pinia", replacement: piniaStub },
      // Decode-only stub — avoid Pinia/Vue UI stores in the worker.
    ],
  },
  worker: {
    format: "es",
    plugins: () => [stubFlightLogUiDeps()],
  },

  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    fs: {
      allow: [repoRoot],
    },
    watch: {
      ignored: ["**/src-tauri/**"],
    },
  },
}));
