import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const viewerRoot = path.resolve(here, "../../../third_party/betaflight/blackbox-log-viewer");

// Host the vendored viewer without copying or editing third_party sources.
export default defineConfig({
  root: viewerRoot,
  plugins: [vue()],
  server: {
    port: 1422,
    strictPort: true,
    fs: {
      allow: [viewerRoot, path.resolve(here, "../../..")],
    },
  },
  build: {
    outDir: path.resolve(here, "dist"),
    emptyOutDir: true,
  },
});
