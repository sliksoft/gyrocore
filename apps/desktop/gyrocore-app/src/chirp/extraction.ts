/**
 * CHIRP segment extraction — port of core/gyrocore/chirp/extraction.py
 * (upstream `parseChirpLog` sample collection + `analyzeLog` last-segment-wins).
 */

import { BOXCHIRP_BIT, REQUIRED_FIELDS, type ChirpFrames } from "./frames";
import {
  chirpFrequencyRangeHz,
  highResolutionScale,
  validateChirpDebugMode,
  type ChirpSysConfig,
} from "./sysconfig";
import { AXIS_NAMES, type ChirpExtractionDict, type ChirpSegmentInfo } from "./types";

export type ChirpExtraction = {
  detected: boolean;
  segments: ChirpSegmentInfo[];
  /** axis -> segment index (a later segment of the same axis replaces an earlier one). */
  selectedByAxis: Map<number, number>;
  /** float32-rounded `value * hiResScale`, concatenated chirp-active samples. */
  setpoint: [Float64Array, Float64Array, Float64Array];
  gyro: [Float64Array, Float64Array, Float64Array];
  timeUs: Float64Array;
  totalFrames: number;
  droppedAxisFrames: number;
  highResolutionScale: number;
  flagGating: ChirpExtractionDict["flag_gating"];
  apiVersion: string | null;
  chirpDebugModeIndex: number | null;
  frequencyRangeHz: [number, number] | null;
  warnings: string[];
  errors: string[];
};

export function axisName(axis: number): string {
  return axis >= 0 && axis < 3 ? AXIS_NAMES[axis]! : `axis${axis}`;
}

function makeSegment(index: number, axis: number, start: number, end: number, timeUs: Float64Array): ChirpSegmentInfo {
  const st = timeUs.length ? timeUs[start]! : NaN;
  const et = timeUs.length ? timeUs[end]! : NaN;
  return {
    index,
    axis,
    axis_name: axisName(axis),
    start_idx: start,
    end_idx: end,
    sample_count: end - start + 1,
    start_time_us: st,
    end_time_us: et,
    duration_s: Math.max(0.0, (et - st) / 1e6),
  };
}

function empty(frames: ChirpFrames | null, kw: Partial<ChirpExtraction>): ChirpExtraction {
  const z = () => new Float64Array(0);
  return {
    detected: false,
    segments: [],
    selectedByAxis: new Map(),
    setpoint: [z(), z(), z()],
    gyro: [z(), z(), z()],
    timeUs: z(),
    totalFrames: frames ? frames.timeUs.length : 0,
    droppedAxisFrames: 0,
    highResolutionScale: 1.0,
    flagGating: "none",
    apiVersion: null,
    chirpDebugModeIndex: null,
    frequencyRangeHz: null,
    warnings: [],
    errors: [],
    ...kw,
  };
}

export function extractChirp(
  frames: ChirpFrames,
  sysconfig: ChirpSysConfig | null,
  opts: { apiVersion?: string | null; requireFlightModeFlags?: boolean } = {},
): ChirpExtraction {
  const warnings = frames.warnings.slice();
  let apiUsed: string | null = null;
  let chirpIndex: number | null = null;
  let scale = 1.0;
  let freqRange: [number, number] | null = null;
  if (sysconfig === null) {
    warnings.push("sysconfig_missing_debug_mode_unverified");
  } else {
    const [api, index, err] = validateChirpDebugMode(sysconfig, opts.apiVersion ?? null);
    apiUsed = api;
    chirpIndex = index;
    if (err) return empty(frames, { apiVersion: api, chirpDebugModeIndex: index, errors: [err], warnings });
    if (sysconfig.field_i_names.length) {
      const missing = REQUIRED_FIELDS.filter((f) => !sysconfig.field_i_names.includes(f));
      if (missing.length) {
        return empty(frames, {
          apiVersion: api,
          chirpDebugModeIndex: index,
          errors: ["missing_required_field:" + missing.join(",")],
          warnings,
        });
      }
    }
    scale = highResolutionScale(sysconfig);
    freqRange = chirpFrequencyRangeHz(sysconfig);
    if (freqRange === null) warnings.push("chirp_frequency_range_missing");
  }

  const flags = frames.flightModeFlags;
  let gating: ChirpExtractionDict["flag_gating"];
  if (flags === null) {
    if (opts.requireFlightModeFlags) return empty(frames, { errors: ["flight_mode_flags_unavailable"], warnings });
    warnings.push("chirp_mode_flag_unavailable_debug_axis_only");
    gating = "debug_axis_only";
  } else {
    gating = "flight_mode_flags";
  }

  const axisCol = frames.debug[1];
  const n = frames.timeUs.length;
  const rows: number[] = [];
  const segBounds: Array<[number, number, number]> = [];
  let active = flags === null;
  let currentAxis = -1;
  let dropped = 0;
  const chirpBit = 1 << BOXCHIRP_BIT;
  const closeSegment = (endIdx: number, axis: number) => {
    const last = segBounds[segBounds.length - 1];
    if (last && last[0] === axis) last[2] = endIdx;
  };

  for (let r = 0; r < n; r++) {
    if (flags !== null) {
      const f = flags[r]!;
      const now = f < 0 ? active : Boolean(f & chirpBit);
      if (now && !active) currentAxis = -1;
      if (!now && active) {
        closeSegment(rows.length - 1, currentAxis);
        currentAxis = -1;
      }
      active = now;
    }
    if (!active) continue;
    const a = axisCol[r]!;
    if (!Number.isFinite(a) || a !== Math.trunc(a) || a < -1 || a > 2) {
      dropped++;
      continue;
    }
    rows.push(r);
    const sampleIdx = rows.length - 1;
    if (a < 0) {
      if (currentAxis >= 0) closeSegment(sampleIdx - 1, currentAxis);
    } else if (a !== currentAxis) {
      if (currentAxis >= 0) closeSegment(sampleIdx - 1, currentAxis);
      segBounds.push([a, sampleIdx, sampleIdx]);
    }
    currentAxis = a;
  }
  if (currentAxis >= 0) closeSegment(rows.length - 1, currentAxis);

  const m = rows.length;
  const pick = (src: Float64Array, s: number) => {
    const out = new Float64Array(m);
    for (let i = 0; i < m; i++) out[i] = Math.fround(src[rows[i]!]! * s);
    return out;
  };
  const timeUs = new Float64Array(m);
  for (let i = 0; i < m; i++) timeUs[i] = frames.timeUs[rows[i]!]!;
  const setpoint: ChirpExtraction["setpoint"] = [
    pick(frames.setpoint[0], scale),
    pick(frames.setpoint[1], scale),
    pick(frames.setpoint[2], scale),
  ];
  const gyro: ChirpExtraction["gyro"] = [
    pick(frames.gyroAdc[0], scale),
    pick(frames.gyroAdc[1], scale),
    pick(frames.gyroAdc[2], scale),
  ];

  const segments = segBounds.map(([axis, start, end], i) => makeSegment(i, axis, start, end, timeUs));
  const selected = new Map<number, number>();
  for (const seg of segments) selected.set(seg.axis, seg.index);
  if (dropped) warnings.push("chirp_axis_out_of_range_frames_dropped");
  if (segments.length > selected.size) warnings.push("repeated_axis_segments_last_selected");
  if (!segments.length) warnings.push("no_chirp_segments_detected");

  return {
    detected: segments.length > 0,
    segments,
    selectedByAxis: selected,
    setpoint,
    gyro,
    timeUs,
    totalFrames: n,
    droppedAxisFrames: dropped,
    highResolutionScale: scale,
    flagGating: gating,
    apiVersion: apiUsed,
    chirpDebugModeIndex: chirpIndex,
    frequencyRangeHz: freqRange,
    warnings,
    errors: [],
  };
}

export function extractionToDict(e: ChirpExtraction): ChirpExtractionDict {
  const selected: ChirpExtractionDict["selected_by_axis"] = {};
  for (const [axis, idx] of [...e.selectedByAxis.entries()].sort((a, b) => a[0] - b[0])) {
    selected[AXIS_NAMES[axis]!] = idx;
  }
  return {
    detected: e.detected,
    segments: e.segments.map((s) => ({ ...s })),
    selected_by_axis: selected,
    sample_count: e.timeUs.length,
    total_frames: e.totalFrames,
    dropped_axis_frames: e.droppedAxisFrames,
    high_resolution_scale: e.highResolutionScale,
    flag_gating: e.flagGating,
    api_version: e.apiVersion,
    chirp_debug_mode_index: e.chirpDebugModeIndex,
    frequency_range_hz: e.frequencyRangeHz ? [e.frequencyRangeHz[0], e.frequencyRangeHz[1]] : null,
    warnings: e.warnings.slice(),
    errors: e.errors.slice(),
  };
}
