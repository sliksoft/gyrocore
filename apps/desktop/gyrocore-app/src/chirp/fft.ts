/**
 * Unnormalized float64 DFT for the browser CHIRP port.
 *
 * Convention (identical to the Python reference / upstream `ComplexFFT`):
 * `X[k] = sum_n x[n] * exp(-2j*pi*k*n/N)`; inverse uses `exp(+...)` and is also
 * unnormalized. Power-of-two sizes use an iterative radix-2 transform with
 * directly evaluated twiddles; other sizes fall back to a direct DFT (CHIRP only
 * uses power-of-two Welch segments, so the fallback exists for completeness).
 */

const twiddleCache = new Map<number, { cos: Float64Array; sin: Float64Array }>();

function twiddles(n: number): { cos: Float64Array; sin: Float64Array } {
  let t = twiddleCache.get(n);
  if (!t) {
    const half = n >> 1;
    const cos = new Float64Array(half);
    const sin = new Float64Array(half);
    for (let k = 0; k < half; k++) {
      const a = (2 * Math.PI * k) / n;
      cos[k] = Math.cos(a);
      sin[k] = Math.sin(a);
    }
    t = { cos, sin };
    twiddleCache.set(n, t);
  }
  return t;
}

export function isPow2(n: number): boolean {
  return n > 0 && (n & (n - 1)) === 0;
}

/** In-place complex FFT of (re, im); `inverse` flips the exponent sign. */
export function complexFftInPlace(re: Float64Array, im: Float64Array, inverse = false): void {
  const n = re.length;
  if (n !== im.length || n < 1) throw new Error("fft_size_invalid");
  if (!isPow2(n)) {
    directDft(re, im, inverse);
    return;
  }
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      let t = re[i]!;
      re[i] = re[j]!;
      re[j] = t;
      t = im[i]!;
      im[i] = im[j]!;
      im[j] = t;
    }
  }
  const { cos, sin } = twiddles(n);
  const sign = inverse ? 1 : -1;
  for (let len = 2; len <= n; len <<= 1) {
    const half = len >> 1;
    const step = n / len;
    for (let i = 0; i < n; i += len) {
      for (let k = 0; k < half; k++) {
        const wr = cos[k * step]!;
        const wi = sign * sin[k * step]!;
        const a = i + k;
        const b = a + half;
        const xr = re[b]! * wr - im[b]! * wi;
        const xi = re[b]! * wi + im[b]! * wr;
        re[b] = re[a]! - xr;
        im[b] = im[a]! - xi;
        re[a] = re[a]! + xr;
        im[a] = im[a]! + xi;
      }
    }
  }
}

function directDft(re: Float64Array, im: Float64Array, inverse: boolean): void {
  const n = re.length;
  const sign = inverse ? 1 : -1;
  const outRe = new Float64Array(n);
  const outIm = new Float64Array(n);
  for (let k = 0; k < n; k++) {
    let sr = 0;
    let si = 0;
    for (let t = 0; t < n; t++) {
      const a = (sign * 2 * Math.PI * ((k * t) % n)) / n;
      const c = Math.cos(a);
      const s = Math.sin(a);
      sr += re[t]! * c - im[t]! * s;
      si += re[t]! * s + im[t]! * c;
    }
    outRe[k] = sr;
    outIm[k] = si;
  }
  re.set(outRe);
  im.set(outIm);
}

/** One-sided spectrum (bins 0..floor(n/2)) of real input `x` (length n), like `np.fft.rfft`. */
export function realFft(x: Float64Array): { re: Float64Array; im: Float64Array } {
  const n = x.length;
  const re = Float64Array.from(x);
  const im = new Float64Array(n);
  complexFftInPlace(re, im, false);
  const bins = Math.floor(n / 2) + 1;
  return { re: re.slice(0, bins), im: im.slice(0, bins) };
}
