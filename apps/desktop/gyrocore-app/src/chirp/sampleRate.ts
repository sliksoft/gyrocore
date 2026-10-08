/**
 * CHIRP sample-rate resolution and timestamp-spacing analysis.
 * Port of core/gyrocore/chirp/sample_rate.py (WU6/WU7 policy, unchanged).
 */

import { npMedian, npRint } from "./numeric";
import type { SampleRateEvidence, TimestampSpacing } from "./types";

export const MISMATCH_TOLERANCE_FRACTION = 0.05;
const MIN_TIMESTAMP_DELTAS = 8;
export const SPACING_UNIFORM_TOLERANCE_FRACTION = 0.1;
export const SPACING_MIN_UNIFORM_FRACTION = 0.9;
export const SPACING_GAP_FACTOR = 1.5;

const finitePositive = (v: number | null): v is number => v !== null && Number.isFinite(v) && v > 0;

/** Mirror of Configurator `useAutotune.computeSampleRate` (ignores PNum). */
export function upstreamAutotuneSampleRateHz(
  looptimeUs: number | null,
  pidProcessDenom: number | null,
  pDenom: number | null,
): number {
  // Python `float(x or default)`: 0 / None fall back to the upstream default.
  const lt = looptimeUs || 125;
  const pd = pidProcessDenom || 1;
  const bb = pDenom || 1;
  return 1_000_000.0 / (lt * pd * bb);
}

function tryHeaderRate(lt: number | null, pd: number | null, num: number | null, den: number | null): number | null {
  if (lt === null || pd === null || num === null || den === null) return null;
  if (![lt, pd, num, den].every(finitePositive)) return null;
  return (1_000_000.0 * num) / (lt * pd * den);
}

function tryPidRate(lt: number | null, pd: number | null): number | null {
  if (lt === null || pd === null) return null;
  if (!(Number.isFinite(lt) && Number.isFinite(pd) && lt > 0 && pd > 0)) return null;
  return 1_000_000.0 / (lt * pd);
}

function positiveFiniteDeltas(ts: Float64Array): { dts: Float64Array; finite: number; positive: Float64Array } {
  const n = ts.length;
  const dts = new Float64Array(Math.max(0, n - 1));
  for (let i = 1; i < n; i++) dts[i - 1] = ts[i]! - ts[i - 1]!;
  let finite = 0;
  const pos: number[] = [];
  for (const d of dts) {
    if (Number.isFinite(d)) {
      finite++;
      if (d > 0) pos.push(d);
    }
  }
  return { dts, finite, positive: Float64Array.from(pos) };
}

export function estimateTimestampRateHz(ts: Float64Array, minDeltas = MIN_TIMESTAMP_DELTAS): number | null {
  if (ts.length < 2) return null;
  const { positive } = positiveFiniteDeltas(ts);
  if (positive.length < minDeltas && positive.length < 3) return null;
  const median = npMedian(positive);
  if (!Number.isFinite(median) || median <= 0) return null;
  const rate = 1_000_000.0 / median;
  return Number.isFinite(rate) && rate > 0 ? rate : null;
}

export function analyzeTimestampSpacing(ts: Float64Array): TimestampSpacing {
  const { dts, finite, positive } = positiveFiniteDeltas(ts);
  const nonPositive = finite - positive.length + (dts.length - finite);
  if (positive.length === 0) {
    return {
      delta_count: dts.length,
      median_dt_us: null,
      min_dt_us: null,
      max_dt_us: null,
      uniform_fraction: 0.0,
      gap_count: 0,
      missing_samples_estimate: 0,
      missing_fraction: 0.0,
      max_gap_samples: 0,
      non_positive_deltas: nonPositive,
      uniform: false,
    };
  }
  const median = npMedian(positive);
  let within = 0;
  let gapCount = 0;
  let missing = 0;
  let maxGap = 0;
  let mn = Infinity;
  let mx = -Infinity;
  for (const d of positive) {
    if (Math.abs(d - median) <= SPACING_UNIFORM_TOLERANCE_FRACTION * median) within++;
    if (d > SPACING_GAP_FACTOR * median) {
      gapCount++;
      const m = Math.max(npRint(d / median) - 1, 0);
      missing += m;
      if (m > maxGap) maxGap = m;
    }
    if (d < mn) mn = d;
    if (d > mx) mx = d;
  }
  const uniformFraction = within / dts.length;
  const expected = ts.length + missing;
  return {
    delta_count: dts.length,
    median_dt_us: median,
    min_dt_us: mn,
    max_dt_us: mx,
    uniform_fraction: uniformFraction,
    gap_count: gapCount,
    missing_samples_estimate: missing,
    missing_fraction: expected > 0 ? missing / expected : 0.0,
    max_gap_samples: maxGap,
    non_positive_deltas: nonPositive,
    uniform: uniformFraction >= SPACING_MIN_UNIFORM_FRACTION && nonPositive === 0,
  };
}

export function resolveChirpSampleRate(opts: {
  looptimeUs: number | null;
  pidProcessDenom: number | null;
  frameIntervalPNum: number | null;
  frameIntervalPDenom: number | null;
  timestampsUs: Float64Array | null;
}): SampleRateEvidence {
  const { looptimeUs: lt, pidProcessDenom: pd, frameIntervalPNum: num, frameIntervalPDenom: den } = opts;
  const warnings: string[] = [];
  const pidRate = tryPidRate(lt, pd);
  const headerRate = tryHeaderRate(lt, pd, num, den);
  if (headerRate !== null && num !== null && den !== null && num > den) {
    warnings.push("frame_interval_p_num_exceeds_denom");
  }
  let tsRate: number | null = null;
  if (opts.timestampsUs) {
    tsRate = estimateTimestampRateHz(opts.timestampsUs);
    if (tsRate === null && opts.timestampsUs.length >= 2) warnings.push("timestamp_rate_unreliable");
  }
  if (num === null || den === null) {
    if (lt !== null && pd !== null) warnings.push("p_interval_metadata_missing");
  }
  if (lt === null) warnings.push("looptime_missing");
  if (pd === null) warnings.push("pid_process_denom_missing");

  const base = {
    pid_loop_rate_hz: pidRate,
    frame_interval_p_num: num === null ? null : Math.trunc(num),
    frame_interval_p_denom: den === null ? null : Math.trunc(den),
    looptime_us: lt,
    pid_process_denom: pd,
  };
  if (headerRate === null && tsRate === null) {
    return {
      ...base,
      blackbox_configured_rate_hz: headerRate,
      header_rate_hz: headerRate,
      timestamp_rate_hz: tsRate,
      effective_rate_hz: null,
      source: "unknown",
      status: "unusable",
      difference_percent: null,
      confidence: 0.0,
      warnings: [...warnings, "no_trustworthy_sample_rate"],
      usable: false,
    };
  }
  if (headerRate === null) {
    return {
      ...base,
      blackbox_configured_rate_hz: null,
      header_rate_hz: null,
      timestamp_rate_hz: tsRate,
      effective_rate_hz: tsRate,
      source: "timestamp",
      status: "timestamp_only",
      difference_percent: null,
      confidence: 0.7,
      warnings: [...warnings, "derived_from_timestamps_only"],
      usable: true,
    };
  }
  if (tsRate === null) {
    return {
      ...base,
      blackbox_configured_rate_hz: headerRate,
      header_rate_hz: headerRate,
      timestamp_rate_hz: null,
      effective_rate_hz: headerRate,
      source: "header",
      status: "header_only",
      difference_percent: null,
      confidence: 0.75,
      warnings: [...warnings, "no_timestamp_crosscheck"],
      usable: true,
    };
  }
  const rel = Math.abs(headerRate - tsRate) / tsRate;
  const diffPct = tsRate === 0 ? Infinity : (Math.abs(headerRate - tsRate) / Math.abs(tsRate)) * 100.0;
  if (rel <= MISMATCH_TOLERANCE_FRACTION) {
    return {
      ...base,
      blackbox_configured_rate_hz: headerRate,
      header_rate_hz: headerRate,
      timestamp_rate_hz: tsRate,
      effective_rate_hz: headerRate,
      source: "header_confirmed",
      status: "ok",
      difference_percent: diffPct,
      confidence: 0.95,
      warnings,
      usable: true,
    };
  }
  return {
    ...base,
    blackbox_configured_rate_hz: headerRate,
    header_rate_hz: headerRate,
    timestamp_rate_hz: tsRate,
    effective_rate_hz: tsRate,
    source: "timestamp",
    status: "mismatch",
    difference_percent: diffPct,
    confidence: 0.6,
    warnings: [...warnings, "header_timestamp_rate_mismatch", "effective_rate_from_timestamps_due_to_mismatch"],
    usable: true,
  };
}
