import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { ReasonList } from "@/components/KeyValue";
import { StatusBadge } from "@/components/StatusBadge";
import { cardTitle, dataTable, dataTableCell, dataTableHead, dataTableNum, dataTableRow } from "@/lib/gyrocore-theme";
import { mutedText } from "@/lib/premium-theme";
import { statusTone } from "@/lib/status";
import { cn } from "@/lib/utils";

const ACCENT: Record<string, string> = {
  success: "bg-[var(--gc-status-good)]",
  warning: "bg-[var(--gc-status-warn)]",
  danger: "bg-[var(--gc-status-error)]",
  muted: "bg-[var(--gc-border-default)]",
  info: "bg-[var(--gc-accent)]",
  neutral: "bg-[var(--gc-border-default)]",
};

export function SafetyStage({
  step,
  title,
  status,
  body,
}: {
  step?: number;
  title: string;
  status?: string | null;
  body: Record<string, unknown> | null | undefined;
}) {
  const checks = Array.isArray(body?.checks) ? (body?.checks as Array<Record<string, unknown>>) : [];
  const reasons = [
    ...((body?.blocking_reasons as string[]) || []),
    ...((body?.blocked_reasons as string[]) || []),
    ...((body?.warning_reasons as string[]) || []),
    ...((body?.warnings as string[]) || []),
    ...((body?.reasons as string[]) || []),
  ];
  const clampIds = (body?.clamp_ids as string[]) || [];
  const shown = status || (body?.status as string);
  const tone = statusTone(shown);

  return (
    <SurfaceCard className="pl-6" data-tone={tone}>
      <span aria-hidden className={cn("absolute inset-y-0 left-0 w-[3px]", ACCENT[tone])} />
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          {step != null && (
            <span className="grid h-7 w-7 place-items-center rounded-lg border border-[var(--gc-border-default)] bg-[var(--gc-bg-inset)] font-mono text-xs text-[var(--gc-text-secondary)]">
              {step}
            </span>
          )}
          <h3 className={cn(cardTitle, "m-0 text-base")}>{title}</h3>
        </div>
        <StatusBadge value={shown} />
      </div>
      {reasons.length > 0 && <ReasonList items={reasons} className="mb-3" />}
      {clampIds.length > 0 && (
        <div className="mb-3 flex flex-col gap-1.5">
          <MicroLabel>clamp_ids</MicroLabel>
          <ReasonList items={clampIds} />
        </div>
      )}
      {checks.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)]/60">
          <table className={dataTable}>
            <thead>
              <tr>
                <th className={dataTableHead}>Rule</th>
                <th className={dataTableHead}>Verdict</th>
                <th className={dataTableHead}>Message</th>
                <th className={cn(dataTableHead, "text-right")}>Before</th>
                <th className={cn(dataTableHead, "text-right")}>After</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((c, i) => (
                <tr key={`${c.rule_id}-${i}`} className={dataTableRow}>
                  <td className={cn(dataTableCell, "font-mono text-xs")}>{String(c.rule_id || "")}</td>
                  <td className={dataTableCell}>
                    <StatusBadge value={String(c.verdict || "")} />
                  </td>
                  <td className={cn(dataTableCell, "text-[var(--gc-text-secondary)]")}>{String(c.message || "")}</td>
                  <td className={dataTableNum}>{c.before == null ? "—" : String(c.before)}</td>
                  <td className={dataTableNum}>{c.after == null ? "—" : String(c.after)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!reasons.length && !checks.length && <p className={cn(mutedText, "m-0")}>No detailed reasons for this stage.</p>}
    </SurfaceCard>
  );
}
