/// <reference lib="webworker" />

import { createSessionCore } from "./sessionCore";
import type { SessionRequest } from "./types";

const ctx: DedicatedWorkerGlobalScope = self as unknown as DedicatedWorkerGlobalScope;
const session = createSessionCore();

ctx.onmessage = (ev: MessageEvent<SessionRequest>) => {
  const { response, transfer } = session.handle(ev.data);
  ctx.postMessage(response, transfer);
};
