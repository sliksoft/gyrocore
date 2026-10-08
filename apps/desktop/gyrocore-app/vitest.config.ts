import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

const repoRoot = fileURLToPath(new URL("../../..", import.meta.url));
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

export default defineConfig({
  plugins: [stubFlightLogUiDeps(), react()],
  resolve: {
    alias: [
      { find: "@", replacement: fileURLToPath(new URL("./src", import.meta.url)) },
      {
        find: "@bf-blackbox",
        replacement: fileURLToPath(
          new URL("../../../third_party/betaflight/blackbox-log-viewer/src", import.meta.url),
        ),
      },
      { find: "semver", replacement: fileURLToPath(new URL("./node_modules/semver", import.meta.url)) },
      { find: "pinia", replacement: piniaStub },
      {
        find: "virtual:pwa-register",
        replacement: fileURLToPath(new URL("./src/test/pwa-register-mock.ts", import.meta.url)),
      },
    ],
  },
  server: {
    fs: {
      allow: [repoRoot],
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
