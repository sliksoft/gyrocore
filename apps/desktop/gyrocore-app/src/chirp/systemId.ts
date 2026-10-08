/**
 * Welch transfer function, sensitivity and step response — port of
 * core/gyrocore/chirp/system_id.py (itself a port of Betaflight Configurator
 * `spectral_analysis.ts`). Conventions are identical to the reference:
 *
 * - symmetric Hann `0.5 * (1 - cos(2*pi*i / (size - 1)))`
 * - unnormalized DFT; one-sided bins k = 0..floor(seg/2), f = k*fs/seg
 * - Sxy = conj(X)*Y summed over segments; H = Sxy / Sxx
 * - magnitude 20*log10|H| dB; phase atan2 degrees; coherence |Sxy|^2/(Sxx*Syy)
 * - bins with Sxx < 1e-20: H = 0, magnitude -inf, phase 0, coherence 0
 * - hop Math.round(seg*(1-overlap)); segments max(1, floor((N-seg)/hop)+1)
 *
 * The spectrogram and open-loop helpers are not ported: the pipeline does not
 * emit them in its result contract (spectrogram is off by default).
 */

import { complexFftInPlace, realFft } from "./fft";
import { jsRound } from "./numeric";
import type { StepResponseResult, TransferFunctionResult } from "./types";

export const SXX_FLOOR = 1e-20;
export const COHERENCE_DENOM_FLOOR = 1e-30;
export const CROSSOVER_COHERENCE_MIN = 0.5;
export const SENSITIVITY_COHERENCE_MIN = 0.3;
export const SENSITIVITY_MAX_HZ = 500.0;
export const STEP_RESPONSE_MAX_MS = 100.0;

export type WelchSpectra = {
  sxx: Float64Array;
  syy: Float64Array;
  sxyRe: Float64Array;
  sxyIm: Float64Array;
  numSegments: number;
  segmentSize: number;
  hopSize: number;
};

export function hanningWindow(size: number): Float64Array {
  if (size < 2) throw new Error("Hanning window size must be >= 2");
  const w = new Float64Array(size);
  for (let i = 0; i < size; i++) w[i] = 0.5 * (1.0 - Math.cos((2.0 * Math.PI * i) / (size - 1)));
  return w;
}

function nextPow2(n: number): number {
  let p = 1;
  while (p < n) p <<= 1;
  return p;
}

function clampSegmentSize(segmentSize: number, n: number): number {
  if (segmentSize <= n) return segmentSize;
  let fit = nextPow2(n);
  if (fit > n) fit >>= 1;
  return Math.max(fit, 4);
}

/** `useAutotune.chooseSegmentSize`: smallest pow2 >= 256 with seg >= rate/2, capped at 4096. */
export function chooseSegmentSize(sampleRateHz: number): number {
  let seg = 256;
  while (seg < sampleRateHz * 0.5) seg <<= 1;
  return Math.min(seg, 4096);
}

export function welchSpectra(x: Float64Array, y: Float64Array, segmentSize = 1024, overlap = 0.5): WelchSpectra {
  if (x.length !== y.length) throw new Error("Input and output arrays must be the same length");
  const n = x.length;
  if (n < 4) throw new Error("Need at least 4 samples to compute a transfer function");
  const seg = clampSegmentSize(segmentSize, n);
  const hop = Math.max(1, jsRound(seg * (1.0 - overlap)));
  const numSegments = Math.max(1, Math.floor((n - seg) / hop) + 1);
  const numBins = Math.floor(seg / 2) + 1;
  const window = hanningWindow(seg);
  const sxx = new Float64Array(numBins);
  const syy = new Float64Array(numBins);
  const sxyRe = new Float64Array(numBins);
  const sxyIm = new Float64Array(numBins);
  const xb = new Float64Array(seg);
  const yb = new Float64Array(seg);
  for (let s = 0; s < numSegments; s++) {
    const off = s * hop;
    for (let i = 0; i < seg; i++) {
      // numpy slices past the end are short; rfft(n=seg) zero-pads.
      xb[i] = off + i < n ? x[off + i]! * window[i]! : 0;
      yb[i] = off + i < n ? y[off + i]! * window[i]! : 0;
    }
    const X = realFft(xb);
    const Y = realFft(yb);
    for (let k = 0; k < numBins; k++) {
      const xr = X.re[k]!;
      const xi = X.im[k]!;
      const yr = Y.re[k]!;
      const yi = Y.im[k]!;
      sxx[k] = sxx[k]! + (xr * xr + xi * xi);
      syy[k] = syy[k]! + (yr * yr + yi * yi);
      sxyRe[k] = sxyRe[k]! + (xr * yr + xi * yi);
      sxyIm[k] = sxyIm[k]! + (-xi * yr + xr * yi);
    }
  }
  return { sxx, syy, sxyRe, sxyIm, numSegments, segmentSize: seg, hopSize: hop };
}

export type TransferFunction = TransferFunctionResult & { spectra: WelchSpectra };

export function transferFunctionFromSpectra(sp: WelchSpectra, sampleRateHz: number): TransferFunction {
  if (!(sampleRateHz > 0) || !Number.isFinite(sampleRateHz)) throw new Error("sample_rate_hz must be finite and > 0");
  const nb = sp.sxx.length;
  const frequencies = new Float64Array(nb);
  const hRe = new Float64Array(nb);
  const hIm = new Float64Array(nb);
  const mag = new Float64Array(nb);
  const phase = new Float64Array(nb);
  const coh = new Float64Array(nb);
  const df = sampleRateHz / sp.segmentSize;
  for (let k = 0; k < nb; k++) {
    frequencies[k] = k * df;
    const sxx = sp.sxx[k]!;
    const sre = sp.sxyRe[k]!;
    const sim = sp.sxyIm[k]!;
    if (sxx >= SXX_FLOOR) {
      const a = sre / sxx;
      const b = sim / sxx;
      hRe[k] = a;
      hIm[k] = b;
      mag[k] = 20.0 * Math.log10(Math.hypot(a, b));
      phase[k] = Math.atan2(b, a) * (180.0 / Math.PI);
      const denom = sxx * sp.syy[k]!;
      coh[k] = denom > COHERENCE_DENOM_FLOOR ? (sre * sre + sim * sim) / denom : 0.0;
    } else {
      mag[k] = -Infinity;
    }
  }
  return {
    segment_size: sp.segmentSize,
    num_segments: sp.numSegments,
    sample_rate_hz: sampleRateHz,
    frequencies_hz: frequencies,
    h_real: hRe,
    h_imag: hIm,
    magnitude_db: mag,
    phase_deg: phase,
    coherence: coh,
    spectra: sp,
  };
}

export function welchTransferFunction(
  x: Float64Array,
  y: Float64Array,
  sampleRateHz: number,
  segmentSize = 1024,
  overlap = 0.5,
): TransferFunction {
  if (!(sampleRateHz > 0) || !Number.isFinite(sampleRateHz)) throw new Error("sample_rate_hz must be finite and > 0");
  return transferFunctionFromSpectra(welchSpectra(x, y, segmentSize, overlap), sampleRateHz);
}

/** `computeSensitivity` peak: max 20log10|1-T| over 0 < f < 500 Hz with coherence >= 0.3. */
export function sensitivityPeakDb(tf: TransferFunctionResult): number {
  let peak = -Infinity;
  let any = false;
  for (let k = 0; k < tf.frequencies_hz.length; k++) {
    const f = tf.frequencies_hz[k]!;
    if (!(f > 0 && f < SENSITIVITY_MAX_HZ && tf.coherence[k]! >= SENSITIVITY_COHERENCE_MIN)) continue;
    const m = Math.hypot(1.0 - tf.h_real[k]!, -tf.h_imag[k]!);
    const db = m > 1e-20 ? 20.0 * Math.log10(m > 0 ? m : 1.0) : -Infinity;
    if (!any || db > peak) peak = db;
    any = true;
  }
  return any ? peak : -Infinity;
}

function stepMetrics(timeMs: Float64Array, response: Float64Array): [number, number, number] {
  const n = response.length;
  if (n < 2) return [0, 0, 0];
  const tail = Math.max(1, Math.floor(n * 0.9));
  let acc = 0;
  for (let i = tail; i < n; i++) acc += response[i]!;
  const ss = acc / (n - tail);
  if (Math.abs(ss) < 1e-10) return [0, 0, 0];
  let mx = -Infinity;
  for (const v of response) if (v > mx) mx = v;
  const raw = ((mx - ss) / ss) * 100.0;
  const overshoot = Number.isFinite(raw) ? Math.max(0.0, raw) : 0.0;
  let rise = 0.0;
  let start: number | null = null;
  for (let i = 0; i < n; i++) {
    if (start === null && response[i]! >= 0.1 * ss) start = timeMs[i]!;
    if (response[i]! >= 0.9 * ss) {
      rise = start === null ? 0.0 : Math.max(0.0, timeMs[i]! - start);
      break;
    }
  }
  let settle = 0.0;
  const band = 0.02 * Math.abs(ss);
  for (let i = n - 1; i >= 0; i--) {
    if (Math.abs(response[i]! - ss) > band) {
      settle = i < n - 1 ? timeMs[i + 1]! : timeMs[i]!;
      break;
    }
  }
  return [overshoot, rise, settle];
}

/** `computeStepResponse`: IFFT of Hermitian H, cumulative sum, DC-normalized, first 100 ms. */
export function computeStepResponse(tf: TransferFunctionResult, sampleRateHz: number, segmentSize: number): StepResponseResult {
  const nb = tf.h_real.length;
  const n = segmentSize;
  const re = new Float64Array(n);
  const im = new Float64Array(n);
  const kLo = Math.min(nb, n);
  for (let k = 0; k < kLo; k++) {
    re[k] = tf.h_real[k]!;
    im[k] = tf.h_imag[k]!;
  }
  for (let k = nb; k < n; k++) {
    re[k] = tf.h_real[n - k]!;
    im[k] = -tf.h_imag[n - k]!;
  }
  complexFftInPlace(re, im, true);
  const half = n >> 1;
  const step = new Float64Array(half);
  let acc = 0;
  for (let i = 0; i < half; i++) {
    acc += re[i]! / n;
    step[i] = acc;
  }
  const dc = Math.hypot(tf.h_real[0]!, tf.h_imag[0]!);
  if (dc > 1e-10) for (let i = 0; i < half; i++) step[i] = step[i]! / dc;
  const dt = 1000.0 / sampleRateHz;
  let display = half;
  for (let i = 0; i < half; i++) {
    if (i * dt > STEP_RESPONSE_MAX_MS) {
      display = i;
      break;
    }
  }
  const timeMs = new Float64Array(display);
  for (let i = 0; i < display; i++) timeMs[i] = i * dt;
  const response = step.slice(0, display);
  const [overshoot, rise, settle] = stepMetrics(timeMs, response);
  return { overshoot_pct: overshoot, rise_time_ms: rise, settling_time_ms: settle, time_ms: timeMs, response };
}
