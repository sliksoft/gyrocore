import { FolderOpen } from "lucide-react";
import type { NavId } from "@/bridge/types";
import { NAV } from "@/components/layout/AppSidebar";
import { ActionButton } from "@/components/ui/ActionButton";
import { EmptyState } from "@/components/ui/EmptyState";

const COPY: Partial<Record<NavId, string>> = {
  overview: "No analysis available yet.",
  blackbox: "Load a Blackbox log to inspect the flight.",
  analysis: "Analyze a flight to see signal and tuning analysis.",
  chirp: "No CHIRP analysis available yet.",
  tune: "No tuning result available yet.",
  safety: "No safety evaluation available yet.",
  compare: "No comparison data available yet.",
  cli: "No CLI output available yet.",
  diagnostics: "No diagnostics available yet.",
};

/** Shown on workspace pages before a log (or explicit demo) is loaded — never fake data. */
export function NoWorkspaceState({ page, onOpen }: { page: NavId; onOpen: () => void }) {
  const Icon = NAV.find((n) => n.id === page)?.icon ?? FolderOpen;
  return (
    <EmptyState
      data-testid={`empty-${page}`}
      className="py-20"
      icon={<Icon className="h-6 w-6" aria-hidden />}
      title="No flight loaded yet"
      description={COPY[page] ?? "Load a Betaflight Blackbox log to view analysis results."}
      action={
        <ActionButton type="button" onClick={onOpen} data-testid={`empty-${page}-open`}>
          <FolderOpen className="h-4 w-4" aria-hidden />
          Open Blackbox Log
        </ActionButton>
      }
    />
  );
}
