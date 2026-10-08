// Stage temporary copies of the vendored Betaflight Configurator sources so they
// can run under plain Node (shared by the WU7 CHIRP and WU8 Autotune harnesses).
//
// third_party/betaflight/** is never written. Only the copies in a fresh
// tmpdir are touched:
//   - extensionless relative imports get an explicit .ts/.js suffix
//   - `vue` / `semver` and utils/common.clamp are replaced by tiny local stubs
//   - module-private useAutotune.ts functions are extracted verbatim into
//     js/autotune_extract.ts
//   - optionally, an `export { ... }` line is appended to the copy of
//     spectral_analysis.ts so module-private helpers can be called directly
//     (no statement of the original file is altered)
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { createHash } from "node:crypto";
import { appendFileSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
export const ROOT = resolve(HERE, "..", "..");
export const CONFIGURATOR = join(ROOT, "third_party", "betaflight", "configurator");
const VENDOR_JS = join(CONFIGURATOR, "src", "js");

export function sha256(buf) {
    return createHash("sha256").update(buf).digest("hex");
}

export function jsonReplacer(_key, value) {
    if (typeof value === "number" && !Number.isFinite(value)) {
        return String(value);
    }
    if (ArrayBuffer.isView(value)) {
        return Array.from(value, (v) => (Number.isFinite(v) ? v : String(v)));
    }
    return value;
}

function walk(dir) {
    const out = [];
    for (const name of readdirSync(dir)) {
        const p = join(dir, name);
        if (statSync(p).isDirectory()) {
            out.push(...walk(p));
        } else {
            out.push(p);
        }
    }
    return out;
}

function rewriteImports(file) {
    const src = readFileSync(file, "utf8");
    const out = src.replace(/(from\s+|import\s+)(["'])(\.{1,2}\/[^"']+)\2/g, (match, kw, q, spec) => {
        if (/\.(ts|js|mjs)$/.test(spec)) {
            return match;
        }
        const base = resolve(dirname(file), spec);
        for (const ext of [".ts", ".js"]) {
            if (existsSync(base + ext)) {
                return `${kw}${q}${spec}${ext}${q}`;
            }
        }
        return match;
    });
    if (out !== src) {
        writeFileSync(file, out);
    }
}

function writeStub(stage, name, body) {
    const dir = join(stage, "node_modules", name);
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "package.json"), JSON.stringify({ name, type: "module", main: "index.js" }));
    writeFileSync(join(dir, "index.js"), body);
}

/** Extract a top-level `function name(...) {...}` from source text verbatim. */
export function extractFunction(source, name, label = "source") {
    const start = source.indexOf(`function ${name}(`);
    if (start < 0) {
        throw new Error(`function ${name} not found in ${label}`);
    }
    const end = source.indexOf("\n}\n", start);
    return source.slice(start, end + 2);
}

/**
 * @param {object} [opts]
 * @param {string[]} [opts.autotuneFunctions] useAutotune.ts functions to extract (exported)
 * @param {string} [opts.autotunePrelude] lines placed before the extracted functions
 * @param {string[]} [opts.spectralExports] private spectral_analysis.ts names to export
 */
export function stageVendored(opts = {}) {
    const autotuneFunctions = opts.autotuneFunctions ?? ["computeSampleRate", "chooseSegmentSize"];
    const stage = mkdtempSync(join(tmpdir(), "gyrocore-chirp-ref-"));
    cpSync(join(VENDOR_JS, "blackbox"), join(stage, "js", "blackbox"), { recursive: true });
    cpSync(join(VENDOR_JS, "utils"), join(stage, "js", "utils"), { recursive: true });
    for (const f of ["data_storage.ts", "debug_modes_table.ts", "debug_fields_table.ts", "debug_units.ts", "debug_annotation.ts"]) {
        cpSync(join(VENDOR_JS, f), join(stage, "js", f));
    }
    writeFileSync(join(stage, "package.json"), JSON.stringify({ type: "module" }));
    // spectral_analysis.ts only needs clamp() from utils/common (which pulls in the app model).
    writeFileSync(
        join(stage, "js", "utils", "common.ts"),
        "export function clamp(value: number, min: number, max: number): number { return Math.min(Math.max(value, min), max); }\n",
    );
    writeStub(stage, "vue", "export function reactive(o) { return o; }\n");
    writeStub(
        stage,
        "semver",
        [
            "const RE = /^v?(\\d+)\\.(\\d+)\\.(\\d+)$/;",
            "function parse(v) { const m = RE.exec(String(v).trim()); return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null; }",
            "function valid(v) { return typeof v === 'string' && parse(v) ? v.trim().replace(/^v/, '') : null; }",
            "function compare(a, b) { const x = parse(a), y = parse(b); for (let i = 0; i < 3; i++) { if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1; } return 0; }",
            "function gte(a, b) { return compare(a, b) >= 0; }",
            "export default { valid, compare, gte };",
            "export { valid, compare, gte };",
        ].join("\n"),
    );
    const autotune = readFileSync(join(CONFIGURATOR, "src", "composables", "useAutotune.ts"), "utf8");
    writeFileSync(
        join(stage, "js", "autotune_extract.ts"),
        [
            "// Verbatim from src/composables/useAutotune.ts (module-private upstream).",
            "type SysConfig = any;",
            ...(opts.autotunePrelude ? [opts.autotunePrelude] : []),
            ...autotuneFunctions.map((name) => `export ${extractFunction(autotune, name, "useAutotune.ts")}`),
        ].join("\n\n"),
    );
    if (opts.spectralExports?.length) {
        appendFileSync(
            join(stage, "js", "blackbox", "spectral_analysis.ts"),
            `\n// GyroCore reference harness: expose module-private helpers (copy only).\nexport { ${opts.spectralExports.join(", ")} };\n`,
        );
    }
    for (const file of walk(join(stage, "js"))) {
        if (/\.(ts|js)$/.test(file)) {
            rewriteImports(file);
        }
    }
    return stage;
}
