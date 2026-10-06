// Upstream reference-vector harness for GyroCore CHIRP / system-ID parity (WU7).
//
// Runs the *vendored* Betaflight Configurator TypeScript (third_party/betaflight/
// configurator, read-only) over the fixtures produced by make_cases.py and writes
// the expected values the Python port is checked against.
//
// The vendored files are copied into a temporary directory; only those copies are
// touched (extensionless relative imports get an explicit .ts/.js suffix, and the
// `vue` / `semver` packages are replaced by tiny local stubs). The SHA-256 of
// every vendored source file used is recorded in the output.
//
//   node --experimental-strip-types tools/chirp_reference/reference_harness.mjs
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { createHash } from "node:crypto";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { gunzipSync } from "node:zlib";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..", "..");
const CONFIGURATOR = join(ROOT, "third_party", "betaflight", "configurator");
const VENDOR_JS = join(CONFIGURATOR, "src", "js");
const FIXTURES = join(ROOT, "tests", "fixtures", "chirp", "wu7");

const VENDORED_FILES = [
    "src/js/blackbox/chirp_bbl_parser.ts",
    "src/js/blackbox/datastream.js",
    "src/js/blackbox/decoders.js",
    "src/js/blackbox/spectral_analysis.ts",
    "src/js/blackbox/fft.ts",
    "src/js/data_storage.ts",
    "src/js/utils/debugModes.ts",
    "src/js/debug_modes_table.ts",
    "src/js/debug_fields_table.ts",
    "src/js/debug_units.ts",
    "src/js/debug_annotation.ts",
    "src/composables/useAutotune.ts",
];

function sha256(buf) {
    return createHash("sha256").update(buf).digest("hex");
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

// Extract a module-private function from useAutotune.ts verbatim.
function extractFunction(source, name) {
    const start = source.indexOf(`function ${name}(`);
    if (start < 0) {
        throw new Error(`function ${name} not found in useAutotune.ts`);
    }
    const end = source.indexOf("\n}\n", start);
    return source.slice(start, end + 2);
}

function stageVendored() {
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
            `export ${extractFunction(autotune, "computeSampleRate")}`,
            `export ${extractFunction(autotune, "chooseSegmentSize")}`,
        ].join("\n\n"),
    );
    for (const file of walk(join(stage, "js"))) {
        if (/\.(ts|js)$/.test(file)) {
            rewriteImports(file);
        }
    }
    return stage;
}

const toArray = (a) => Array.from(a);

function jsonReplacer(_key, value) {
    if (typeof value === "number" && !Number.isFinite(value)) {
        return String(value);
    }
    if (ArrayBuffer.isView(value)) {
        return Array.from(value, (v) => (Number.isFinite(v) ? v : String(v)));
    }
    return value;
}

function float32Digest(arr) {
    return sha256(Buffer.from(arr.buffer, arr.byteOffset, arr.byteLength));
}

function tfToJson(tf) {
    return {
        numSegments: tf.numSegments,
        frequencies: tf.frequencies,
        hReal: tf.hReal,
        hImag: tf.hImag,
        magnitude: tf.magnitude,
        phase: tf.phase,
        coherence: tf.coherence,
    };
}

function stepToJson(step) {
    return {
        timeMs: step.timeMs,
        response: step.response,
        overshootPct: step.overshootPct,
        riseTimeMs: step.riseTimeMs,
        settlingTimeMs: step.settlingTimeMs,
    };
}

async function main() {
    const stage = stageVendored();
    try {
        const mod = (p) => import(pathToFileURL(join(stage, "js", p)).href);
        const parser = await mod("blackbox/chirp_bbl_parser.ts");
        const spectral = await mod("blackbox/spectral_analysis.ts");
        const { ComplexFFT } = await mod("blackbox/fft.ts");
        const { getDebugModeIndex } = await mod("utils/debugModes.ts");
        const CONFIGURATOR_STATE = (await mod("data_storage.ts")).default;
        const autotune = await mod("autotune_extract.ts");

        const provenance = {
            generator: relative(ROOT, fileURLToPath(import.meta.url)),
            node: process.version,
            upstream_commit: readFileSync(join(CONFIGURATOR, "UPSTREAM_COMMIT"), "utf8").trim(),
            api_version_max_supported: CONFIGURATOR_STATE.API_VERSION_MAX_SUPPORTED,
            vendored_sha256: Object.fromEntries(
                VENDORED_FILES.map((f) => [`third_party/betaflight/configurator/${f}`, sha256(readFileSync(join(CONFIGURATOR, f)))]),
            ),
        };

        // ---------------- math vectors ----------------
        const math = JSON.parse(readFileSync(join(FIXTURES, "math_inputs.json"), "utf8"));
        const fft = math.fft.map((spec) => {
            const f = new ComplexFFT(spec.n, spec.inverse);
            const out = new Float64Array(2 * spec.n);
            const input = Float64Array.from(spec.input);
            f.simple(out, input, spec.kind);
            return { n: spec.n, inverse: spec.inverse, kind: spec.kind, output: out };
        });
        const hanning = math.hanning_sizes.map((n) => ({ size: n, window: spectral.hanningWindow(n) }));
        const welch = math.welch.map((spec) => {
            const tf = spectral.welchTransferFunction(spec.input, spec.output, spec.sample_rate, spec.segment_size, spec.overlap);
            const sens = spectral.computeSensitivity(tf);
            const ol = spectral.openLoopResponse(tf);
            const effectiveSeg = 2 * (tf.frequencies.length - 1);
            const step = spectral.computeStepResponse(tf, spec.sample_rate, effectiveSeg);
            return {
                name: spec.name,
                transferFunction: tfToJson(tf),
                sensitivity: { magnitude: sens.magnitude, phase: sens.phase, peakDb: sens.peakDb },
                openLoop: { magnitude: ol.magnitude, phase: ol.phase, startIndex: ol.startIndex },
                stepResponse: { segmentSize: effectiveSeg, ...stepToJson(step) },
            };
        });
        const spectrogram = math.spectrogram.map((spec) => {
            const sg = spectral.computeSpectrogram(spec.signal, spec.sample_rate, spec.window_size, spec.overlap);
            return { name: spec.name, ...sg };
        });
        const sampleRate = math.sample_rate_sysconfigs.map((sc) => ({ sysConfig: sc, sampleRate: autotune.computeSampleRate(sc) }));
        const segmentSize = math.segment_size_rates.map((rate) => ({ sampleRate: rate, segmentSize: autotune.chooseSegmentSize(rate) }));
        const debugModes = math.debug_mode_api_versions.map((v) => ({ apiVersion: v, chirpIndex: getDebugModeIndex("CHIRP", v ?? undefined) }));

        writeFileSync(
            join(FIXTURES, "upstream_math_reference.json"),
            JSON.stringify({ provenance, fft, hanning, welch, spectrogram, sampleRate, segmentSize, debugModes }, jsonReplacer) + "\n",
        );

        // ---------------- BBL cases ----------------
        const manifest = JSON.parse(readFileSync(join(FIXTURES, "cases.json"), "utf8"));
        const cases = [];
        for (const c of manifest.cases) {
            const data = new Uint8Array(gunzipSync(readFileSync(join(FIXTURES, c.bbl))));
            const entry = { case_id: c.case_id, bbl_sha256: sha256(data) };
            if (entry.bbl_sha256 !== c.bbl_sha256) {
                throw new Error(`${c.case_id}: BBL digest mismatch with cases.json`);
            }
            const logs = parser.findLogBoundaries(data);
            entry.logBoundaries = logs;
            let parsed;
            try {
                parsed = parser.parseChirpLog(data, logs[0].start, logs[0].end);
            } catch (err) {
                entry.parseError = String(err && err.message ? err.message : err);
                cases.push(entry);
                continue;
            }
            const { sysConfig, chirpData } = parsed;
            entry.sysConfig = {
                looptime: sysConfig.looptime,
                pid_process_denom: sysConfig.pid_process_denom,
                frameIntervalI: sysConfig.frameIntervalI,
                frameIntervalPNum: sysConfig.frameIntervalPNum,
                frameIntervalPDenom: sysConfig.frameIntervalPDenom,
                debug_mode: sysConfig.debug_mode,
                blackbox_high_resolution: sysConfig.blackbox_high_resolution,
                chirp_frequency_start_deci_hz: sysConfig.chirp_frequency_start_deci_hz,
                chirp_frequency_end_deci_hz: sysConfig.chirp_frequency_end_deci_hz,
                chirp_time_seconds: sysConfig.chirp_time_seconds,
                firmwareRevision: sysConfig.firmwareRevision ?? null,
                firmwareApiVersion: sysConfig.firmwareApiVersion ?? null,
            };
            entry.chirpData = {
                sampleCount: chirpData.sampleCount,
                totalFrames: chirpData.totalFrames,
                corruptFrames: chirpData.corruptFrames,
                segments: chirpData.segments,
                digests: {
                    setpoint: chirpData.setpoint.map(float32Digest),
                    gyro: chirpData.gyro.map(float32Digest),
                    debug: chirpData.debug.map(float32Digest),
                },
            };
            // Mirrors useAutotune.ts analyzeLog()/computeAxisResult() up to (but
            // excluding) recommendGains(), which GyroCore does not port.
            const sampleRateHz = autotune.computeSampleRate(sysConfig);
            const segSize = autotune.chooseSegmentSize(sampleRateHz);
            entry.analysis = { sampleRate: sampleRateHz, sampleRateRounded: Math.round(sampleRateHz), segmentSize: segSize, segments: [] };
            const selected = {};
            for (let i = 0; i < chirpData.segments.length; i++) {
                const seg = chirpData.segments[i];
                const len = seg.endIdx - seg.startIdx + 1;
                const segOut = { index: i, axis: seg.axis, startIdx: seg.startIdx, endIdx: seg.endIdx, length: len };
                if (!Number.isInteger(seg.axis) || seg.axis < 0 || seg.axis > 2) {
                    segOut.error = "unsupported DEBUG_CHIRP axis encoding";
                    entry.analysis.segments.push(segOut);
                    entry.analysis.error = segOut.error;
                    break;
                }
                if (len < segSize) {
                    segOut.skipped = "len < segmentSize";
                    entry.analysis.segments.push(segOut);
                    continue;
                }
                const input = chirpData.setpoint[seg.axis].subarray(seg.startIdx, seg.endIdx + 1);
                const output = chirpData.gyro[seg.axis].subarray(seg.startIdx, seg.endIdx + 1);
                const tf = spectral.welchTransferFunction(input, output, sampleRateHz, segSize, 0.5);
                const sens = spectral.computeSensitivity(tf);
                const step = spectral.computeStepResponse(tf, sampleRateHz, segSize);
                const sg = spectral.computeSpectrogram(output, sampleRateHz);
                const ol = spectral.openLoopResponse(tf);
                segOut.inputDigest = float32Digest(input);
                segOut.outputDigest = float32Digest(output);
                segOut.transferFunction = tfToJson(tf);
                segOut.sensitivity = { magnitude: sens.magnitude, phase: sens.phase, peakDb: sens.peakDb };
                segOut.stepResponse = stepToJson(step);
                segOut.openLoop = { magnitude: ol.magnitude, phase: ol.phase, startIndex: ol.startIndex };
                segOut.spectrogram = {
                    numSegments: sg.numSegments,
                    numBins: sg.numBins,
                    timeMs: sg.timeMs,
                    freqHz: sg.freqHz,
                    powerFirstRow: sg.power.subarray(0, sg.numBins),
                    powerLastRow: sg.power.subarray((sg.numSegments - 1) * sg.numBins),
                    powerSum: sg.power.reduce((a, b) => a + b, 0),
                };
                selected[seg.axis] = i;
                entry.analysis.segments.push(segOut);
            }
            entry.analysis.selectedSegmentByAxis = selected;
            entry.analysis.result = Object.keys(selected).length === 0 ? null : "axes";
            cases.push(entry);
        }
        writeFileSync(join(FIXTURES, "upstream_reference.json"), JSON.stringify({ provenance, cases }, jsonReplacer) + "\n");
        console.log(`reference vectors: ${fft.length} fft, ${welch.length} welch, ${cases.length} cases`);
    } finally {
        rmSync(stage, { recursive: true, force: true });
    }
}

await main();
