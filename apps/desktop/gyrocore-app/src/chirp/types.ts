/**
 * GyroCore-owned browser CHIRP / system-identification contract.
 *
 * Field names and semantics mirror the Python reference
 * `ChirpSystemIdResult.to_dict(include_arrays=True)` (core/gyrocore/chirp/pipeline.py)
 * so Python/browser parity is a direct comparison. Nothing here exposes
 * Betaflight FlightLog internals. Analysis only — no tuning output.
 */

export const AXIS_NAMES = ["roll", "pitch", "yaw"] as const;
export type AxisName = (typeof AXIS_NAMES)[number];

export type ChirpStatus = "ok" | "usable_with_warnings" | "unusable" | "error";

export type ChirpSegmentInfo = {
  index: number;
  axis: number;
  axis_name: string;
  start_idx: number;
  end_idx: number;
  sample_count: number;
  start_time_us: number;
  end_time_us: number;
  duration_s: number;
};

export type SampleRateSource = "header" | "timestamp" | "header_confirmed" | "unknown";
export type SampleRateStatus = "ok" | "mismatch" | "header_only" | "timestamp_only" | "unusable";

export type SampleRateEvidence = {
  pid_loop_rate_hz: number | null;
  blackbox_configured_rate_hz: number | null;
  header_rate_hz: number | null;
  timestamp_rate_hz: number | null;
  effective_rate_hz: number | null;
  source: SampleRateSource;
  status: SampleRateStatus;
  difference_percent: number | null;
  confidence: number;
  warnings: string[];
  frame_interval_p_num: number | null;
  frame_interval_p_denom: number | null;
  looptime_us: number | null;
  pid_process_denom: number | null;
  usable: boolean;
};

export type TimestampSpacing = {
  delta_count: number;
  median_dt_us: number | null;
  min_dt_us: number | null;
  max_dt_us: number | null;
  uniform_fraction: number;
  gap_count: number;
  missing_samples_estimate: number;
  missing_fraction: number;
  max_gap_samples: number;
  non_positive_deltas: number;
  uniform: boolean;
};

export type GateSeverity = "blocking" | "warning";

export type QualityGate = {
  code: string;
  passed: boolean;
  severity: GateSeverity;
  value: number | null;
  threshold: number | null;
  detail: string;
};

export type QualityReport = {
  usable: boolean;
  failed_gates: string[];
  warning_gates: string[];
  gates: QualityGate[];
  usable_range_hz: [number, number] | null;
  usable_bin_count: number;
  analysis_band_hz: [number, number];
  mean_band_coherence: number | null;
  input_rms: number;
};

/** Welch closed-loop H(f) = Sxy / Sxx. `magnitude_db` is -Infinity on bins with Sxx < 1e-20. */
export type TransferFunctionResult = {
  segment_size: number;
  num_segments: number;
  sample_rate_hz: number;
  frequencies_hz: Float64Array;
  h_real: Float64Array;
  h_imag: Float64Array;
  magnitude_db: Float64Array;
  phase_deg: Float64Array;
  coherence: Float64Array;
};

export type StepResponseResult = {
  overshoot_pct: number;
  rise_time_ms: number;
  settling_time_ms: number;
  time_ms: Float64Array;
  response: Float64Array;
};

export type ChirpAxisResult = {
  axis: number;
  axis_name: string;
  usable: boolean;
  segment: ChirpSegmentInfo;
  effective_rate_hz: number | null;
  upstream_autotune_rate_hz: number;
  sample_rate: SampleRateEvidence;
  timestamp_spacing: TimestampSpacing;
  segment_size: number | null;
  overlap: number;
  quality: QualityReport;
  warnings: string[];
  num_segments?: number;
  num_bins?: number;
  transfer_function?: TransferFunctionResult;
  /** 1 where the bin is in the usable band (in-band, Sxx floor, coherence >= 0.5). */
  usable_mask?: Uint8Array;
  sensitivity_peak_db?: number;
  step_response?: StepResponseResult;
};

export type ChirpSysConfigDict = {
  data_version: number | null;
  looptime: number | null;
  pid_process_denom: number | null;
  debug_mode: number | null;
  blackbox_high_resolution: number | null;
  i_interval: number | null;
  p_interval_num: number | null;
  p_interval_denom: number | null;
  p_interval_seen: boolean;
  chirp_lag_freq_hz: number | null;
  chirp_lead_freq_hz: number | null;
  chirp_amplitude_roll: number | null;
  chirp_amplitude_pitch: number | null;
  chirp_amplitude_yaw: number | null;
  chirp_frequency_start_deci_hz: number | null;
  chirp_frequency_end_deci_hz: number | null;
  chirp_time_seconds: number | null;
  firmware_revision: string | null;
  firmware_api_version: string | null;
  present_keys: string[];
  field_i_names: string[];
};

export type ChirpExtractionDict = {
  detected: boolean;
  segments: ChirpSegmentInfo[];
  selected_by_axis: Partial<Record<AxisName, number>>;
  sample_count: number;
  total_frames: number;
  dropped_axis_frames: number;
  high_resolution_scale: number;
  flag_gating: "none" | "flight_mode_flags" | "debug_axis_only";
  api_version: string | null;
  chirp_debug_mode_index: number | null;
  frequency_range_hz: [number, number] | null;
  warnings: string[];
  errors: string[];
};

export type ChirpSystemIdResult = {
  status: ChirpStatus;
  usable: boolean;
  detected: boolean;
  analysis_only: true;
  tuning_recommendations: null;
  sysconfig: ChirpSysConfigDict | null;
  extraction: ChirpExtractionDict | null;
  axes: Partial<Record<AxisName, ChirpAxisResult>>;
  warnings: string[];
  errors: string[];
  provenance: Record<string, unknown>;
};

/** Explicit structured rejection; never an empty-array "success". */
export type ChirpRejection = {
  code: string;
  detail: string;
};

export type ChirpBrowserAnalysis = {
  schemaVersion: 1;
  engine: "gyrocore-browser-chirp";
  result: ChirpSystemIdResult;
  /** null only when at least one axis is usable with non-empty series. */
  rejection: ChirpRejection | null;
  source: {
    filename: string;
    sizeBytes: number;
    logIndex: number;
    logCount: number;
    decoder: "betaflight-flightlog-js";
    /** Every valid main frame of the selected log (no subsampling). */
    framesDecoded: number;
    inputPolicy: "full_frame";
  };
  timingsMs: Record<string, number>;
};

export type ChirpRequest = {
  buffer: ArrayBuffer;
  filename: string;
  logIndex?: number | null;
};

export type ChirpResponse =
  | { ok: true; analysis: ChirpBrowserAnalysis }
  | { ok: false; error: string; timingsMs?: Record<string, number> };
