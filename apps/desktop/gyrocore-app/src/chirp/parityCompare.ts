/**
 * Python-reference vs browser CHIRP comparison (CHIRP_BROWSER_WU1 parity gate).
 *
 * Tolerances are fixed up front and match the project's accepted WU7
 * Python-vs-upstream tolerances (tests/core/chirp/test_chirp_wu7_pipeline_parity.py):
 *
 * - structure, strings, booleans, integers, gate pass/fail, warnings, errors,
 *   segment bounds, usable_mask: EXACT
 * - frequency vector, rates, timestamps and every other scalar: rel 1e-12
 * - transfer function, evaluated on bins inside `quality.analysis_band_hz`
 *   (the excited chirp band; outside it Sxx ~ 0 and H = Sxy/Sxx is
 *   FFT-rounding noise):
 *     h_real / h_imag rel 1e-9 (abs floor 1e-12), magnitude_db abs 1e-8 dB,
 *     phase_deg abs 1e-6 deg (wrap-aware), coherence abs 1e-10
 * - sensitivity peak abs 1e-8 dB; step-response metrics abs 1e-7, arrays abs 1e-7
 *
 * All-bin error statistics are reported alongside but are informational.
 */

export const TOLERANCES = {
  scalarRel: 1e-12,
  scalarAbs: 1e-12,
  frequencyRel: 1e-12,
  hRel: 1e-9,
  hAbsFloor: 1e-12,
  magnitudeDbAbs: 1e-8,
  phaseDegAbs: 1e-6,
  coherenceAbs: 1e-10,
  sensitivityDbAbs: 1e-8,
  stepAbs: 1e-7,
} as const;

export type SeriesStats = {
  bins: number;
  maxAbs: number;
  meanAbs: number;
  maxRel: number | null;
  correlation: number | null;
};

export type ParityReport = {
  mismatches: string[];
  series: Record<string, { band: SeriesStats; all: SeriesStats }>;
};

/** Typed arrays -> arrays, Uint8Array masks -> booleans, non-finite -> null (Python golden encoding). */
export function toPlain(v: unknown, key = ""): unknown {
  if (v instanceof Uint8Array) return Array.from(v, (b) => b === 1);
  if (ArrayBuffer.isView(v)) return Array.from(v as Float64Array, (x) => (Number.isFinite(x) ? x : null));
  if (typeof v === "number") return Number.isFinite(v) ? v : null;
  if (Array.isArray(v)) return v.map((x) => toPlain(x, key));
  if (v && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, x] of Object.entries(v)) if (x !== undefined) out[k] = toPlain(x, k);
    return out;
  }
  return v;
}

function wrapDeg(d: number): number {
  let x = d % 360;
  if (x > 180) x -= 360;
  if (x < -180) x += 360;
  return Math.abs(x);
}

function stats(ref: number[], got: number[], idx: number[], diff: (a: number, b: number) => number): SeriesStats {
  let maxAbs = 0;
  let sumAbs = 0;
  let maxRel: number | null = null;
  let n = 0;
  let sa = 0;
  let sb = 0;
  for (const i of idx) {
    const a = ref[i]!;
    const b = got[i]!;
    if (a === null || b === null) continue;
    const d = diff(a, b);
    maxAbs = Math.max(maxAbs, d);
    sumAbs += d;
    if (Math.abs(a) > 1e-12) maxRel = Math.max(maxRel ?? 0, d / Math.abs(a));
    sa += a;
    sb += b;
    n++;
  }
  let correlation: number | null = null;
  if (n > 1) {
    const ma = sa / n;
    const mb = sb / n;
    let cov = 0;
    let va = 0;
    let vb = 0;
    for (const i of idx) {
      const a = ref[i]!;
      const b = got[i]!;
      if (a === null || b === null) continue;
      cov += (a - ma) * (b - mb);
      va += (a - ma) ** 2;
      vb += (b - mb) ** 2;
    }
    correlation = va > 0 && vb > 0 ? cov / Math.sqrt(va * vb) : va === 0 && vb === 0 ? 1 : null;
  }
  return { bins: n, maxAbs, meanAbs: n ? sumAbs / n : 0, maxRel, correlation };
}

const TF_SERIES: Record<string, { diff: (a: number, b: number) => number; ok: (a: number, b: number) => boolean }> = {
  h_real: {
    diff: (a, b) => Math.abs(a - b),
    ok: (a, b) => Math.abs(a - b) <= Math.max(TOLERANCES.hRel * Math.abs(a), TOLERANCES.hAbsFloor),
  },
  h_imag: {
    diff: (a, b) => Math.abs(a - b),
    ok: (a, b) => Math.abs(a - b) <= Math.max(TOLERANCES.hRel * Math.abs(a), TOLERANCES.hAbsFloor),
  },
  magnitude_db: { diff: (a, b) => Math.abs(a - b), ok: (a, b) => Math.abs(a - b) <= TOLERANCES.magnitudeDbAbs },
  phase_deg: { diff: (a, b) => wrapDeg(a - b), ok: (a, b) => wrapDeg(a - b) <= TOLERANCES.phaseDegAbs },
  coherence: { diff: (a, b) => Math.abs(a - b), ok: (a, b) => Math.abs(a - b) <= TOLERANCES.coherenceAbs },
};

function scalarClose(a: number, b: number, rel: number, abs: number): boolean {
  return a === b || Math.abs(a - b) <= Math.max(rel * Math.abs(a), abs);
}

function compareTf(path: string, ref: Record<string, unknown>, got: Record<string, unknown>, band: [number, number], report: ParityReport) {
  const f = ref.frequencies_hz as number[];
  const gf = got.frequencies_hz as number[];
  if (!Array.isArray(f) || !Array.isArray(gf) || f.length !== gf.length) {
    report.mismatches.push(`${path}.frequencies_hz length ${f?.length} vs ${gf?.length}`);
    return;
  }
  for (let i = 0; i < f.length; i++) {
    if (!scalarClose(f[i]!, gf[i]!, TOLERANCES.frequencyRel, 0)) {
      report.mismatches.push(`${path}.frequencies_hz[${i}] ${f[i]} vs ${gf[i]}`);
      break;
    }
  }
  const all = f.map((_, i) => i);
  const inBand = all.filter((i) => f[i]! >= band[0] && f[i]! <= band[1]);
  for (const [name, rule] of Object.entries(TF_SERIES)) {
    const r = ref[name] as number[];
    const g = got[name] as number[];
    if (!Array.isArray(r) || !Array.isArray(g) || r.length !== g.length) {
      report.mismatches.push(`${path}.${name} length ${r?.length} vs ${g?.length}`);
      continue;
    }
    for (const i of inBand) {
      if ((r[i] === null) !== (g[i] === null)) {
        report.mismatches.push(`${path}.${name}[${i}] null mismatch ${r[i]} vs ${g[i]}`);
        break;
      }
      if (r[i] !== null && !rule.ok(r[i]!, g[i]!)) {
        report.mismatches.push(`${path}.${name}[${i}] (${f[i]} Hz) ${r[i]} vs ${g[i]}`);
        break;
      }
    }
    report.series[`${path}.${name}`] = {
      band: stats(r, g, inBand, rule.diff),
      all: stats(r, g, all, rule.diff),
    };
  }
  for (const k of new Set([...Object.keys(ref), ...Object.keys(got)])) {
    if (k === "frequencies_hz" || k in TF_SERIES) continue;
    compareValue(`${path}.${k}`, ref[k], got[k], report);
  }
}

function compareValue(path: string, ref: unknown, got: unknown, report: ParityReport, band?: [number, number]): void {
  const leaf = path.slice(path.lastIndexOf(".") + 1);
  if (leaf === "transfer_function" && ref && got && band) {
    compareTf(path, ref as Record<string, unknown>, got as Record<string, unknown>, band, report);
    return;
  }
  if (typeof ref === "number" && typeof got === "number") {
    let ok: boolean;
    if (leaf === "sensitivity_peak_db") ok = Math.abs(ref - got) <= TOLERANCES.sensitivityDbAbs;
    else if (path.includes(".step_response.")) ok = Math.abs(ref - got) <= TOLERANCES.stepAbs;
    else ok = scalarClose(ref, got, TOLERANCES.scalarRel, TOLERANCES.scalarAbs);
    if (!ok) report.mismatches.push(`${path}: ${ref} vs ${got}`);
    return;
  }
  if (Array.isArray(ref) && Array.isArray(got)) {
    if (ref.length !== got.length) {
      report.mismatches.push(`${path}: length ${ref.length} vs ${got.length}`);
      return;
    }
    const isStep = path.endsWith(".step_response.response") || path.endsWith(".step_response.time_ms");
    for (let i = 0; i < ref.length; i++) {
      if (isStep && typeof ref[i] === "number" && typeof got[i] === "number") {
        if (Math.abs((ref[i] as number) - (got[i] as number)) > TOLERANCES.stepAbs) {
          report.mismatches.push(`${path}[${i}]: ${ref[i]} vs ${got[i]}`);
          break;
        }
        continue;
      }
      const before = report.mismatches.length;
      compareValue(`${path}[${i}]`, ref[i], got[i], report, band);
      if (report.mismatches.length > before) break;
    }
    return;
  }
  if (ref && got && typeof ref === "object" && typeof got === "object") {
    const r = ref as Record<string, unknown>;
    const g = got as Record<string, unknown>;
    const keys = new Set([...Object.keys(r), ...Object.keys(g)]);
    // Per-axis band for the transfer-function rule.
    const quality = r.quality as { analysis_band_hz?: [number, number] } | undefined;
    const axisBand = quality?.analysis_band_hz ?? band;
    for (const k of keys) {
      if (!(k in r)) report.mismatches.push(`${path}.${k}: missing in reference`);
      else if (!(k in g)) report.mismatches.push(`${path}.${k}: missing in browser`);
      else compareValue(`${path}.${k}`, r[k], g[k], report, axisBand);
    }
    return;
  }
  if (ref !== got) report.mismatches.push(`${path}: ${JSON.stringify(ref)} vs ${JSON.stringify(got)}`);
}

export function compareChirpResults(reference: unknown, browser: unknown): ParityReport {
  const report: ParityReport = { mismatches: [], series: {} };
  compareValue("result", reference, toPlain(browser), report);
  return report;
}
