import { readFileSync, existsSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { describe, expect, it } from "vitest";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

describe("PWA manifest expectations", () => {
  it("configures vite-plugin-pwa with GyroCore standalone metadata", () => {
    const cfg = readFileSync(resolve(root, "vite.config.ts"), "utf8");
    expect(cfg).toContain("VitePWA");
    expect(cfg).toContain('registerType: "prompt"');
    expect(cfg).toContain('name: "GyroCore"');
    expect(cfg).toContain('short_name: "GyroCore"');
    expect(cfg).toContain('display: "standalone"');
    expect(cfg).toContain('start_url: "/"');
    expect(cfg).toContain('scope: "/"');
    expect(cfg).toContain("#080c15");
  });

  it("ships 192 and 512 PWA icons", () => {
    expect(existsSync(resolve(root, "public/pwa-192x192.png"))).toBe(true);
    expect(existsSync(resolve(root, "public/pwa-512x512.png"))).toBe(true);
  });
});
