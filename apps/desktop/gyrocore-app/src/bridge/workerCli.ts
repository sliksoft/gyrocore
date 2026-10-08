/** Node-only worker bridge for vitest. Do not import from browser UI modules. */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { WorkerResponse } from "./client";

export async function runWorkerCli<T>(op: string, params: Record<string, unknown> = {}): Promise<T> {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const repo = path.resolve(here, "../../../../../");
  const worker = path.join(repo, "apps/desktop/worker/gyrocore_worker.py");
  const req = JSON.stringify({ id: "test", op, params });
  const py = process.env.GYROCORE_PYTHON || "/home/sliksoft/aerotuner/.venv/bin/python";
  const out = spawnSync(py, [worker], {
    input: `${req}\n`,
    encoding: "utf-8",
    env: {
      ...process.env,
      PYTHONPATH: `${repo}${path.delimiter}${path.join(repo, "core")}`,
    },
  });
  if (out.status !== 0) {
    throw new Error(out.stderr || `worker_exit_${out.status}`);
  }
  const line = (out.stdout || "").trim().split("\n").filter(Boolean).pop();
  if (!line) throw new Error("worker_empty_response");
  const raw = JSON.parse(line) as WorkerResponse<T>;
  if (!raw.ok) throw new Error(raw.error?.message || "worker_error");
  return raw.result as T;
}
