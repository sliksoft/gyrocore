import { isTauriRuntime } from "@/runtime/capabilities";
import type { InspectResult, WorkspacePayload } from "./types";

export interface WorkerResponse<T> {
  id: string | number | null;
  ok: boolean;
  protocol?: number;
  result?: T;
  error?: { code: string; message: string; details?: string };
}

type WorkerFn = <T>(op: string, params?: Record<string, unknown>) => Promise<T>;

declare global {
  interface Window {
    __GYROCORE_WORKER__?: WorkerFn;
  }
}

async function invokeWorker<T>(op: string, params: Record<string, unknown> = {}): Promise<T> {
  const id = `ui-${Date.now()}`;
  const request = { id, op, params };

  if (typeof window !== "undefined" && window.__GYROCORE_WORKER__) {
    return window.__GYROCORE_WORKER__<T>(op, params);
  }

  // PWA / browser: never touch Tauri invoke (would throw TypeError).
  if (!isTauriRuntime()) {
    if (op === "demo" || op === "list_demos" || op === "ping") {
      return runDemoFixtureFallback<T>(op, params);
    }
    throw new Error(
      "Browser analysis backend is not available yet. Demo fixtures work offline; real Blackbox analysis arrives in a later update.",
    );
  }

  try {
    const { invoke } = await import("@tauri-apps/api/core");
    const raw = (await invoke("worker_request", { request })) as WorkerResponse<T>;
    if (!raw.ok) {
      throw new Error(raw.error?.message || raw.error?.code || "worker_error");
    }
    return raw.result as T;
  } catch (err) {
    if (op === "demo" || op === "list_demos" || op === "ping") {
      return runDemoFixtureFallback<T>(op, params);
    }
    const msg = String(err || "");
    throw new Error(
      msg.includes("not allowed") || msg.includes("invoke") || msg.includes("Tauri")
        ? "Core bridge requires the Tauri desktop host for local files. Use Demo mode in the browser."
        : msg,
    );
  }
}

async function runDemoFixtureFallback<T>(op: string, params: Record<string, unknown>): Promise<T> {
  if (op === "ping") {
    return { pong: true, worker: "fixture-fallback", protocol: 1 } as T;
  }
  if (op === "list_demos") {
    return {
      scenarios: ["pass", "warn", "block", "no_chirp", "merge_review", "no_autotune"],
    } as T;
  }
  if (op === "demo") {
    const scenario = String(params.scenario || "pass");
    const url = `${import.meta.env.BASE_URL}demo/${scenario}.json`;
    const res = await fetch(url);
    if (!res.ok) {
      throw new Error(`demo_fixture_missing:${scenario}`);
    }
    return (await res.json()) as T;
  }
  throw new Error("fixture_fallback_unsupported_op");
}

export const bridge = {
  ping: () => invokeWorker<{ pong: boolean }>("ping"),
  listDemos: () => invokeWorker<{ scenarios: string[] }>("list_demos"),
  loadDemo: (scenario: string) => invokeWorker<WorkspacePayload>("demo", { scenario }),
  inspect: (path: string) => invokeWorker<InspectResult>("inspect", { path }),
  analyze: (args: {
    path: string;
    log_index?: number | null;
    cli_dump?: string;
    cli_path?: string;
  }) => invokeWorker<WorkspacePayload>("analyze", args as Record<string, unknown>),
};
