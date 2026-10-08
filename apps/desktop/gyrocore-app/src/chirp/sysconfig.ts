/**
 * CHIRP header (sysConfig) parsing from raw `H key:value` lines.
 * Port of core/gyrocore/chirp/sysconfig.py (`parse_chirp_sysconfig`, H-line path)
 * and debug_modes.py. Values keep upstream `Number.parseInt` semantics; present
 * keys are recorded so upstream defaults are never mistaken for logged values.
 */

import { findLogStartOffsets } from "@/decode/headers";
import type { ChirpSysConfigDict } from "./types";

export const API_VERSION_MAX_SUPPORTED = "1.49.0";

const CHIRP_DEBUG_INDEX_BY_TABLE_VERSION: Array<[string, number]> = [
  ["1.44.0", -1],
  ["1.45.0", -1],
  ["1.46.0", -1],
  ["1.47.0", 97],
  ["1.48.0", 96],
  ["1.49.0", 96],
];

const UPSTREAM_DEFAULTS: Record<string, number> = {
  data_version: 2,
  looptime: 125,
  pid_process_denom: 1,
  debug_mode: -1,
  blackbox_high_resolution: 0,
  i_interval: 32,
  p_interval_num: 1,
  p_interval_denom: 1,
};

const INT_KEYS = [
  "data_version",
  "looptime",
  "pid_process_denom",
  "debug_mode",
  "blackbox_high_resolution",
  "i_interval",
  "chirp_lag_freq_hz",
  "chirp_lead_freq_hz",
  "chirp_amplitude_roll",
  "chirp_amplitude_pitch",
  "chirp_amplitude_yaw",
  "chirp_frequency_start_deci_hz",
  "chirp_frequency_end_deci_hz",
  "chirp_time_seconds",
] as const;
type IntKey = (typeof INT_KEYS)[number] | "p_interval_num" | "p_interval_denom";

export type ChirpSysConfig = {
  ints: Partial<Record<IntKey, number | null>>;
  p_interval_seen: boolean;
  firmware_revision: string | null;
  firmware_api_version: string | null;
  field_i_names: string[];
  present_keys: Set<string>;
};

/** `Number.parseInt(value, 10)`; null where JS yields NaN. */
export function jsParseInt(value: string): number | null {
  const m = /^\s*([+-]?\d+)/.exec(value);
  return m ? Number.parseInt(m[1]!, 10) : null;
}

/** gyrocore.parse.firmware_metadata._normalize_field_key */
export function normalizeFieldKey(raw: string): string {
  return raw.trim().toLowerCase().replace(/^_+/, "").trim().replace(/\s+/g, "_");
}

const LATIN1 = new TextDecoder("latin1");

/** Ordered `H` header pairs (raw key, raw value) of embedded log `logIndex`, as `read_bbl_header_text`. */
export function readHeaderPairs(bytes: Uint8Array, logIndex: number): Array<[string, string]> {
  const starts = findLogStartOffsets(bytes);
  if (!starts.length) throw new Error("no_blackbox_log_found");
  if (logIndex < 0 || logIndex >= starts.length) {
    throw new Error(`log_index_out_of_range: ${logIndex} (logs=${starts.length})`);
  }
  const start = starts[logIndex]!;
  const end = logIndex + 1 < starts.length ? starts[logIndex + 1]! : bytes.length;
  const pairs: Array<[string, string]> = [];
  let pos = start;
  while (pos + 1 < end && bytes[pos] === 0x48 && bytes[pos + 1] === 0x20) {
    let stop = pos;
    while (stop < end && bytes[stop] !== 0x0a) stop++;
    // Python splitlines() also breaks on \r; the H line body ends there.
    const line = LATIN1.decode(bytes.subarray(pos + 2, stop)).split(/\r/)[0]!;
    const colon = line.indexOf(":");
    if (colon >= 0) pairs.push([line.slice(0, colon), line.slice(colon + 1)]);
    pos = stop + 1;
  }
  return pairs;
}

export function parseChirpSysConfig(pairs: Array<[string, string]>): ChirpSysConfig {
  const ints: ChirpSysConfig["ints"] = {};
  const present = new Set<string>();
  let pIntervalSeen = false;
  let pRatio: number | null = null;
  let firmwareRevision: string | null = null;
  let firmwareApi: string | null = null;
  let fieldINames: string[] = [];
  for (const [rawKey, raw] of pairs) {
    const key = normalizeFieldKey(rawKey);
    if ((INT_KEYS as readonly string[]).includes(key)) {
      ints[key as IntKey] = jsParseInt(raw);
      present.add(key);
    } else if (key === "p_interval") {
      pIntervalSeen = true;
      present.add(key);
      const slash = raw.indexOf("/");
      if (slash >= 0) {
        ints.p_interval_num = jsParseInt(raw.slice(0, slash));
        ints.p_interval_denom = jsParseInt(raw.slice(slash + 1));
      } else {
        ints.p_interval_num = 1;
        ints.p_interval_denom = jsParseInt(raw);
      }
    } else if (key === "p_interval_num" || key === "p_interval_denom") {
      pIntervalSeen = true;
      present.add("p_interval");
      ints[key] = jsParseInt(raw);
    } else if (key === "p_ratio") {
      pRatio = jsParseInt(raw);
      present.add(key);
    } else if (key === "firmware_revision") {
      firmwareRevision = raw.trim();
      present.add(key);
    } else if (key === "firmware_api_version") {
      firmwareApi = raw.trim();
      present.add(key);
    } else if (key === "field_i_name") {
      fieldINames = raw.split(",");
      present.add(key);
    }
  }
  if (!pIntervalSeen && pRatio !== null && pRatio > 0) {
    ints.p_interval_num = 1;
    ints.p_interval_denom = pRatio;
    pIntervalSeen = true;
  }
  return {
    ints,
    p_interval_seen: pIntervalSeen,
    firmware_revision: firmwareRevision,
    firmware_api_version: firmwareApi,
    field_i_names: fieldINames,
    present_keys: present,
  };
}

function intOrNull(sc: ChirpSysConfig, key: IntKey): number | null {
  const v = sc.ints[key];
  return v === undefined ? null : v;
}

/** `ChirpSysConfig.upstream_value`: upstream defaults applied, NaN -> 0. */
export function upstreamValue(sc: ChirpSysConfig, key: IntKey): number {
  const v = intOrNull(sc, key);
  if (v === null) return sc.present_keys.has(key) ? 0 : (UPSTREAM_DEFAULTS[key] ?? 0);
  return v;
}

export function highResolutionScale(sc: ChirpSysConfig): number {
  return upstreamValue(sc, "blackbox_high_resolution") ? 0.1 : 1.0;
}

export function chirpFrequencyRangeHz(sc: ChirpSysConfig): [number, number] | null {
  const start = intOrNull(sc, "chirp_frequency_start_deci_hz");
  const end = intOrNull(sc, "chirp_frequency_end_deci_hz");
  if (start === null || end === null || start <= 0 || end <= start) return null;
  return [start / 10.0, end / 10.0];
}

export function sampleRateInputs(sc: ChirpSysConfig): {
  looptimeUs: number | null;
  pidProcessDenom: number | null;
  frameIntervalPNum: number | null;
  frameIntervalPDenom: number | null;
} {
  const lt = intOrNull(sc, "looptime");
  const pd = intOrNull(sc, "pid_process_denom");
  return {
    looptimeUs: lt && lt > 0 ? lt : null,
    pidProcessDenom: pd && pd > 0 ? pd : null,
    frameIntervalPNum: sc.p_interval_seen ? intOrNull(sc, "p_interval_num") : null,
    frameIntervalPDenom: sc.p_interval_seen ? intOrNull(sc, "p_interval_denom") : null,
  };
}

export function sysConfigToDict(sc: ChirpSysConfig): ChirpSysConfigDict {
  const g = (k: IntKey) => intOrNull(sc, k);
  return {
    data_version: g("data_version"),
    looptime: g("looptime"),
    pid_process_denom: g("pid_process_denom"),
    debug_mode: g("debug_mode"),
    blackbox_high_resolution: g("blackbox_high_resolution"),
    i_interval: g("i_interval"),
    p_interval_num: g("p_interval_num"),
    p_interval_denom: g("p_interval_denom"),
    p_interval_seen: sc.p_interval_seen,
    chirp_lag_freq_hz: g("chirp_lag_freq_hz"),
    chirp_lead_freq_hz: g("chirp_lead_freq_hz"),
    chirp_amplitude_roll: g("chirp_amplitude_roll"),
    chirp_amplitude_pitch: g("chirp_amplitude_pitch"),
    chirp_amplitude_yaw: g("chirp_amplitude_yaw"),
    chirp_frequency_start_deci_hz: g("chirp_frequency_start_deci_hz"),
    chirp_frequency_end_deci_hz: g("chirp_frequency_end_deci_hz"),
    chirp_time_seconds: g("chirp_time_seconds"),
    firmware_revision: sc.firmware_revision,
    firmware_api_version: sc.firmware_api_version,
    present_keys: [...sc.present_keys].sort(),
    field_i_names: sc.field_i_names.slice(),
  };
}

// --- debug_modes.py --------------------------------------------------------

function semver(v: string | null | undefined): [number, number, number] | null {
  if (typeof v !== "string") return null;
  const m = /^v?(\d+)\.(\d+)\.(\d+)$/.exec(v.trim());
  return m ? [Number(m[1]), Number(m[2]), Number(m[3])] : null;
}

function semverGte(a: [number, number, number], b: [number, number, number]): boolean {
  for (let i = 0; i < 3; i++) {
    if (a[i]! !== b[i]!) return a[i]! > b[i]!;
  }
  return true;
}

export function chirpDebugModeIndex(apiVersion: string | null): number {
  const parsed = semver(apiVersion);
  let resolved = CHIRP_DEBUG_INDEX_BY_TABLE_VERSION[0]!;
  if (parsed) {
    for (const entry of CHIRP_DEBUG_INDEX_BY_TABLE_VERSION) {
      if (semverGte(parsed, semver(entry[0])!)) resolved = entry;
    }
  }
  return resolved[1];
}

export function effectiveChirpApiVersion(logApi: string | null, callerApi: string | null): string {
  if (logApi && logApi !== "0.0.0") return logApi;
  if (callerApi && callerApi !== "0.0.0") return callerApi;
  return API_VERSION_MAX_SUPPORTED;
}

/** `validate_chirp_debug_mode`: [apiVersionUsed, chirpIndex, errorCode]. */
export function validateChirpDebugMode(
  sc: ChirpSysConfig,
  apiVersion: string | null = null,
): [string, number, string | null] {
  const api = effectiveChirpApiVersion(sc.firmware_api_version, apiVersion);
  const index = chirpDebugModeIndex(api);
  if (index < 0) return [api, index, "chirp_debug_mode_unsupported_api"];
  if (upstreamValue(sc, "debug_mode") !== index) return [api, index, "not_chirp_debug_mode"];
  return [api, index, null];
}
