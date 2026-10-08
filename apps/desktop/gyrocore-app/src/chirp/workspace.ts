/**
 * Browser CHIRP result -> existing UI payloads (`ChirpPayload`, `WorkspacePayload`).
 *
 * `available` is true only for a usable result with non-empty, equal-length
 * magnitude / phase / coherence series: never available=true with empty arrays.
 * Tune, Safety, Compare and CLI apply stay explicitly not available in the browser.
 */

import type { ChirpPayload, WorkspacePayload } from "@/bridge/types";
import type { NormalizedDecodedLog } from "@/decode/types";
import { featureAvailability, type FeatureCapabilities } from "@/runtime/capabilities";
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

export const NOT_IN_BROWSER =
  "Not available in the browser yet: general analysis, Tune, Safety, Compare and CLI apply have not been migrated from the Python Core.";

/** Selected CLI dump context, read locally (the dump text itself is not kept in the workspace). */
export type CliContext = {
  filename: string;
  size_bytes: number;
  lines: number;
  firmware?: string;
  board_name?: string;
  craft_name?: string;
  debug_mode?: string;
};

export function cliContextFromText(filename: string, sizeBytes: number, text: string): CliContext {
  const lines = text.split(/\r?\n/);
  const find = (re: RegExp) => {
    for (const line of lines) {
      const m = re.exec(line.trim());
      if (m) return m[1]!.trim();
    }
    return undefined;
  };
  const ctx: CliContext = { filename, size_bytes: sizeBytes, lines: lines.filter((l) => l.trim()).length };
  const firmware = find(/^#\s*((?:Betaflight|INAV|Emuflight)\b.*)$/i);
  const board = find(/^board_name\s+(\S+)/i);
  const craft = find(/^set\s+craft_name\s*=\s*(.*)$/i);
  const debug = find(/^set\s+debug_mode\s*=\s*(\S+)/i);
  if (firmware) ctx.firmware = firmware;
  if (board) ctx.board_name = board;
  if (craft) ctx.craft_name = craft;
  if (debug) ctx.debug_mode = debug;
  return ctx;
}

/**
 * Real browser/PWA workspace from the session's decode of the selected log and its
 * CHIRP result. Everything not migrated stays null / NOT AVAILABLE: no demo, no
 * Tauri, no fabricated Tune / Safety / Compare / CLI output.
 */
export function browserWorkspace(opts: {
  decoded: NormalizedDecodedLog;
  analysis: ChirpBrowserAnalysis;
  bbl: { name: string; sizeBytes: number };
  cli: CliContext;
  features: FeatureCapabilities;
}): WorkspacePayload {
  const { decoded, analysis } = opts;
  const chirp = chirpPayloadFromAnalysis(analysis);
  const md = decoded.metadata;
  const logIndex = analysis.source.logIndex;
  if (decoded.embedded.selectedIndex !== logIndex) throw new Error(`workspace_log_mismatch:${decoded.embedded.selectedIndex}:${logIndex}`);
  const flight = decoded.embedded.flights[logIndex];
  const logCount = decoded.embedded.logCount;
  return {
    kind: "gyrocore_browser_workspace",
    demo: false,
    scenario: `browser · log ${logIndex + 1}/${logCount}`,
    overview: {
      message:
        "Local browser workspace: Blackbox decode and CHIRP / system-ID. General analysis, Tune, Safety and CLI apply are not available in the browser yet. Nothing was uploaded.",
      target: md.boardInformation,
      betaflight_version: [md.firmwareType, md.firmwareVersion].filter(Boolean).join(" ") || undefined,
      craft: md.craftName,
      log_duration_s: flight?.durationUs != null ? Number((flight.durationUs / 1e6).toFixed(2)) : undefined,
      sample_rate_hz: chirp.sample_rate_hz ?? (md.sampleRateHzEstimate != null ? Math.round(md.sampleRateHzEstimate) : undefined),
      chirp_detected: chirp.available,
      tune_recommendation: "not available (browser)",
      detected_issues: [],
      bbl_filename: opts.bbl.name,
      cli_filename: opts.cli.filename,
      log_index: logIndex,
      log_count: logCount,
      decode_status: `decoded in browser · ${analysis.source.framesDecoded} frames`,
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
      label: "CLI apply / rollback generation is not available in the browser.",
      reasons: [NOT_IN_BROWSER],
      firmware_provenance: { ...opts.cli },
    },
    capabilities: featureAvailability(opts.features),
    unavailable_reason: NOT_IN_BROWSER,
    diagnostics: { note: NOT_IN_BROWSER, chirp_timings_ms: analysis.timingsMs },
    blackbox: {
      source: "browser",
      filename: opts.bbl.name,
      size_bytes: opts.bbl.sizeBytes,
      selected_log_index: logIndex,
      log_count: logCount,
      flights: decoded.embedded.flights.map((f) => ({ ...f })),
      frames_decoded: analysis.source.framesDecoded,
      decoder: analysis.source.decoder,
      metadata: {
        firmware: [md.firmwareType, md.firmwareVersion].filter(Boolean).join(" ") || undefined,
        board: md.boardInformation,
        craft: md.craftName,
        looptime_us: md.looptimeUs,
        pid_process_denom: md.pidProcessDenom,
        debug_mode: md.debugMode,
        sample_rate_hz_estimate: md.sampleRateHzEstimate,
        log_start: md.logStartDatetime,
      },
      fields_hint: [...md.fieldNames],
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
