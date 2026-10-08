/**
 * Test double for `@/session/client`: the real session core run in-process (real
 * FlightLog decode + CHIRP on committed fixtures), with hooks to observe sessions
 * and to hold a decode pending.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { gunzipSync } from "node:zlib";
import { createSessionCore } from "@/session/sessionCore";
import type { SessionAnalyzeResult, SessionOpenResult } from "@/session/types";

const FIXTURES = join(__dirname, "../../../../../tests/fixtures");

export function fixtureFile(name: string, as = `${name}.bbl`): File {
  const path = name === "mode_events" ? join(FIXTURES, "decode/mode_events.bbl.gz") : join(FIXTURES, `chirp/wu7/bbl/${name}.bbl.gz`);
  return new File([gunzipSync(readFileSync(path))], as, { type: "application/octet-stream" });
}

export function multiLogFile(names: string[], as = "multi.bbl"): File {
  return new File(
    names.map((n) => gunzipSync(readFileSync(join(FIXTURES, `chirp/wu7/bbl/${n}.bbl.gz`)))),
    as,
    { type: "application/octet-stream" },
  );
}

export const sessionLog: { sessions: InProcessSession[]; holdOpen: Promise<void> | null } = { sessions: [], holdOpen: null };

export class InProcessSession {
  readonly core = createSessionCore();
  disposed = false;
  analyzed: number[] = [];
  private seq = 0;

  constructor() {
    sessionLog.sessions.push(this);
  }

  async open(file: File): Promise<SessionOpenResult> {
    const buffer = await file.arrayBuffer();
    if (sessionLog.holdOpen) await sessionLog.holdOpen;
    if (this.disposed) throw new Error("session_disposed");
    const r = this.core.handle({ id: ++this.seq, type: "open", buffer, filename: file.name }).response;
    if (!r.ok) throw new Error(r.error);
    if (r.type !== "open") throw new Error("protocol");
    return r;
  }

  async analyze(logIndex: number): Promise<SessionAnalyzeResult> {
    if (this.disposed) throw new Error("session_disposed");
    this.analyzed.push(logIndex);
    const r = this.core.handle({ id: ++this.seq, type: "analyze", logIndex }).response;
    if (!r.ok) throw new Error(r.error);
    if (r.type !== "analyze") throw new Error("protocol");
    return r;
  }

  dispose() {
    this.disposed = true;
  }

  get isDisposed() {
    return this.disposed;
  }
}
