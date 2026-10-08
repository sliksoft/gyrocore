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

export type MetadataKey =
  | "firmwareType"
  | "firmwareVersion"
  | "firmwareRevision"
  | "firmwareDate"
  | "boardInformation"
  | "craftName"
  | "looptimeUs"
  | "pidProcessDenom"
  | "frameIntervalI"
  | "frameIntervalPNum"
  | "frameIntervalPDenom"
  | "gyroScaleRaw"
  | "motorProtocol"
  | "debugMode"
  | "dataVersion"
  | "logStartDatetime";

/**
 * PRESENT — header logged and surfaced.
 * ABSENT_IN_LOG — header not logged (or logged empty); not a decoder defect.
 * UNSET_SENTINEL — header logged with a placeholder value (e.g. RTC unset date).
 * PARSER_MISSING — header logged but the adapter did not surface it (defect).
 */
export type MetadataPresence = "PRESENT" | "ABSENT_IN_LOG" | "UNSET_SENTINEL" | "PARSER_MISSING";

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
    firmwareRevision?: string;
    firmwareDate?: string;
    boardInformation?: string;
    craftName?: string;
    looptimeUs?: number;
    pidProcessDenom?: number;
    frameIntervalI?: number;
    frameIntervalPNum?: number;
    frameIntervalPDenom?: number;
    /** Raw `gyro_scale` header value (FlightLog converts it internally). */
    gyroScaleRaw?: string;
    motorProtocol?: number;
    debugMode?: number;
    dataVersion?: number;
    /** `Log start datetime` header; undefined when absent or the unset-RTC sentinel. */
    logStartDatetime?: string;
    sampleRateHzEstimate?: number | null;
    fieldNames: string[];
    /**
     * Provenance per metadata key, checked against the raw `H` header lines of the
     * selected log. Empty when raw headers were not supplied to the adapter.
     */
    presence: Partial<Record<MetadataKey, MetadataPresence>>;
  };
  /** Aligned timebase for selected flight (µs). */
  timeUs: Float64Array;
  /** Logged loopIteration aligned with `timeUs` (join key for parity / segmenting). */
  loopIteration: Float64Array;
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
