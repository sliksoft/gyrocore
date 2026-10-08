export type StatusBadge = "PASS" | "WARN" | "BLOCK" | "NOT AVAILABLE" | string;

export interface WorkspacePayload {
  kind: string;
  demo: boolean;
  demo_label?: string | null;
  scenario: string;
  overview: Record<string, unknown>;
  analysis: Record<string, unknown> | null;
  chirp: ChirpPayload | null;
  tune: TunePayload | null;
  safety: SafetyPayload | null;
  compare: ComparePayload | null;
  cli: CliPayload;
  diagnostics?: {
    filter_evidence?: Record<string, unknown>;
    throttle?: Record<string, unknown>;
    verification?: Record<string, unknown>;
    note?: string;
    [key: string]: unknown;
  };
  blackbox: Record<string, unknown>;
  controls: {
    fc_apply_button: boolean;
    msp: boolean;
    serial: boolean;
    copy_apply_cli: boolean;
    copy_rollback_cli: boolean;
  };
  error_state?: string;
  /** Browser workspace: which features this workspace can show (absent on Core workspaces). */
  capabilities?: Record<string, "available" | "unavailable">;
  /** Browser workspace: why Analysis / Tune / Safety / Compare are empty. */
  unavailable_reason?: string;
}

export interface ChirpPayload {
  available: boolean;
  /** Core / browser CHIRP status: ok | usable_with_warnings | unusable | error. */
  status?: string;
  reason?: string;
  axis?: string;
  sample_rate_hz?: number;
  sample_rate_source?: string;
  header_vs_timestamp?: Record<string, unknown>;
  usable_frequency_hz?: Record<string, unknown>;
  quality?: string;
  segment?: Record<string, unknown>;
  magnitude: Array<{ hz: number; db: number | null }>;
  phase: Array<{ hz: number; deg: number | null }>;
  coherence: Array<{ hz: number; value: number | null }>;
  warnings?: string[];
}

export interface TunePayload {
  merge_status: string;
  review_reasons: string[];
  per_axis_recommendations: Record<string, unknown>;
  merged_sliders: Record<string, unknown>;
  current: StageValues;
  wu8_autotune: Record<string, unknown>;
  wu9_absolute_proposal: StageValues | { axes: null };
  wu10_safe_target: StageValues & { clamp_ids?: string[]; status?: string };
}

export interface StageValues {
  axes?: Record<string, Record<string, number | null>> | null;
  filters?: Record<string, number | null> | null;
  sliders?: Record<string, unknown> | null;
}

export interface SafetyPayload {
  mechanical: Record<string, unknown>;
  safe_tune: Record<string, unknown>;
  tuning_output_safety: Record<string, unknown>;
  final: Record<string, unknown>;
}

export interface ComparePayload {
  current: { axes: Record<string, Record<string, number | null>>; filters: Record<string, number | null>; flat: Record<string, number> };
  final_safe: { axes: Record<string, Record<string, number | null>> | null; filters: Record<string, number | null> | null; flat: Record<string, number> };
}

export interface CliPayload {
  state: "authorized" | "preview" | "denied" | string;
  authorized: boolean;
  actionable: boolean;
  label: string;
  apply_cli?: string;
  rollback_cli?: string;
  preview_cli?: string;
  reasons?: string[];
  blocked_reasons?: string[];
  changed_settings?: Record<string, number>;
  bundle_id?: string;
  source_profile?: number;
  target_profile?: number;
  firmware_provenance?: Record<string, unknown>;
  safety_provenance?: Record<string, unknown>;
  diagnostic_values?: Record<string, unknown>;
  warnings?: string[];
}

export interface InspectResult {
  path: string;
  filename: string;
  size_bytes: number;
  suffix: string;
  logs: Array<{ index: number; label: string }>;
  multi_log: boolean;
  requires_log_index: boolean;
  recommended_log_index?: number;
  decoder?: Record<string, unknown>;
  probe_error?: string;
}

export type NavId =
  | "open"
  | "overview"
  | "blackbox"
  | "analysis"
  | "chirp"
  | "tune"
  | "safety"
  | "compare"
  | "cli"
  | "diagnostics";
