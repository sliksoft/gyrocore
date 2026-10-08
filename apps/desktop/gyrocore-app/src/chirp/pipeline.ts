/**
 * End-to-end browser CHIRP system identification — port of
 * core/gyrocore/chirp/pipeline.py `identify_chirp_system` (analysis only).
 *
 *   frames -> sysConfig -> CHIRP extraction -> per-segment sample-rate
 *   resolution -> Welch H(f) (+ sensitivity / step) -> validity gates
 *
 * No gain recommendation, PID/filter output, MSP write or CLI is produced.
 */

import { extractChirp, extractionToDict, type ChirpExtraction } from "./extraction";
import type { ChirpFrames } from "./frames";
import { analysisBand, postAnalysisReport, preAnalysisGates } from "./quality";
import { analyzeTimestampSpacing, resolveChirpSampleRate, upstreamAutotuneSampleRateHz } from "./sampleRate";
import {
  sampleRateInputs,
  sysConfigToDict,
  upstreamValue,
  validateChirpDebugMode,
  type ChirpSysConfig,
} from "./sysconfig";
import { chooseSegmentSize, computeStepResponse, sensitivityPeakDb, welchTransferFunction } from "./systemId";
import {
  AXIS_NAMES,
  type ChirpAxisResult,
  type ChirpSegmentInfo,
  type ChirpStatus,
  type ChirpSystemIdResult,
} from "./types";

export const WELCH_OVERLAP = 0.5;

export const UPSTREAM_PROVENANCE: Record<string, unknown> = {
  configurator_commit: "a38c4a797a86a580106162653db92af7e14be787",
  blackbox_tools_commit: "f832acf9cd9dbe5ad8220de1a5f4eb4021523d72",
  reference_functions: [
    "chirp_bbl_parser.ts:parseChirpLog",
    "chirp_bbl_parser.ts:validateDebugModeIsChirp",
    "useAutotune.ts:analyzeLog",
    "useAutotune.ts:computeAxisResult",
    "useAutotune.ts:chooseSegmentSize",
    "spectral_analysis.ts:welchTransferFunction",
    "spectral_analysis.ts:computeSensitivity",
    "spectral_analysis.ts:computeStepResponse",
    "spectral_analysis.ts:computeSpectrogram",
    "spectral_analysis.ts:openLoopResponse",
    "fft.ts:ComplexFFT",
  ],
  not_ported: ["spectral_analysis.ts:recommendGains", "useAutotune.ts:applyGains"],
};

function provenance(): Record<string, unknown> {
  return { ...UPSTREAM_PROVENANCE };
}

function errorResult(
  code: string,
  sysconfig: ChirpSysConfig | null,
  extraction: ChirpExtraction | null = null,
  warnings: string[] = [],
): ChirpSystemIdResult {
  return {
    status: "error",
    usable: false,
    detected: Boolean(extraction?.detected),
    analysis_only: true,
    tuning_recommendations: null,
    sysconfig: sysconfig ? sysConfigToDict(sysconfig) : null,
    extraction: extraction ? extractionToDict(extraction) : null,
    axes: {},
    warnings: warnings.slice(),
    errors: [code],
    provenance: provenance(),
  };
}

export function analyzeChirpSegment(
  extraction: ChirpExtraction,
  segment: ChirpSegmentInfo,
  sysconfig: ChirpSysConfig | null,
  opts: { segmentSize?: number | null } = {},
): ChirpAxisResult {
  const lo = segment.start_idx;
  const hi = segment.end_idx + 1;
  const x = extraction.setpoint[segment.axis]!.subarray(lo, hi);
  const y = extraction.gyro[segment.axis]!.subarray(lo, hi);
  const ts = extraction.timeUs.subarray(lo, hi);
  const inputs = sysconfig
    ? sampleRateInputs(sysconfig)
    : { looptimeUs: null, pidProcessDenom: null, frameIntervalPNum: null, frameIntervalPDenom: null };
  const rate = resolveChirpSampleRate({ ...inputs, timestampsUs: ts });
  const spacing = analyzeTimestampSpacing(ts);
  const upstreamRate = upstreamAutotuneSampleRateHz(
    sysconfig ? upstreamValue(sysconfig, "looptime") : null,
    sysconfig ? upstreamValue(sysconfig, "pid_process_denom") : null,
    sysconfig ? upstreamValue(sysconfig, "p_interval_denom") : null,
  );
  const fs = rate.effective_rate_hz;
  const segSize = opts.segmentSize || (fs ? chooseSegmentSize(fs) : null);
  let gates = preAnalysisGates({ sampleCount: segment.sample_count, segmentSize: segSize, rate, spacing });
  let band: [number, number] = [0.0, 0.0];
  if (fs) {
    const [b, bandGates] = analysisBand(extraction.frequencyRangeHz, fs);
    band = b;
    gates = gates.concat(bandGates);
  }
  const canCompute = Boolean(fs) && segSize !== null && segment.sample_count >= segSize;
  const tf = canCompute ? welchTransferFunction(x, y, fs!, segSize!, WELCH_OVERLAP) : null;
  const report = postAnalysisReport({ gates, tf, inputSignal: x, bandHz: band });
  const { usableMask, ...quality } = report;

  const out: ChirpAxisResult = {
    axis: segment.axis,
    axis_name: AXIS_NAMES[segment.axis]!,
    usable: tf !== null && quality.usable,
    segment: { ...segment },
    effective_rate_hz: fs,
    upstream_autotune_rate_hz: upstreamRate,
    sample_rate: rate,
    timestamp_spacing: spacing,
    segment_size: segSize,
    overlap: WELCH_OVERLAP,
    quality,
    warnings: rate.warnings.slice(),
  };
  if (tf) {
    const { spectra: _spectra, ...tfData } = tf;
    out.num_segments = tf.num_segments;
    out.num_bins = tf.frequencies_hz.length;
    out.transfer_function = tfData;
    out.usable_mask = usableMask;
    out.sensitivity_peak_db = sensitivityPeakDb(tf);
    out.step_response = computeStepResponse(tf, fs!, segSize!);
  }
  return out;
}

export function identifyChirpSystem(opts: {
  frames: ChirpFrames;
  sysconfig: ChirpSysConfig | null;
  apiVersion?: string | null;
  axes?: number[] | null;
  segmentSize?: number | null;
  requireFlightModeFlags?: boolean;
}): ChirpSystemIdResult {
  const { frames, sysconfig } = opts;
  if (sysconfig) {
    const [, , err] = validateChirpDebugMode(sysconfig, opts.apiVersion ?? null);
    if (err) return errorResult(err, sysconfig);
  }
  const extraction = extractChirp(frames, sysconfig, {
    apiVersion: opts.apiVersion ?? null,
    requireFlightModeFlags: opts.requireFlightModeFlags ?? false,
  });
  if (extraction.errors.length) return errorResult(extraction.errors[0]!, sysconfig, extraction, extraction.warnings);
  if (!extraction.detected) {
    return {
      status: "unusable",
      usable: false,
      detected: false,
      analysis_only: true,
      tuning_recommendations: null,
      sysconfig: sysconfig ? sysConfigToDict(sysconfig) : null,
      extraction: extractionToDict(extraction),
      axes: {},
      warnings: extraction.warnings.slice(),
      errors: ["no_chirp_segments"],
      provenance: provenance(),
    };
  }

  const wanted = opts.axes ? new Set(opts.axes) : null;
  const results: ChirpAxisResult[] = [];
  for (const [axis, segIndex] of [...extraction.selectedByAxis.entries()].sort((a, b) => a[0] - b[0])) {
    if (wanted && !wanted.has(axis)) continue;
    results.push(analyzeChirpSegment(extraction, extraction.segments[segIndex]!, sysconfig, opts));
  }

  const warnings = extraction.warnings.slice();
  for (const r of results) for (const w of r.quality.warning_gates) warnings.push(`${r.axis_name}:${w}`);
  let status: ChirpStatus;
  if (!results.length || !results.some((r) => r.usable)) status = "unusable";
  else if (
    results.every((r) => r.usable) &&
    !results.some((r) => r.quality.warning_gates.length) &&
    !extraction.warnings.length
  )
    status = "ok";
  else status = "usable_with_warnings";

  const axes: ChirpSystemIdResult["axes"] = {};
  for (const r of results) axes[AXIS_NAMES[r.axis]!] = r;
  return {
    status,
    usable: results.some((r) => r.usable),
    detected: true,
    analysis_only: true,
    tuning_recommendations: null,
    sysconfig: sysconfig ? sysConfigToDict(sysconfig) : null,
    extraction: extractionToDict(extraction),
    axes,
    warnings: [...new Set(warnings)],
    errors: results.flatMap((r) => r.quality.failed_gates.map((c) => `${r.axis_name}:${c}`)),
    provenance: provenance(),
  };
}
