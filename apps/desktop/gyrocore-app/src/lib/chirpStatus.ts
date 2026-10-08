import type { ChirpPayload } from "@/bridge/types";

/**
 * The one CHIRP status mapping used by every CHIRP display (Overview, CHIRP page).
 *
 *   ok                    -> PASS
 *   usable_with_warnings  -> WARN
 *   anything else         -> NOT AVAILABLE (with the rejection reason)
 *
 * PASS / WARN additionally require available=true and non-empty, equal-length
 * magnitude / phase / coherence series; a contradiction is never a PASS.
 */
export type ChirpBadge = "PASS" | "WARN" | "NOT AVAILABLE";

export type ChirpDisplay = {
  badge: ChirpBadge;
  /** True only when the Bode charts can be drawn (badge is PASS or WARN). */
  chartable: boolean;
  /** Why the result is not chartable; null when it is. */
  reason: string | null;
};

const BADGE_BY_STATUS: Readonly<Record<string, ChirpBadge>> = Object.freeze({
  ok: "PASS",
  usable_with_warnings: "WARN",
});

const notAvailable = (reason: string): ChirpDisplay => ({ badge: "NOT AVAILABLE", chartable: false, reason });

export function chirpDisplay(c: ChirpPayload | null | undefined): ChirpDisplay {
  if (!c) return notAvailable("no_chirp_payload");
  if (!c.available) return notAvailable(c.reason || "unavailable");
  const n = c.magnitude?.length ?? 0;
  if (!n || !c.phase?.length || !c.coherence?.length) return notAvailable("chirp_series_empty");
  if (c.phase.length !== n || c.coherence.length !== n) return notAvailable("chirp_series_length_mismatch");
  const badge = c.status != null ? BADGE_BY_STATUS[c.status] : undefined;
  if (!badge) return notAvailable(c.status ? `chirp_status_${c.status}` : "chirp_status_missing");
  return { badge, chartable: true, reason: null };
}
