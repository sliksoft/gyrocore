/**
 * Display-only mapping from GyroCore Core status strings to design-system tones.
 * Core values are shown verbatim; only their colour treatment is derived here.
 */
export type StatusTone = "success" | "warning" | "danger" | "muted" | "info" | "neutral";

const SUCCESS = new Set(["PASS", "OK", "AUTHORIZED", "SAFE", "CLEAR", "MECHANICAL_CLEAR", "AVAILABLE", "GOOD", "READY"]);
const WARNING = new Set(["WARN", "WARNING", "PREVIEW", "CAUTION", "LIMITED", "REVIEW", "LOW_CONFIDENCE", "LOW_QUALITY"]);
const DANGER = new Set(["BLOCK", "BLOCKED", "DENIED", "HARD_BLOCK", "FAIL", "FAILED", "ERROR"]);
const MUTED = new Set(["", "NOT AVAILABLE", "NOT_AVAILABLE", "N/A", "NA", "UNKNOWN", "MISSING", "NONE", "INSUFFICIENT_EVIDENCE"]);

export function statusLabel(value: unknown): string {
  const text = value == null ? "" : String(value).trim();
  return text ? text.toUpperCase() : "NOT AVAILABLE";
}

export function statusTone(value: unknown): StatusTone {
  const v = statusLabel(value);
  if (MUTED.has(v)) return "muted";
  if (DANGER.has(v) || v.includes("BLOCK") || v.includes("DENIED")) return "danger";
  if (WARNING.has(v) || v.includes("WARN") || v.includes("REVIEW") || v.includes("CAUTION") || v.includes("LIMITED")) {
    return "warning";
  }
  if (SUCCESS.has(v)) return "success";
  if (v === "INFO" || v === "PROPOSED") return "info";
  return "neutral";
}
