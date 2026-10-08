import type { ChirpBrowserAnalysis } from "@/chirp/types";
import type { NormalizedDecodedLog } from "@/decode/types";

/** Browser analysis session: one file, decoded once, analysed for a selected embedded log. */
export type SessionRequest =
  | { id: number; type: "open"; buffer: ArrayBuffer; filename: string }
  | { id: number; type: "analyze"; logIndex: number };

export type SessionOpenResult = {
  /** Decode summary (all embedded logs; metadata of the recommended log). */
  decoded: NormalizedDecodedLog;
  timingsMs: Record<string, number>;
  /** FlightLog constructions in this session (decode-once proof: always 1). */
  flightLogBuilds: number;
};

export type SessionAnalyzeResult = {
  /** Decode summary re-normalized for the selected log (same FlightLog, no second decode). */
  decoded: NormalizedDecodedLog;
  analysis: ChirpBrowserAnalysis;
  flightLogBuilds: number;
};

export type SessionResponse =
  | ({ id: number; ok: true; type: "open" } & SessionOpenResult)
  | ({ id: number; ok: true; type: "analyze" } & SessionAnalyzeResult)
  | { id: number; ok: false; error: string };
