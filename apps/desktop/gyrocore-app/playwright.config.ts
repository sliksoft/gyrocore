import { defineConfig, devices } from "@playwright/test";

// Built-PWA browser proof: serves `dist/` (run `npm run build` first) with `vite preview`.
const PORT = 4791;

export default defineConfig({
  testDir: "e2e",
  workers: 1,
  retries: 0,
  timeout: 120_000,
  forbidOnly: Boolean(process.env.CI),
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${PORT}/`,
    serviceWorkers: "allow",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npx vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
