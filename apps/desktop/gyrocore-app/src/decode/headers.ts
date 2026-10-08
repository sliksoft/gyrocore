/**
 * Byte-level Blackbox header scan, independent of FlightLog.
 *
 * Used to tell metadata that is genuinely absent from a log (ABSENT_IN_LOG)
 * from metadata the browser adapter failed to surface (PARSER_MISSING).
 */

/** Same start marker FlightLogIndex / blackbox_decode use to split embedded logs. */
export const LOG_START_MARKER = "H Product:Blackbox flight data recorder by Nicholas Sherlock";

const MARKER_BYTES = new TextEncoder().encode(LOG_START_MARKER);

/** Byte offsets of every embedded log start, in file order. */
export function findLogStartOffsets(bytes: Uint8Array): number[] {
  const out: number[] = [];
  const first = MARKER_BYTES[0]!;
  const last = bytes.length - MARKER_BYTES.length;
  outer: for (let i = 0; i <= last; i++) {
    if (bytes[i] !== first) continue;
    for (let j = 1; j < MARKER_BYTES.length; j++) {
      if (bytes[i + j] !== MARKER_BYTES[j]) continue outer;
    }
    out.push(i);
    i += MARKER_BYTES.length - 1;
  }
  return out;
}

/** Parse consecutive `H key:value\n` lines starting at `offset`. */
export function scanHeaderLines(bytes: Uint8Array, offset: number): Record<string, string> {
  const headers: Record<string, string> = {};
  const decoder = new TextDecoder("latin1");
  let pos = offset;
  while (pos + 1 < bytes.length && bytes[pos] === 0x48 /* H */ && bytes[pos + 1] === 0x20) {
    let end = pos;
    while (end < bytes.length && bytes[end] !== 0x0a) end++;
    const line = decoder.decode(bytes.subarray(pos + 2, end));
    const colon = line.indexOf(":");
    if (colon > 0) headers[line.slice(0, colon)] = line.slice(colon + 1);
    pos = end + 1;
  }
  return headers;
}

/** Raw headers of embedded log `logIndex` (0-based); `{}` when the index is out of range. */
export function readLogHeaders(bytes: Uint8Array, logIndex: number): Record<string, string> {
  const starts = findLogStartOffsets(bytes);
  const start = starts[logIndex];
  return start === undefined ? {} : scanHeaderLines(bytes, start);
}
