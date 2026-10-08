/**
 * GyroCore-owned normalized decoded Blackbox contract.
 * Deliberately independent of Betaflight FlightLog internal shapes.
 */

export type DecodedFlightSummary = {
  index: number;
  label: string;
  /** Microseconds (raw blackbox time field) when available. */
  startTimeUs: number | null;
  endTimeUs: number | null;
  durationUs: number | null;
  sampleCount: number;
  error?: string;
};

export type DecodedSeries = {
  /** Field name as logged (e.g. gyroADC[0]). */
  name: string;
  /** Compact Float64 samples aligned with `timeUs` when present. */
  values: Float64Array;
};

export type NormalizedDecodedLog = {
  schemaVersion: 1;
  source: {
    filename: string;
    sizeBytes: number;
    decoder: "betaflight-flightlog-js";
    licenseNote: "GPL-3.0 (vendored Betaflight blackbox-log-viewer)";
  };
  embedded: {
    logCount: number;
    selectedIndex: number;
    recommendedIndex: number;
    flights: DecodedFlightSummary[];
  };
  metadata: {
    firmwareType?: string;
    firmwareVersion?: string;
    craftName?: string;
    sampleRateHzEstimate?: number | null;
    fieldNames: string[];
  };
  /** Aligned timebase for selected flight (µs). */
  timeUs: Float64Array;
  /** Selected primary series for parity / future analysis (not all fields). */
  series: Record<string, Float64Array>;
};

export type DecodeProgress = {
  phase: "read" | "index" | "decode" | "normalize" | "done" | "error";
  message?: string;
  ratio?: number;
};

export type DecodeRequest = {
  /** Transferred ArrayBuffer of BBL/BFL bytes. */
  buffer: ArrayBuffer;
  filename: string;
  logIndex?: number | null;
  /** When true, extract full series for selected log (heavier). */
  includeSeries?: boolean;
};

export type DecodeResponse =
  | { ok: true; result: NormalizedDecodedLog; timingsMs: Record<string, number> }
  | { ok: false; error: string; timingsMs?: Record<string, number> };
