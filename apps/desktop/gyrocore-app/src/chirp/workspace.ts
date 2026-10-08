/**
 * Browser CHIRP result -> existing UI payloads (`ChirpPayload`, `WorkspacePayload`).
 *
 * `available` is true only for a usable result with non-empty, equal-length
 * magnitude / phase / coherence series: never available=true with empty arrays.
 * Tune, Safety, Compare and CLI stay explicitly not available in the browser.
 */

import type { ChirpPayload, WorkspacePayload } from "@/bridge/types";
import type { NormalizedDecodedLog } from "@/decode/types";
import { primaryUsableAxis } from "./runChirp";
import type { ChirpBrowserAnalysis } from "./types";

const finiteOrNull = (v: number) => (Number.isFinite(v) ? v : null);

export function chirpPayloadFromAnalysis(analysis: ChirpBrowserAnalysis): ChirpPayload {
  const { result, rejection } = analysis;
  const unavailable = (reason: string, detail?: string): ChirpPayload => ({
    available: false,
    status: result.status,
    reason,
    warnings: [...(detail ? [detail] : []), ...result.warnings],
    magnitude: [],
    phase: [],
    coherence: [],
  });
  if (rejection) return unavailable(rejection.code, rejection.detail);
  const ax = primaryUsableAxis(result);
  if (!ax?.transfer_function) return unavailable("chirp_series_empty");

  // Chart the analysed band (chirp range capped at 0.9 Nyquist); outside it H is unexcited.
  const tf = ax.transfer_function;
  const [lo, hi] = ax.quality.analysis_band_hz;
  const magnitude: ChirpPayload["magnitude"] = [];
  const phase: ChirpPayload["phase"] = [];
  const coherence: ChirpPayload["coherence"] = [];
  for (let k = 0; k < tf.frequencies_hz.length; k++) {
    const hz = tf.frequencies_hz[k]!;
    if (hz < lo || hz > hi) continue;
    magnitude.push({ hz, db: finiteOrNull(tf.magnitude_db[k]!) });
    phase.push({ hz, deg: finiteOrNull(tf.phase_deg[k]!) });
    coherence.push({ hz, value: finiteOrNull(tf.coherence[k]!) });
  }
  if (!magnitude.length) return unavailable("chirp_series_empty");

  const sr = ax.sample_rate;
  const usable = ax.quality.usable_range_hz;
  return {
    available: true,
    status: result.status,
    axis: ax.axis_name,
    sample_rate_hz: ax.effective_rate_hz ?? undefined,
    sample_rate_source: sr.source,
    header_vs_timestamp: {
      agree: sr.status !== "mismatch",
      status: sr.status,
      header_rate_hz: sr.header_rate_hz,
      timestamp_rate_hz: sr.timestamp_rate_hz,
      difference_percent: sr.difference_percent,
      confidence: sr.confidence,
    },
    usable_frequency_hz: usable
      ? { min: usable[0], max: usable[1], bins: ax.quality.usable_bin_count, analysis_band_hz: ax.quality.analysis_band_hz }
      : {},
    quality:
      ax.quality.mean_band_coherence != null
        ? `${result.status} · coherence ${ax.quality.mean_band_coherence.toFixed(2)}`
        : result.status,
    segment: {
      index: ax.segment.index,
      start_time_us: ax.segment.start_time_us,
      end_time_us: ax.segment.end_time_us,
      duration_s: ax.segment.duration_s,
      sample_count: ax.segment.sample_count,
      segment_size: ax.segment_size,
      welch_segments: ax.num_segments,
      frames_decoded: analysis.source.framesDecoded,
      input_policy: analysis.source.inputPolicy,
    },
    magnitude,
    phase,
    coherence,
    warnings: [...result.warnings, ...ax.warnings],
  };
}

const NOT_IN_BROWSER = "Not available in the browser yet (Tune / Safety analysis not migrated).";

export function browserChirpWorkspace(opts: {
  analysis: ChirpBrowserAnalysis;
  decoded: NormalizedDecodedLog | null;
  bblName: string;
  cliName: string | null;
}): WorkspacePayload {
  const chirp = chirpPayloadFromAnalysis(opts.analysis);
  const md = opts.decoded?.metadata;
  const flight = opts.decoded?.embedded.flights[opts.analysis.source.logIndex];
  return {
    kind: "gyrocore_browser_workspace",
    demo: false,
    scenario: "browser · CHIRP",
    overview: {
      message: "Browser analysis: CHIRP / system-ID only. Tune, Safety and CLI generation are not available in the browser yet.",
      target: md?.boardInformation,
      betaflight_version: [md?.firmwareType, md?.firmwareVersion].filter(Boolean).join(" ") || undefined,
      craft: md?.craftName,
      log_duration_s: flight?.durationUs != null ? Number((flight.durationUs / 1e6).toFixed(2)) : undefined,
      sample_rate_hz: chirp.sample_rate_hz,
      chirp_detected: chirp.available,
      tune_recommendation: "not available (browser)",
      detected_issues: [],
    },
    analysis: null,
    chirp,
    tune: null,
    safety: null,
    compare: null,
    cli: {
      state: "NOT AVAILABLE",
      authorized: false,
      actionable: false,
      label: "CLI generation is not available in the browser.",
      reasons: [NOT_IN_BROWSER],
    },
    diagnostics: { note: NOT_IN_BROWSER, chirp_timings_ms: opts.analysis.timingsMs },
    blackbox: {
      source: "browser",
      filename: opts.bblName,
      cli_filename: opts.cliName,
      log_index: opts.analysis.source.logIndex,
      log_count: opts.analysis.source.logCount,
      frames_decoded: opts.analysis.source.framesDecoded,
      decoder: opts.analysis.source.decoder,
    },
    controls: {
      fc_apply_button: false,
      msp: false,
      serial: false,
      copy_apply_cli: false,
      copy_rollback_cli: false,
    },
  };
}
