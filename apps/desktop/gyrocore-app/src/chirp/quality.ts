/**
 * Analysis-validity gates for CHIRP system identification — port of
 * core/gyrocore/chirp/quality.py. These judge the measurement, not PID / flight
 * safety, and never produce tuning output.
 */

import { npMean } from "./numeric";
import { CROSSOVER_COHERENCE_MIN, SXX_FLOOR, type TransferFunction } from "./systemId";
import type { QualityGate, QualityReport, SampleRateEvidence, TimestampSpacing } from "./types";

export const MIN_WELCH_SEGMENTS = 4;
export const MIN_EXCITATION_RMS = 5.0;
export const MAX_MISSING_SAMPLE_FRACTION = 0.01;
export const USABLE_COHERENCE_MIN = CROSSOVER_COHERENCE_MIN;
export const MIN_MEAN_BAND_COHERENCE = 0.6;
export const MEAN_COHERENCE_BAND_HZ: [number, number] = [5.0, 100.0];
export const MIN_USABLE_BINS = 8;
export const NYQUIST_GUARD_FRACTION = 0.9;
export const DEFAULT_ANALYSIS_BAND_HZ: [number, number] = [5.0, 100.0];

function gate(
  code: string,
  ok: boolean,
  value: number | null,
  threshold: number | null,
  detail = "",
  warn = false,
): QualityGate {
  return { code, passed: ok, severity: warn ? "warning" : "blocking", value, threshold, detail };
}

/** Python `f"{x:g}"` for the finite band edges used in gate details. */
function fmtG(x: number): string {
  if (Number.isInteger(x) && Math.abs(x) < 1e16) return String(x);
  const s = x.toPrecision(6);
  return s.includes("e") ? s : s.replace(/\.?0+$/, "");
}

export function preAnalysisGates(opts: {
  sampleCount: number;
  segmentSize: number | null;
  rate: SampleRateEvidence;
  spacing: TimestampSpacing;
}): QualityGate[] {
  const { rate, spacing } = opts;
  const gates = [
    gate(
      "invalid_sample_rate",
      rate.usable && rate.effective_rate_hz !== null && rate.effective_rate_hz > 0,
      rate.effective_rate_hz,
      null,
      rate.status,
    ),
    gate("non_uniform_sampling", spacing.uniform, spacing.uniform_fraction, 0.9, "timestamp deltas outside +/-10% of the median"),
    gate(
      "excessive_gaps",
      spacing.missing_fraction <= MAX_MISSING_SAMPLE_FRACTION,
      spacing.missing_fraction,
      MAX_MISSING_SAMPLE_FRACTION,
      `${spacing.gap_count} gaps, ~${spacing.missing_samples_estimate} samples missing`,
    ),
    gate("timestamp_gaps_present", spacing.gap_count === 0, spacing.gap_count, 0.0, "", true),
    gate("sample_rate_crosscheck", rate.status === "ok", rate.difference_percent, 5.0, rate.status, true),
  ];
  if (opts.segmentSize !== null) {
    gates.push(
      gate(
        "insufficient_samples",
        opts.sampleCount >= opts.segmentSize,
        opts.sampleCount,
        opts.segmentSize,
        "segment shorter than the Welch segment (upstream skips the axis)",
      ),
    );
  }
  return gates;
}

export function analysisBand(
  chirpRangeHz: [number, number] | null,
  sampleRateHz: number,
): [[number, number], QualityGate[]] {
  const nyquist = sampleRateHz / 2.0;
  const gates: QualityGate[] = [];
  let lo: number;
  let hi: number;
  if (chirpRangeHz === null) {
    [lo, hi] = DEFAULT_ANALYSIS_BAND_HZ;
    gates.push(gate("chirp_band_unknown_default_used", false, null, null, "", true));
  } else {
    [lo, hi] = chirpRangeHz;
    if (hi > NYQUIST_GUARD_FRACTION * nyquist) {
      gates.push(gate("chirp_band_near_nyquist", false, hi, NYQUIST_GUARD_FRACTION * nyquist, "", true));
    }
  }
  hi = Math.min(hi, NYQUIST_GUARD_FRACTION * nyquist);
  return [[lo, hi], gates];
}

export type QualityResult = QualityReport & { usableMask: Uint8Array };

export function postAnalysisReport(opts: {
  gates: QualityGate[];
  tf: TransferFunction | null;
  inputSignal: Float64Array;
  bandHz: [number, number];
}): QualityResult {
  const x = opts.inputSignal;
  let rms = 0.0;
  if (x.length) {
    const mean = npMean(x);
    const sq = new Float64Array(x.length);
    for (let i = 0; i < x.length; i++) {
      const d = x[i]! - mean;
      sq[i] = d * d;
    }
    rms = Math.sqrt(npMean(sq));
  }
  const gates = opts.gates.slice();
  gates.push(gate("insufficient_excitation", rms >= MIN_EXCITATION_RMS, rms, MIN_EXCITATION_RMS, "setpoint RMS"));
  const band = opts.bandHz;
  const tf = opts.tf;
  if (tf === null) return finish(gates, new Uint8Array(0), null, band, null, rms);

  gates.push(
    gate(
      "insufficient_samples",
      tf.num_segments >= MIN_WELCH_SEGMENTS,
      tf.num_segments,
      MIN_WELCH_SEGMENTS,
      "too few Welch segments for a meaningful coherence estimate",
    ),
  );
  const f = tf.frequencies_hz;
  let cohLo = Math.max(MEAN_COHERENCE_BAND_HZ[0], band[0]);
  let cohHi = Math.min(MEAN_COHERENCE_BAND_HZ[1], band[1]);
  if (cohHi <= cohLo) [cohLo, cohHi] = band;
  const cohBins: number[] = [];
  for (let k = 0; k < f.length; k++) if (f[k]! >= cohLo && f[k]! <= cohHi) cohBins.push(tf.coherence[k]!);
  const meanCoh = cohBins.length ? npMean(cohBins) : null;
  gates.push(
    gate(
      "low_coherence",
      meanCoh !== null && meanCoh >= MIN_MEAN_BAND_COHERENCE,
      meanCoh,
      MIN_MEAN_BAND_COHERENCE,
      `mean coherence over ${fmtG(cohLo)}-${fmtG(cohHi)} Hz`,
    ),
  );
  const nyq = tf.sample_rate_hz / 2.0;
  const mask = new Uint8Array(f.length);
  let count = 0;
  let uMin = Infinity;
  let uMax = -Infinity;
  for (let k = 0; k < f.length; k++) {
    const fk = f[k]!;
    const inBand = fk >= band[0] && fk <= band[1] && fk > 0 && fk < nyq;
    if (inBand && tf.spectra.sxx[k]! >= SXX_FLOOR && tf.coherence[k]! >= USABLE_COHERENCE_MIN) {
      mask[k] = 1;
      count++;
      if (fk < uMin) uMin = fk;
      if (fk > uMax) uMax = fk;
    }
  }
  gates.push(gate("unusable_frequency_range", count >= MIN_USABLE_BINS, count, MIN_USABLE_BINS));
  return finish(gates, mask, count ? [uMin, uMax] : null, band, meanCoh, rms);
}

function finish(
  gates: QualityGate[],
  mask: Uint8Array,
  usableRange: [number, number] | null,
  band: [number, number],
  meanCoh: number | null,
  rms: number,
): QualityResult {
  const blocking = gates.filter((g) => g.severity === "blocking");
  let bins = 0;
  for (const v of mask) bins += v;
  return {
    usable: blocking.every((g) => g.passed),
    failed_gates: blocking.filter((g) => !g.passed).map((g) => g.code),
    warning_gates: gates.filter((g) => g.severity === "warning" && !g.passed).map((g) => g.code),
    gates,
    usable_range_hz: usableRange,
    usable_bin_count: bins,
    analysis_band_hz: [band[0], band[1]],
    mean_band_coherence: meanCoh,
    input_rms: rms,
    usableMask: mask,
  };
}
