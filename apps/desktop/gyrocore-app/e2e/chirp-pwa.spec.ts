/**
 * Built-PWA proof for browser CHIRP (real Chromium, `vite preview` of dist/).
 *
 * Uses committed synthetic WU7 fixtures only. Every request is recorded:
 * user files must never leave the page (GET-only, same-origin, with a positive
 * control that the CHIRP worker chunk itself was observed).
 */
import { expect, test, type Page, type Request } from "@playwright/test";
import { readFileSync } from "node:fs";
import { gunzipSync } from "node:zlib";

const WU7 = new URL("../../../../tests/fixtures/chirp/wu7/bbl/", import.meta.url);
const bbl = (name: string) => gunzipSync(readFileSync(new URL(`${name}.bbl.gz`, WU7)));
const CLI = Buffer.from("# diff all\n# version\n# Betaflight / STM32F405 (S405) 4.5.0\nset debug_mode = CHIRP\n");

type ChirpMessage = {
  ok: boolean;
  logIndex?: number;
  logCount?: number;
  rejection?: { code: string } | null;
  status?: string;
  lengths?: number[];
  flightLogBuilds?: number;
};

type Probe = { __chirp: ChirpMessage[]; __workers: string[] };

/** Records every request, every Worker construction and each session analyse reply (workers not modified). */
async function instrument(page: Page) {
  const requests: Request[] = [];
  page.context().on("request", (r) => requests.push(r));
  await page.addInitScript(() => {
    const w = window as unknown as Probe & { Worker: typeof Worker };
    w.__chirp = [];
    w.__workers = [];
    const Orig = window.Worker;
    w.Worker = class extends Orig {
      constructor(url: string | URL, opts?: WorkerOptions) {
        super(url, opts);
        w.__workers.push(String(url));
        this.addEventListener("message", (ev: MessageEvent) => {
          const d = ev.data ?? {};
          if (d.type !== "analyze" && !d.error) return;
          const a = d.analysis;
          const ax = a && Object.values(a.result.axes as Record<string, any>).find((x: any) => x?.usable);
          const tf = ax?.transfer_function;
          w.__chirp.push({
            ok: Boolean(d.ok),
            logIndex: a?.source.logIndex,
            logCount: a?.source.logCount,
            rejection: a?.rejection ?? null,
            status: a?.result.status,
            lengths: tf ? [tf.frequencies_hz.length, tf.magnitude_db.length, tf.phase_deg.length, tf.coherence.length] : [],
            flightLogBuilds: d.flightLogBuilds,
          });
        });
      }
    };
  });
  return requests;
}

async function chirpReply(page: Page): Promise<ChirpMessage> {
  await page.waitForFunction(() => (window as unknown as Probe).__chirp.length > 0, null, { timeout: 90_000 });
  return page.evaluate(() => (window as unknown as Probe).__chirp[0]!);
}

/** Exactly one session worker per selected BBL; the retired decode / CHIRP-only workers never run. */
async function expectSingleSessionWorker(page: Page) {
  const workers = await page.evaluate(() => (window as unknown as Probe).__workers);
  expect(workers.filter((u) => /browserSession/.test(u))).toHaveLength(1);
  expect(workers.filter((u) => /blackboxDecode|chirpAnalysis/.test(u))).toEqual([]);
}

async function loadAndAnalyze(page: Page, name: string, bytes: Buffer, log?: { index: number; count: number }) {
  await page.goto("/");
  await page.setInputFiles('[data-testid="bbl-file-input"]', { name: `${name}.bbl`, mimeType: "application/octet-stream", buffer: bytes });
  await expect(page.getByTestId("decode-status")).toBeVisible({ timeout: 60_000 });
  if (log) {
    const select = page.getByTestId("log-index").first();
    await expect(select.locator("option")).toHaveCount(log.count);
    await select.selectOption(String(log.index));
  }
  await page.setInputFiles('[data-testid="cli-file-input"]', { name: "cli.txt", mimeType: "text/plain", buffer: CLI });
  await expect(page.getByTestId("analyze-btn")).toBeEnabled();
  await page.getByTestId("analyze-btn").click();
  return chirpReply(page);
}

function expectNoUpload(requests: Request[], baseURL: string) {
  expect(requests.length).toBeGreaterThan(0);
  const offending = requests.filter(
    (r) => r.method() !== "GET" || !(r.url().startsWith(baseURL) || r.url().startsWith("blob:") || r.url().startsWith("data:")),
  );
  expect(offending.map((r) => `${r.method()} ${r.url()}`)).toEqual([]);
}

async function chartPoints(page: Page, label: string) {
  const points = await page.locator(`svg[aria-label="${label}"] polyline`).getAttribute("points");
  return points ? points.trim().split(/\s+/).length : 0;
}

test("PWA shell loads without Tauri, has a manifest and an activated service worker", async ({ page, baseURL }) => {
  const requests = await instrument(page);
  await page.goto("/");
  await expect(page.getByTestId("open-page")).toHaveAttribute("data-runtime", "browser");
  expect(await page.evaluate(() => "__TAURI_INTERNALS__" in window || "__TAURI__" in window)).toBe(false);

  const href = await page.locator('link[rel="manifest"]').getAttribute("href");
  expect(href).toBeTruthy();
  const manifest = await (await page.request.get(new URL(href!, baseURL).toString())).json();
  expect(manifest).toMatchObject({ name: "GyroCore", display: "standalone", start_url: "/" });

  const state = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready;
    const sw = reg.active!;
    if (sw.state !== "activated") await new Promise((r) => sw.addEventListener("statechange", () => sw.state === "activated" && r(null)));
    return sw.state;
  });
  expect(state).toBe("activated");
  expectNoUpload(requests, baseURL!);
});

test("usable CHIRP fixture: decode, CLI, worker analysis, non-empty series, PASS", async ({ page, baseURL }) => {
  const requests = await instrument(page);
  const reply = await loadAndAnalyze(page, "clean_single_axis", bbl("clean_single_axis"));
  expect(reply).toMatchObject({ ok: true, rejection: null, status: "ok", logCount: 1, flightLogBuilds: 1 });
  const [n, ...rest] = reply.lengths!;
  expect(n).toBeGreaterThan(8);
  expect(rest).toEqual([n, n, n]);

  await page.getByTestId("nav-chirp").click();
  const card = page.getByTestId("chirp-available");
  await expect(card).toBeVisible();
  await expect(card.getByText("PASS", { exact: true })).toBeVisible();
  const counts = await Promise.all(["Magnitude", "Phase", "Coherence"].map((l) => chartPoints(page, l)));
  expect(counts[0]).toBeGreaterThan(8);
  expect(counts).toEqual([counts[0], counts[0], counts[0]]);

  await page.getByTestId("nav-overview").click();
  await expect(page.locator("dt", { hasText: /^CHIRP$/ }).locator("+ dd")).toHaveText("PASS");

  // Positive control: the request monitor saw the session worker chunk.
  expect(requests.some((r) => /browserSession.*\.js/.test(r.url()))).toBe(true);
  await expectSingleSessionWorker(page);
  expectNoUpload(requests, baseURL!);
});

test("multi-log BBL: the selected embedded log is the one analysed", async ({ page, baseURL }) => {
  const requests = await instrument(page);
  const multi = Buffer.concat(["clean_single_axis", "three_axis_sequence", "known_gain"].map(bbl));
  const reply = await loadAndAnalyze(page, "multi", multi, { index: 1, count: 3 });
  expect(reply).toMatchObject({ ok: true, rejection: null, logIndex: 1, logCount: 3, flightLogBuilds: 1 });
  expect(reply.lengths![0]).toBeGreaterThan(8);
  await page.getByTestId("nav-chirp").click();
  await expect(page.getByTestId("chirp-available")).toBeVisible();
  expectNoUpload(requests, baseURL!);
});

test("rejected CHIRP fixture never reports PASS", async ({ page, baseURL }) => {
  const requests = await instrument(page);
  const reply = await loadAndAnalyze(page, "poor_coherence", bbl("poor_coherence"));
  expect(reply).toMatchObject({ ok: true, status: "unusable", rejection: { code: "chirp_unusable" }, lengths: [] });

  await page.getByTestId("nav-chirp").click();
  const card = page.getByTestId("chirp-unavailable");
  await expect(card).toBeVisible();
  await expect(card.getByText("NOT AVAILABLE", { exact: true })).toBeVisible();
  await expect(page.getByText("PASS", { exact: true })).toHaveCount(0);
  await expect(page.locator('svg[aria-label="Magnitude"]')).toHaveCount(0);

  await page.getByTestId("nav-overview").click();
  await expect(page.locator("dt", { hasText: /^CHIRP$/ }).locator("+ dd")).toHaveText("NOT AVAILABLE");
  await expect(page.getByText("PASS", { exact: true })).toHaveCount(0);
  expectNoUpload(requests, baseURL!);
});

/** Every Cache Storage entry is a same-origin build asset; no flight data in browser storage. */
async function expectNoFlightDataPersisted(page: Page, baseURL: string, names: string[]) {
  const stored = await page.evaluate(async () => {
    const cached: string[] = [];
    for (const key of await caches.keys()) {
      for (const req of await (await caches.open(key)).keys()) cached.push(req.url);
    }
    const idb = "databases" in indexedDB ? (await indexedDB.databases()).map((d) => d.name ?? "") : [];
    return { cached, local: Object.keys(localStorage), session: Object.keys(sessionStorage), idb };
  });
  expect(stored.cached.length).toBeGreaterThan(0); // precache exists, so the check is not vacuous
  for (const url of stored.cached) {
    expect(url.startsWith(baseURL)).toBe(true);
    expect(url).toMatch(/\.(html|js|css|png|svg|ico|webmanifest|woff2?|json)(\?.*)?$/);
    for (const n of names) expect(url).not.toContain(n);
  }
  expect(stored.local.filter((k) => k !== "gyrocore.sidebar.collapsed")).toEqual([]);
  expect(stored.session).toEqual([]);
  expect(stored.idb.filter((n) => !/workbox/i.test(n))).toEqual([]);
}

test("Begin analysis: multi-log BBL + CLI -> real browser workspace across pages, nothing uploaded or persisted", async ({ page, baseURL }) => {
  const requests = await instrument(page);
  const multi = Buffer.concat(["clean_single_axis", "three_axis_sequence", "poor_coherence"].map(bbl));
  await page.goto("/");
  expect(await page.evaluate(() => "__TAURI_INTERNALS__" in window || "__TAURI__" in window)).toBe(false);
  await page.evaluate(() => navigator.serviceWorker.ready);

  await expect(page.getByTestId("analyze-btn")).toBeDisabled();
  await page.setInputFiles('[data-testid="bbl-file-input"]', { name: "multi.bbl", mimeType: "application/octet-stream", buffer: multi });
  await expect(page.getByTestId("decode-status")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByTestId("analyze-btn")).toBeDisabled(); // CLI still missing
  const select = page.getByTestId("log-index").first();
  await expect(select.locator("option")).toHaveCount(3);
  await select.selectOption("1");
  await page.setInputFiles('[data-testid="cli-file-input"]', { name: "cli.txt", mimeType: "text/plain", buffer: CLI });
  await expect(page.getByTestId("files-ready")).toContainText("Ready for local browser analysis.");
  await expect(page.getByTestId("analyze-btn")).toBeEnabled();
  await page.getByTestId("analyze-btn").click();

  const reply = await chirpReply(page);
  expect(reply).toMatchObject({ ok: true, logIndex: 1, logCount: 3, status: "ok", rejection: null, flightLogBuilds: 1 });

  // Overview: real files, selected log, decode and CHIRP status.
  const kv = (label: string) => page.locator("dt", { hasText: new RegExp(`^${label}$`) }).locator("+ dd");
  await expect(kv("BBL")).toHaveText("multi.bbl");
  await expect(kv("CLI")).toHaveText("cli.txt");
  await expect(kv("Log index")).toHaveText("1 of 3");
  await expect(kv("Decode")).toHaveText(/^decoded in browser · \d+ frames$/);
  await expect(kv("CHIRP")).toHaveText("PASS");
  await expect(kv("Final safety")).toHaveText("NOT AVAILABLE");

  await page.getByTestId("nav-blackbox").click();
  const bbPage = page.getByTestId("blackbox-browser");
  await expect(bbPage).toContainText("multi.bbl");
  await expect(bbPage).toContainText("1 of 3");
  await expect(page.getByTestId("blackbox-flights")).toContainText("▶ 1:");
  await expect(page.getByTestId("viewer-frame")).toHaveCount(0);

  await page.getByTestId("nav-chirp").click();
  await expect(page.getByTestId("chirp-available").getByText("PASS", { exact: true })).toBeVisible();
  const counts = await Promise.all(["Magnitude", "Phase", "Coherence"].map((l) => chartPoints(page, l)));
  expect(counts[0]).toBeGreaterThan(8);
  expect(counts).toEqual([counts[0], counts[0], counts[0]]);

  await page.getByTestId("nav-cli").click();
  await expect(page.getByTestId("cli-page")).toContainText("cli.txt");
  await expect(page.getByTestId("apply-cli-panel")).toHaveCount(0);

  for (const [nav, id] of [["nav-tune", "tune-unavailable"], ["nav-safety", "safety-unavailable"]] as const) {
    await page.getByTestId(nav).click();
    await expect(page.getByTestId(id)).toContainText(/not available in the browser yet/i);
  }

  await page.getByTestId("nav-overview").click();
  await expect(kv("Log index")).toHaveText("1 of 3"); // workspace survived navigation

  expect(requests.some((r) => /browserSession.*\.js/.test(r.url()))).toBe(true);
  // No demo fallback: the page never requests demo fixtures (the service worker's
  // install-time precache of the static demo files is not a page fetch) and shows no DEMO state.
  expect(requests.filter((r) => /\/demo\//.test(r.url()) && !r.serviceWorker()).map((r) => r.url())).toEqual([]);
  await expect(page.getByTestId("workspace-meta")).not.toContainText("DEMO");
  await expectSingleSessionWorker(page);
  expectNoUpload(requests, baseURL!);
  await expectNoFlightDataPersisted(page, baseURL!, ["multi.bbl", "cli.txt"]);
});
