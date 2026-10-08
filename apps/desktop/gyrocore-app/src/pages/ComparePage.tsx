import type { WorkspacePayload } from "../bridge/types";
import { CompareTable } from "../components/CompareTable";

export function ComparePage({ ws }: { ws: WorkspacePayload }) {
  return <CompareTable compare={ws.compare} unavailableReason={ws.unavailable_reason} />;
}
