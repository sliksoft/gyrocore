/**
 * NumPy-compatible scalar helpers for the browser CHIRP port.
 *
 * The Python reference (core/gyrocore/chirp) reduces with NumPy; these helpers
 * reproduce the exact summation order so gate values match bit-for-bit:
 * `np.add.reduce` on contiguous float64 runs pairwise summation inside
 * 8192-element buffer blocks and adds the block results sequentially.
 */

const PW_BLOCKSIZE = 128;
const REDUCE_BUFSIZE = 8192;

function pairwise(a: ArrayLike<number>, lo: number, n: number): number {
  if (n < 8) {
    let res = -0;
    for (let i = 0; i < n; i++) res += a[lo + i]!;
    return res;
  }
  if (n <= PW_BLOCKSIZE) {
    const r = [a[lo]!, a[lo + 1]!, a[lo + 2]!, a[lo + 3]!, a[lo + 4]!, a[lo + 5]!, a[lo + 6]!, a[lo + 7]!];
    let i = 8;
    const stop = n - (n % 8);
    for (; i < stop; i += 8) {
      for (let j = 0; j < 8; j++) r[j] = r[j]! + a[lo + i + j]!;
    }
    let res = (r[0]! + r[1]!) + (r[2]! + r[3]!) + ((r[4]! + r[5]!) + (r[6]! + r[7]!));
    for (; i < n; i++) res += a[lo + i]!;
    return res;
  }
  let n2 = Math.floor(n / 2);
  n2 -= n2 % 8;
  return pairwise(a, lo, n2) + pairwise(a, lo + n2, n - n2);
}

/** `float(np.add.reduce(a))` for float64 input. */
export function npSum(a: ArrayLike<number>): number {
  const n = a.length;
  if (n === 0) return 0;
  let res = pairwise(a, 0, Math.min(REDUCE_BUFSIZE, n));
  for (let s = REDUCE_BUFSIZE; s < n; s += REDUCE_BUFSIZE) {
    res += pairwise(a, s, Math.min(REDUCE_BUFSIZE, n - s));
  }
  return res;
}

/** `float(np.mean(a))` (NaN for empty input, as NumPy). */
export function npMean(a: ArrayLike<number>): number {
  return a.length ? npSum(a) / a.length : NaN;
}

/** `float(np.median(a))` for finite float64 input. */
export function npMedian(a: ArrayLike<number>): number {
  const n = a.length;
  if (!n) return NaN;
  const s = Float64Array.from(a).sort();
  const h = n >> 1;
  return n % 2 ? s[h]! : (s[h - 1]! + s[h]!) / 2;
}

/** JavaScript `Math.round` (ties toward +inf) == Python `js_round`. */
export function jsRound(x: number): number {
  return Math.floor(x + 0.5);
}

/** `np.rint`: round half to even. */
export function npRint(x: number): number {
  const f = Math.floor(x);
  const d = x - f;
  if (d > 0.5) return f + 1;
  if (d < 0.5) return f;
  return f % 2 === 0 ? f : f + 1;
}

/** Python `float('nan')`-aware `np.isfinite` for unknown inputs. */
export function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}
