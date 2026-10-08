import { useState } from "react";
import { Ban, Copy, Info, ShieldOff, TriangleAlert } from "lucide-react";
import type { WorkspacePayload } from "@/bridge/types";
import { CodeBlock, KeyValue, ReasonList } from "@/components/KeyValue";
import { StatusBadge } from "@/components/StatusBadge";
import { ActionButton } from "@/components/ui/ActionButton";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { StatusAlert } from "@/components/ui/StatusAlert";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { pageStack } from "@/lib/gyrocore-theme";
import { cliPanel } from "@/lib/premium-theme";
import { cn } from "@/lib/utils";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

const cliBox = cn(cliPanel, "m-0 max-h-[280px] overflow-auto whitespace-pre-wrap text-[var(--gc-text-primary)] [overflow-wrap:anywhere]");

export function CliPage({ ws }: { ws: WorkspacePayload }) {
  const cli = ws.cli;
  const [note, setNote] = useState<string | null>(null);

  async function onCopy(which: "apply" | "rollback") {
    const text = which === "apply" ? cli.apply_cli : cli.rollback_cli;
    if (!cli.authorized || !text) {
      setNote("Copy refused: not authorized paste-ready CLI.");
      return;
    }
    const ok = await copyText(text);
    setNote(ok ? `Copied ${which} CLI` : "Clipboard unavailable");
  }

  const rows = [
    { label: "Authorized", value: String(cli.authorized), mono: true },
    { label: "Actionable", value: String(cli.actionable), mono: true },
    ...(cli.source_profile != null
      ? [{ label: "PID profile", value: `${cli.source_profile} → ${cli.target_profile}`, mono: true }]
      : []),
    ...(cli.bundle_id ? [{ label: "Bundle", value: cli.bundle_id, mono: true }] : []),
    ...(cli.firmware_provenance ? [{ label: "Firmware", value: <CodeBlock value={cli.firmware_provenance} maxHeight={180} /> }] : []),
  ];

  return (
    <div className={pageStack} data-testid="cli-page">
      <SurfaceCard>
        <SectionHeader title="CLI output" subtitle={cli.label} actions={<StatusBadge value={cli.state} />} />
        <KeyValue rows={rows} />
        <StatusAlert tone="info" className="mt-4" icon={<ShieldOff className="h-4 w-4 text-[var(--gc-accent)]" />}>
          <span data-testid="no-fc-apply">No Apply to FC · No MSP · No serial — copy CLI text only.</span>
        </StatusAlert>
      </SurfaceCard>

      {cli.state === "authorized" && (
        <div className="grid grid-cols-2 gap-4">
          <SurfaceCard className="min-w-0 border-[var(--gc-status-good-border)]" data-testid="apply-cli-panel">
            <SectionHeader eyebrow="Paste-ready" title="AUTHORIZED APPLY CLI" />
            <pre className={cliBox}>{cli.apply_cli}</pre>
            <div className="mt-3 flex">
              <ActionButton type="button" data-testid="copy-apply" onClick={() => onCopy("apply")}>
                <Copy className="h-4 w-4" aria-hidden />
                Copy APPLY CLI
              </ActionButton>
            </div>
          </SurfaceCard>
          <SurfaceCard className="min-w-0" data-testid="rollback-cli-panel">
            <SectionHeader eyebrow="Restore" title="AUTHORIZED ROLLBACK CLI" />
            <pre className={cliBox}>{cli.rollback_cli}</pre>
            <div className="mt-3 flex">
              <ActionButton type="button" variant="secondary" data-testid="copy-rollback" onClick={() => onCopy("rollback")}>
                <Copy className="h-4 w-4" aria-hidden />
                Copy ROLLBACK CLI
              </ActionButton>
            </div>
          </SurfaceCard>
        </div>
      )}

      {cli.state === "preview" && (
        <SurfaceCard className="border-[var(--gc-status-warn-border)]" data-testid="preview-cli-panel">
          <SectionHeader
            title="WARN PREVIEW — NOT PASTE-READY"
            actions={<TriangleAlert className="h-4 w-4 text-[var(--gc-status-warn)]" aria-hidden />}
          />
          <pre className={cn(cliBox, "border-[var(--gc-status-warn-border)]")}>{cli.preview_cli}</pre>
          <ReasonList items={cli.reasons || []} className="mt-3" />
        </SurfaceCard>
      )}

      {cli.state === "denied" && (
        <SurfaceCard className="border-[var(--gc-status-error-border)]" data-testid="denied-cli-panel">
          <SectionHeader title="BLOCK — no apply CLI" actions={<Ban className="h-4 w-4 text-[var(--gc-status-error)]" aria-hidden />} />
          <pre className={cn(cliBox, "border-[var(--gc-status-error-border)] text-[var(--gc-text-tertiary)]")}>
            No apply_cli / paste_ready_cli fields.
          </pre>
          <ReasonList items={cli.blocked_reasons || []} className="mt-3" />
        </SurfaceCard>
      )}

      {cli.changed_settings && (
        <SurfaceCard>
          <SectionHeader title="Changed settings" />
          <CodeBlock value={cli.changed_settings} />
        </SurfaceCard>
      )}
      {cli.safety_provenance && (
        <SurfaceCard>
          <SectionHeader title="Safety provenance" />
          <CodeBlock value={cli.safety_provenance} maxHeight={240} />
        </SurfaceCard>
      )}
      {note && (
        <StatusAlert tone="info" icon={<Info className="h-4 w-4 text-[var(--gc-accent)]" />}>
          {note}
        </StatusAlert>
      )}
    </div>
  );
}
