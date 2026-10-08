// Upstream reference-vector harness for GyroCore Autotune recommendation parity (WU8).
//
// Runs the *vendored* Betaflight Configurator TypeScript (third_party/betaflight/
// configurator, read-only) and writes tests/fixtures/autotune/wu8/
// upstream_autotune_reference.json.gz.
//
// Staging (tools/chirp_reference/stage_vendored.mjs) copies the vendored sources
// to a tmpdir. On the copies only: spectral_analysis.ts gets an appended
// `export { ... }` for its module-private helpers, and useAutotune.ts's private
// extractCurrentSliders / buildGains / computeAxisResult / computeSampleRate /
// chooseSegmentSize are extracted verbatim. makeSyntheticTf is extracted verbatim
// from configurator/test/js/spectral_analysis.test.js.
//
// Recorded per recommendation: recommendGains() output (proposed + analysis), the
// helper results it is built from, the sensitivity scan grid, and the shaping /
// pre-clamp terms. The few local expressions of computeGainScales /
// buildProposedSliders that are not helper calls (gainForMargin, admissibleMax,
// robustnessFactor, raw ffScale / filterScale, raw slider products) are evaluated
// here with the identical expression and checked against the returned values.
//
//   node --experimental-strip-types tools/autotune_reference/autotune_harness.mjs
//
// SPDX-License-Identifier: GPL-3.0-or-later

import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { gunzipSync, gzipSync } from "node:zlib";

import { CONFIGURATOR, ROOT, extractFunction, jsonReplacer, sha256, stageVendored } from "../chirp_reference/stage_vendored.mjs";

const FIXTURES = join(ROOT, "tests", "fixtures", "autotune", "wu8");

const VENDORED_FILES = [
    "src/js/blackbox/spectral_analysis.ts",
    "src/js/blackbox/chirp_bbl_parser.ts",
    "src/js/blackbox/fft.ts",
    "src/js/blackbox/datastream.js",
    "src/js/blackbox/decoders.js",
    "src/js/utils/common.ts",
    "src/composables/useAutotune.ts",
    "src/components/tabs/autotune/GainRecommendation.vue",
    "test/js/spectral_analysis.test.js",
];

const SPECTRAL_PRIVATE = [
    "extractMetrics",
    "computeGainScales",
    "buildProposedSliders",
    "findOpenLoopCrossover",
    "findTargetCrossover",
    "peakSensitivityAtGain",
    "scanSensitivity",
    "findMaxAchievablePhaseMargin",
    "estimateLoopDelayMs",
    "findBandwidth",
    "findResonantPeak",
    "computeLowFreqError",
    "findNoiseFloor",
    "computeMeanCoherence",
    "resonanceBackoffs",
    "gainClampLimitOf",
    "robustGain",
    "integralScale",
    "MIN_OPEN_LOOP_HZ",
    "CROSSOVER_COHERENCE_MIN",
    "DEFAULT_DTERM_FILTER_HZ",
    "GAIN_SCALE_MIN",
    "GAIN_SCALE_MAX",
    "MAX_SENSITIVITY_PEAK",
    "SENSITIVITY_BIND_TOLERANCE",
    "GAIN_SCAN_STEP",
];

const AUTOTUNE_FUNCTIONS = ["computeSampleRate", "chooseSegmentSize", "extractCurrentSliders", "buildGains", "computeAxisResult"];
const AUTOTUNE_PRELUDE = [
    'import { welchTransferFunction, recommendGains, computeSensitivity, computeStepResponse, computeSpectrogram } from "./blackbox/spectral_analysis.ts";',
].join("\n");

function tfArrays(tf) {
    return {
        frequencies: tf.frequencies,
        hReal: tf.hReal,
        hImag: tf.hImag,
        magnitude: tf.magnitude,
        phase: tf.phase,
        coherence: tf.coherence,
        numSegments: tf.numSegments ?? null,
    };
}

function scanGrid(S, tf, ol, maxGain) {
    // Same grid walk as scanSensitivity (gain starts at GAIN_SCALE_MIN, += GAIN_SCAN_STEP).
    const gains = [];
    const peaks = [];
    for (let gain = S.GAIN_SCALE_MIN; gain <= maxGain + 1e-9; gain += S.GAIN_SCAN_STEP) {
        gains.push(gain);
        const peak = S.peakSensitivityAtGain(tf, ol, gain);
        peaks.push(peak);
        if (!Number.isFinite(peak)) {
            break;
        }
    }
    return { gains, peaks };
}

function check(cond, msg) {
    if (!cond) {
        throw new Error(`harness consistency check failed: ${msg}`);
    }
}

function same(a, b) {
    return Object.is(a, b) || (Number.isNaN(a) && Number.isNaN(b));
}

function recordRecommendation(S, tf, ol, sliders, pm) {
    const rec = S.recommendGains(tf, sliders, pm);
    const a = rec.analysis;
    const metrics = S.extractMetrics(tf, ol, pm);
    const scales = S.computeGainScales(metrics, tf, ol);
    for (const k of Object.keys(metrics)) {
        check(same(metrics[k], a[k]), `extractMetrics.${k}`);
    }
    for (const k of Object.keys(scales)) {
        check(same(scales[k], a[k]), `computeGainScales.${k}`);
    }
    const crossover = S.findOpenLoopCrossover(tf, ol);
    const target = S.findTargetCrossover(tf, ol, pm);
    const resonant = S.findResonantPeak(tf.frequencies, tf.magnitude, tf.coherence);
    const backoffs = S.resonanceBackoffs(a.resonantPeakDb);
    const gainForMargin = Number.isFinite(a.gainToTarget) ? a.gainToTarget : 1;
    const requestedGain = gainForMargin * backoffs.resonanceBackoff;
    check(same(requestedGain, a.requestedGain), "requestedGain");
    const admissibleMax = Math.min(Math.max(requestedGain, S.GAIN_SCALE_MIN), S.GAIN_SCALE_MAX);
    const robust = S.robustGain(tf, ol, admissibleMax);
    check(same(Math.min(Math.max(robust.piScale, S.GAIN_SCALE_MIN), S.GAIN_SCALE_MAX), a.piScale), "piScale");
    const robustnessFactor = robust.piScale / admissibleMax;
    const rawFfScale = gainForMargin * backoffs.ffResonanceBackoff * robustnessFactor;
    check(same(Math.min(Math.max(rawFfScale, S.GAIN_SCALE_MIN), S.GAIN_SCALE_MAX), a.ffScale), "ffScale");
    const rawIScale = S.integralScale(a.lowFreqErrorDb);
    const rawFilterScale = Number.isFinite(a.noiseFloorHz) ? a.noiseFloorHz / S.DEFAULT_DTERM_FILTER_HZ : 1;
    const peakAtAdmissible = S.peakSensitivityAtGain(tf, ol, admissibleMax);
    const robustScan = Number.isNaN(peakAtAdmissible) || peakAtAdmissible <= S.MAX_SENSITIVITY_PEAK
        ? null
        : S.scanSensitivity(tf, ol, S.MAX_SENSITIVITY_PEAK, admissibleMax);
    const proposed = S.buildProposedSliders(sliders, a);
    for (const k of Object.keys(proposed)) {
        check(same(proposed[k], rec.proposed[k]), `proposed.${k}`);
    }
    const scaleFor = {
        slider_master_multiplier: [sliders.masterMultiplier ?? 1, null],
        slider_pi_gain: [sliders.piGain ?? 1, a.piScale],
        slider_i_gain: [sliders.iGain ?? 1, a.iScale],
        slider_d_gain: [sliders.dGain ?? 1, a.dScale],
        slider_feedforward_gain: [sliders.feedforwardGain ?? 1, a.ffScale],
        slider_dterm_filter_multiplier: [sliders.dtermFilterMultiplier ?? 1, a.filterScale],
    };
    const rawSliders = {};
    for (const [k, [cur, scale]] of Object.entries(scaleFor)) {
        const raw = scale === null ? cur * 100 : cur * scale * 100;
        const clamped = Math.min(Math.max(raw, 25), 250);
        check(same(Math.round(clamped), rec.proposed[k]), `raw slider ${k}`);
        rawSliders[k] = { current: cur, scale: scale ?? 1, raw, clamped, rounded: Math.round(clamped) };
    }
    return {
        targetPhaseMarginDeg: pm,
        proposed: rec.proposed,
        analysis: a,
        intermediates: {
            crossover,
            target,
            resonant,
            bandwidthHz: S.findBandwidth(tf.frequencies, tf.magnitude, tf.coherence),
            lowFreqErrorDb: S.computeLowFreqError(tf.frequencies, tf.magnitude, tf.coherence),
            noiseFloorHz: S.findNoiseFloor(tf.frequencies, tf.coherence),
            meanCoherence: S.computeMeanCoherence(tf.frequencies, tf.coherence),
            loopDelayMs: S.estimateLoopDelayMs(tf, ol),
            maxAchievablePhaseMarginDeg: S.findMaxAchievablePhaseMargin(tf, ol),
            metricsScan: S.scanSensitivity(tf, ol, S.MAX_SENSITIVITY_PEAK),
            metricsScanGrid: scanGrid(S, tf, ol, S.GAIN_SCALE_MAX),
            backoffs,
            gainForMargin,
            admissibleMax,
            gainClampLimit: S.gainClampLimitOf(a.gainClamped, requestedGain),
            peakAtAdmissible,
            robust,
            robustScan,
            robustnessFactor,
            rawIScale,
            rawFfScale,
            rawFilterScale,
            predictedSensitivityPeak: S.peakSensitivityAtGain(tf, ol, a.piScale),
            rawSliders,
        },
    };
}

function applyCoherenceOverrides(tf, overrides) {
    for (const [lo, hi, value] of overrides) {
        for (let k = 0; k < tf.frequencies.length; k++) {
            if (tf.frequencies[k] >= lo && tf.frequencies[k] <= hi) {
                tf.coherence[k] = value;
            }
        }
    }
}

async function main() {
    const stage = stageVendored({ autotuneFunctions: AUTOTUNE_FUNCTIONS, autotunePrelude: AUTOTUNE_PRELUDE, spectralExports: SPECTRAL_PRIVATE });
    try {
        const testSrc = readFileSync(join(CONFIGURATOR, "test", "js", "spectral_analysis.test.js"), "utf8");
        writeFileSync(
            join(stage, "js", "synthetic_tf.js"),
            `// Verbatim from configurator/test/js/spectral_analysis.test.js\nexport ${extractFunction(testSrc, "makeSyntheticTf", "spectral_analysis.test.js")}\n`,
        );
        const mod = (p) => import(pathToFileURL(join(stage, "js", p)).href);
        const S = await mod("blackbox/spectral_analysis.ts");
        const parser = await mod("blackbox/chirp_bbl_parser.ts");
        const autotune = await mod("autotune_extract.ts");
        const { makeSyntheticTf } = await mod("synthetic_tf.js");

        const provenance = {
            generator: relative(ROOT, fileURLToPath(import.meta.url)),
            node: process.version,
            upstream_commit: readFileSync(join(CONFIGURATOR, "UPSTREAM_COMMIT"), "utf8").trim(),
            vendored_sha256: Object.fromEntries(
                VENDORED_FILES.map((f) => [`third_party/betaflight/configurator/${f}`, sha256(readFileSync(join(CONFIGURATOR, f)))]),
            ),
            constants: Object.fromEntries(SPECTRAL_PRIVATE.filter((n) => /^[A-Z_]+$/.test(n)).map((n) => [n, S[n]])),
            phaseMarginPresets: S.PHASE_MARGIN_PRESETS,
        };

        // ---------------- synthetic transfer functions ----------------
        const synthetic = JSON.parse(readFileSync(join(FIXTURES, "synthetic_cases.json"), "utf8"));
        const syntheticOut = [];
        for (const c of synthetic.cases) {
            const tf = makeSyntheticTf(c.make_synthetic_tf);
            applyCoherenceOverrides(tf, c.coherence_overrides);
            const ol = S.openLoopResponse(tf);
            syntheticOut.push({
                case_id: c.case_id,
                sliders: c.sliders,
                transferFunction: tfArrays(tf),
                openLoop: { magnitude: ol.magnitude, phase: ol.phase, startIndex: ol.startIndex },
                recommendations: c.presets.map((pm) => recordRecommendation(S, tf, ol, c.sliders, pm)),
            });
        }

        // ---------------- closed-loop BBL logs ----------------
        const bblManifest = JSON.parse(readFileSync(join(FIXTURES, "bbl_cases.json"), "utf8"));
        const bblOut = [];
        for (const c of bblManifest.cases) {
            const data = new Uint8Array(gunzipSync(readFileSync(join(FIXTURES, c.bbl))));
            const entry = { case_id: c.case_id, bbl_sha256: sha256(data) };
            if (entry.bbl_sha256 !== c.bbl_sha256) {
                throw new Error(`${c.case_id}: BBL digest mismatch with bbl_cases.json`);
            }
            const logs = parser.findLogBoundaries(data);
            const { sysConfig, chirpData } = parser.parseChirpLog(data, logs[0].start, logs[0].end);
            const sampleRate = autotune.computeSampleRate(sysConfig);
            const segmentSize = autotune.chooseSegmentSize(sampleRate);
            const currentSliders = autotune.extractCurrentSliders(sysConfig);
            entry.sysConfig = {
                looptime: sysConfig.looptime,
                pid_process_denom: sysConfig.pid_process_denom,
                frameIntervalPNum: sysConfig.frameIntervalPNum,
                frameIntervalPDenom: sysConfig.frameIntervalPDenom,
                rollPID: sysConfig.rollPID,
                pitchPID: sysConfig.pitchPID,
                yawPID: sysConfig.yawPID,
                simplified_master_multiplier: sysConfig.simplified_master_multiplier,
                simplified_pi_gain: sysConfig.simplified_pi_gain,
                simplified_i_gain: sysConfig.simplified_i_gain,
                simplified_d_gain: sysConfig.simplified_d_gain,
                simplified_feedforward_gain: sysConfig.simplified_feedforward_gain,
                simplified_dterm_filter_multiplier: sysConfig.simplified_dterm_filter_multiplier,
            };
            entry.sampleRate = sampleRate;
            entry.segmentSize = segmentSize;
            entry.currentSliders = currentSliders;
            entry.axes = {};
            // analyzeLog(): one computeAxisResult per segment, later segments overwrite earlier ones per axis.
            for (const seg of chirpData.segments) {
                if (!Number.isInteger(seg.axis) || seg.axis < 0 || seg.axis > 2) {
                    entry.error = "unsupported DEBUG_CHIRP axis encoding";
                    break;
                }
                const perPreset = [];
                let axisTf = null;
                for (const pm of bblManifest.presets) {
                    const axisResult = autotune.computeAxisResult(seg, chirpData, sampleRate, segmentSize, currentSliders, pm);
                    if (!axisResult) {
                        break;
                    }
                    axisTf = axisResult.transferFunction;
                    const ol = S.openLoopResponse(axisTf);
                    const rec = recordRecommendation(S, axisTf, ol, currentSliders, pm);
                    for (const k of Object.keys(axisResult.gains.proposed)) {
                        check(same(axisResult.gains.proposed[k], rec.proposed[k]), `computeAxisResult proposed ${k}`);
                    }
                    const { proposed: _p, ...gainsSummary } = axisResult.gains;
                    rec.gains = gainsSummary;
                    perPreset.push(rec);
                }
                if (!axisTf) {
                    entry.axes[seg.axis] = { skipped: "len < segmentSize", startIdx: seg.startIdx, endIdx: seg.endIdx };
                    continue;
                }
                const ol = S.openLoopResponse(axisTf);
                entry.axes[seg.axis] = {
                    startIdx: seg.startIdx,
                    endIdx: seg.endIdx,
                    transferFunction: tfArrays(axisTf),
                    openLoop: { magnitude: ol.magnitude, phase: ol.phase, startIndex: ol.startIndex },
                    recommendations: perPreset,
                };
            }
            bblOut.push(entry);
        }

        const body = JSON.stringify({ provenance, presets: bblManifest.presets, synthetic: syntheticOut, bbl: bblOut }, jsonReplacer) + "\n";
        writeFileSync(join(FIXTURES, "upstream_autotune_reference.json.gz"), gzipSync(Buffer.from(body), { level: 9 }));
        const recs = syntheticOut.reduce((n, c) => n + c.recommendations.length, 0)
            + bblOut.reduce((n, c) => n + Object.values(c.axes).reduce((m, a) => m + (a.recommendations?.length ?? 0), 0), 0);
        console.log(`autotune reference: ${syntheticOut.length} synthetic TFs, ${bblOut.length} BBL logs, ${recs} recommendGains vectors`);
    } finally {
        rmSync(stage, { recursive: true, force: true });
    }
}

await main();
