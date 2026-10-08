import { useRef, useState } from "react";
import { FileText, Loader2, Play, Search, ShieldOff, TriangleAlert, WifiOff } from "lucide-react";
import { bridge } from "@/bridge/client";
import type { InspectResult, WorkspacePayload } from "@/bridge/types";
import { GyroCoreHeroLogo } from "@/components/branding/GyroCoreHeroLogo";
import { KeyValue } from "@/components/KeyValue";
import { ActionButton } from "@/components/ui/ActionButton";
import { FormField } from "@/components/ui/FormField";
import { Input } from "@/components/ui/input";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { StatusAlert } from "@/components/ui/StatusAlert";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { SurfaceCard } from "@/components/ui/SurfaceCard";
import { WizardCard } from "@/components/ui/WizardCard";
import { analyzeChirpFile } from "@/chirp/client";
import { browserChirpWorkspace } from "@/chirp/workspace";
import { decodeBlackboxFile } from "@/decode/client";
import type { NormalizedDecodedLog } from "@/decode/types";
import {
  BLACKBOX_ACCEPT,
  CLI_ACCEPT,
  formatBytes,
  isSupportedBlackboxName,
  isSupportedCliName,
  toSelectedLocalFile,
  type SelectedLocalFile,
} from "@/lib/browser-files";
import { pageStack } from "@/lib/gyrocore-theme";
import { selectBase } from "@/lib/premium-theme";
import { cn } from "@/lib/utils";
import { pwaUpdates } from "@/pwa/update";
import { getRuntimeCapabilities } from "@/runtime/capabilities";

const DEMOS = ["pass", "warn", "block", "no_chirp", "merge_review", "no_autotune"] as const;

const DEMO_INFO: Record<(typeof DEMOS)[number], { title: string; text: string; tone: "success" | "warning" | "danger" | "muted" | "info" }> = {
  pass: { title: "Pass", text: "All stages pass; authorized APPLY / ROLLBACK CLI.", tone: "success" },
  warn: { title: "Warn", text: "Clamped target; preview CLI only.", tone: "warning" },
  block: { title: "Block", text: "Safety blocks the tune; no CLI.", tone: "danger" },
  no_chirp: { title: "No CHIRP", text: "Log without a usable CHIRP segment.", tone: "muted" },
  merge_review: { title: "Merge review", text: "Per-axis sliders disagree; review required.", tone: "warning" },
  no_autotune: { title: "No autotune", text: "Autotune stage unavailable.", tone: "muted" },
};

function FileChip({
  selected,
  onReplace,
  onRemove,
  busy,
  replaceTestId,
  removeTestId,
  selectedTestId,
}: {
  selected: SelectedLocalFile;
  onReplace: () => void;
  onRemove: () => void;
  busy: boolean;
  replaceTestId: string;
  removeTestId: string;
  selectedTestId: string;
}) {
  return (
    <div
      className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)]/70 px-3 py-2.5"
      data-testid={selectedTestId}
    >
      <div className="min-w-0">
        <p className="m-0 truncate text-sm font-semibold text-[var(--gc-text-heading)]">{selected.name}</p>
        <p className="m-0 mt-0.5 font-mono text-[11px] text-[var(--gc-text-tertiary)]">{formatBytes(selected.size)}</p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <ActionButton variant="secondary" size="small" type="button" onClick={onReplace} disabled={busy} data-testid={replaceTestId}>
          Replace
        </ActionButton>
        <ActionButton variant="ghost" size="small" type="button" onClick={onRemove} disabled={busy} data-testid={removeTestId}>
          Remove
        </ActionButton>
      </div>
    </div>
  );
}

export function OpenPage({
  onLoaded,
}: {
  onLoaded: (ws: WorkspacePayload, inspect?: InspectResult | null) => void;
}) {
  const caps = getRuntimeCapabilities();
  const browserMode = caps.mode === "browser";

  const [path, setPath] = useState("");
  const [cliPath, setCliPath] = useState("");
  const [bblFile, setBblFile] = useState<SelectedLocalFile | null>(null);
  const [cliFile, setCliFile] = useState<SelectedLocalFile | null>(null);
  const [decoded, setDecoded] = useState<NormalizedDecodedLog | null>(null);
  const [inspect, setInspect] = useState<InspectResult | null>(null);
  const [logIndex, setLogIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const bblInputRef = useRef<HTMLInputElement>(null);
  const cliInputRef = useRef<HTMLInputElement>(null);

  const filesReady = browserMode
    ? Boolean(bblFile && cliFile)
    : Boolean(path.trim());

  const canAnalyzeTauri = !browserMode && caps.analysis === "tauri-worker" && Boolean(path.trim()) && !busy;
  // Browser analysis = CHIRP / system-ID only (Tune / Safety not migrated).
  const canAnalyzeBrowser =
    browserMode && caps.features.chirpAnalysis === "browser-worker" && Boolean(bblFile && cliFile && decoded);

  function setWorking(next: boolean) {
    setBusy(next);
    pwaUpdates.setSessionBusy(next);
  }

  async function doInspect() {
    if (browserMode) return;
    setWorking(true);
    setError(null);
    try {
      const result = await bridge.inspect(path);
      setInspect(result);
      setLogIndex(result.recommended_log_index ?? 0);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  async function doAnalyze() {
    if (browserMode) {
      if (!canAnalyzeBrowser || !bblFile) return;
      setWorking(true);
      setError(null);
      try {
        const analysis = await analyzeChirpFile(bblFile.file, { logIndex });
        onLoaded(
          browserChirpWorkspace({ analysis, decoded, bblName: bblFile.name, cliName: cliFile?.name ?? null }),
          null,
        );
      } catch (e) {
        setError(String(e));
      } finally {
        setWorking(false);
      }
      return;
    }
    setWorking(true);
    setError(null);
    try {
      const ws = await bridge.analyze({
        path,
        log_index: logIndex,
        cli_path: cliPath || undefined,
      });
      onLoaded(ws, inspect);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  async function loadDemo(scenario: string) {
    setWorking(true);
    setError(null);
    try {
      const ws = await bridge.loadDemo(scenario);
      onLoaded(ws, null);
    } catch (e) {
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  async function onBblPicked(list: FileList | null) {
    const file = list?.[0];
    if (!file) return; // cancel
    if (!isSupportedBlackboxName(file.name)) {
      setError(`Unsupported Blackbox extension: ${file.name}. Use .bbl, .bfl, or .csv.`);
      return;
    }
    setBblFile(toSelectedLocalFile(file));
    setDecoded(null);
    setError(null);
    if (bblInputRef.current) bblInputRef.current.value = "";
    // CSV is accepted for selection but browser FlightLog decode is BBL/BFL binary.
    if (file.name.toLowerCase().endsWith(".csv")) {
      setError("CSV selected. Browser decode currently supports .bbl / .bfl binary logs.");
      return;
    }
    setWorking(true);
    try {
      const { result } = await decodeBlackboxFile(file, { includeSeries: false });
      setDecoded(result);
      setLogIndex(result.embedded.recommendedIndex);
    } catch (e) {
      setDecoded(null);
      setError(String(e));
    } finally {
      setWorking(false);
    }
  }

  function onCliPicked(list: FileList | null) {
    const file = list?.[0];
    if (!file) return;
    if (!isSupportedCliName(file.name)) {
      setError(`Unsupported CLI extension: ${file.name}.`);
      return;
    }
    setCliFile(toSelectedLocalFile(file));
    setError(null);
    if (cliInputRef.current) cliInputRef.current.value = "";
  }

  return (
    <div className={pageStack} data-testid="open-page" data-runtime={caps.mode}>
      <SurfaceCard variant="elevated" className="hero-dot-grid relative overflow-hidden px-8 py-7">
        <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-cyan-500/10 blur-3xl" aria-hidden />
        <div className="relative flex flex-wrap items-end justify-between gap-6">
          <div className="flex flex-col gap-3">
            <GyroCoreHeroLogo />
            <p className="m-0 max-w-xl text-sm leading-relaxed text-[var(--gc-text-secondary)]">
              Betaflight Blackbox analysis and safe tuning on your machine. Logs never leave this computer and
              GyroCore never writes to the flight controller.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge tone="info">
              <WifiOff className="h-3 w-3" aria-hidden /> Local files only
            </StatusBadge>
            <StatusBadge tone="neutral">Nothing uploaded</StatusBadge>
            <StatusBadge tone="neutral">
              <ShieldOff className="h-3 w-3" aria-hidden /> No FC connection
            </StatusBadge>
          </div>
        </div>
      </SurfaceCard>

      <SurfaceCard>
        <SectionHeader
          eyebrow="Step 1"
          title="Open Blackbox Log"
          subtitle="Local files only. Nothing is uploaded. No flight-controller connection."
        />
        <div className="flex flex-col gap-4">
          {browserMode ? (
            <>
              <input
                ref={bblInputRef}
                type="file"
                accept={BLACKBOX_ACCEPT}
                className="hidden"
                data-testid="bbl-file-input"
                onChange={(e) => onBblPicked(e.target.files)}
              />
              <input
                ref={cliInputRef}
                type="file"
                accept={CLI_ACCEPT}
                className="hidden"
                data-testid="cli-file-input"
                onChange={(e) => onCliPicked(e.target.files)}
              />

              <FormField label="Blackbox Log" help="Local .bbl / .bfl / .csv on this device.">
                {!bblFile ? (
                  <ActionButton
                    variant="secondary"
                    type="button"
                    disabled={busy}
                    data-testid="choose-bbl"
                    onClick={() => bblInputRef.current?.click()}
                  >
                    Choose BBL
                  </ActionButton>
                ) : (
                  <FileChip
                    selected={bblFile}
                    busy={busy}
                    selectedTestId="bbl-selected"
                    replaceTestId="replace-bbl"
                    removeTestId="remove-bbl"
                    onReplace={() => bblInputRef.current?.click()}
                    onRemove={() => {
                      setBblFile(null);
                      setDecoded(null);
                    }}
                  />
                )}
              </FormField>

              {decoded && (
                <div
                  className="rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)]/70 p-4"
                  data-testid="browser-decode-meta"
                >
                  <KeyValue
                    rows={[
                      {
                        label: "Embedded logs",
                        value: decoded.embedded.logCount > 1 ? (
                          <select
                            className={cn(selectBase, "max-w-md")}
                            value={logIndex}
                            onChange={(e) => setLogIndex(Number(e.target.value))}
                            data-testid="log-index"
                          >
                            {decoded.embedded.flights.map((f) => (
                              <option key={f.index} value={f.index}>
                                {f.index}: {f.label}
                                {f.index === decoded.embedded.recommendedIndex ? " (recommended)" : ""}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span>1 log</span>
                        ),
                      },
                      {
                        label: "Firmware",
                        value: [decoded.metadata.firmwareType, decoded.metadata.firmwareVersion]
                          .filter(Boolean)
                          .join(" ") || "—",
                        mono: true,
                      },
                      {
                        label: "Fields",
                        value: String(decoded.metadata.fieldNames.length),
                        mono: true,
                      },
                    ]}
                  />
                  <p className="m-0 mt-3 text-xs text-[var(--gc-text-tertiary)]" data-testid="decode-status">
                    Blackbox decoded — browser CHIRP analysis available; Tune / Safety analysis migration not yet complete.
                  </p>
                </div>
              )}

              <FormField label="CLI Dump" help="Betaflight CLI dump required for tuning analysis.">
                {!cliFile ? (
                  <ActionButton
                    variant="secondary"
                    type="button"
                    disabled={busy}
                    data-testid="choose-cli"
                    onClick={() => cliInputRef.current?.click()}
                  >
                    Choose CLI
                  </ActionButton>
                ) : (
                  <FileChip
                    selected={cliFile}
                    busy={busy}
                    selectedTestId="cli-selected"
                    replaceTestId="replace-cli"
                    removeTestId="remove-cli"
                    onReplace={() => cliInputRef.current?.click()}
                    onRemove={() => setCliFile(null)}
                  />
                )}
              </FormField>

              {filesReady && (
                <StatusAlert
                  tone="info"
                  icon={<FileText className="h-4 w-4 text-[var(--gc-accent)]" />}
                  title="Files ready on this device"
                  data-testid="files-ready"
                >
                  {decoded
                    ? "Blackbox decoded locally. Browser analysis migration is not yet complete — nothing was uploaded, and Begin analysis stays disabled."
                    : "Blackbox and CLI are selected locally. Browser analysis is not migrated yet — nothing was uploaded, and Begin analysis will not fabricate results."}
                </StatusAlert>
              )}
            </>
          ) : (
            <>
              <FormField label="Log path" htmlFor="log-path" help="Absolute path to a .bbl / .bfl / .csv log on this machine.">
                <div className="flex gap-2">
                  <Input
                    id="log-path"
                    className="h-9 flex-1 font-mono text-[13px]"
                    value={path}
                    onChange={(e) => setPath(e.target.value)}
                    placeholder="/path/to/flight.bbl"
                    data-testid="log-path"
                  />
                  <ActionButton variant="secondary" type="button" onClick={doInspect} disabled={!path || busy}>
                    <Search className="h-4 w-4" aria-hidden />
                    Inspect
                  </ActionButton>
                </div>
              </FormField>
              <FormField label="CLI dump" htmlFor="cli-path" help="Betaflight CLI dump required for tuning analysis.">
                <Input
                  id="cli-path"
                  className="h-9 font-mono text-[13px]"
                  value={cliPath}
                  onChange={(e) => setCliPath(e.target.value)}
                  placeholder="/path/to/cli.txt"
                  data-testid="cli-path"
                />
              </FormField>

              {inspect && (
                <div className="rounded-lg border border-[var(--gc-border-subtle)] bg-[var(--gc-bg-inset)]/70 p-4">
                  <KeyValue
                    rows={[
                      { label: "Filename", value: inspect.filename, mono: true },
                      { label: "Size", value: `${inspect.size_bytes} bytes`, mono: true },
                      {
                        label: "Logs",
                        value: inspect.multi_log ? (
                          <select
                            className={cn(selectBase, "max-w-md")}
                            value={logIndex}
                            onChange={(e) => setLogIndex(Number(e.target.value))}
                            data-testid="log-index"
                          >
                            {inspect.logs.map((l) => (
                              <option key={l.index} value={l.index}>
                                {l.index}: {l.label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span>1 log</span>
                        ),
                      },
                      { label: "Decoder", value: JSON.stringify(inspect.decoder), mono: true },
                    ]}
                  />
                </div>
              )}
            </>
          )}

          <div className="flex items-center gap-3 border-t border-[var(--gc-border-subtle)] pt-4">
            <ActionButton
              type="button"
              onClick={doAnalyze}
              disabled={browserMode ? !canAnalyzeBrowser || busy : !canAnalyzeTauri}
              data-testid="analyze-btn"
            >
              <Play className="h-4 w-4" aria-hidden />
              Begin analysis
            </ActionButton>
            <span className="text-xs text-[var(--gc-text-tertiary)]">
              {browserMode
                ? "Browser CHIRP / system-ID analysis — files stay local. Tune / Safety not yet in browser."
                : "Runs the local Python Core and blackbox_decode."}
            </span>
          </div>
        </div>
      </SurfaceCard>

      <SurfaceCard>
        <SectionHeader
          eyebrow="Demo"
          title="Demo / fixture mode"
          subtitle="Synthetic Core scenarios for UI testing. Not real flight blackbox data."
        />
        <div className="grid grid-cols-3 gap-3">
          {DEMOS.map((s) => (
            <WizardCard
              key={s}
              as="button"
              minHeight="none"
              onClick={() => loadDemo(s)}
              disabled={busy}
              data-testid={`demo-${s}`}
              className="p-4"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-semibold text-[var(--gc-text-heading)]">{DEMO_INFO[s].title}</span>
                <StatusBadge tone={DEMO_INFO[s].tone} className="font-mono">
                  {s}
                </StatusBadge>
              </div>
              <p className="m-0 mt-2 text-xs leading-relaxed text-[var(--gc-text-tertiary)]">{DEMO_INFO[s].text}</p>
            </WizardCard>
          ))}
        </div>
      </SurfaceCard>

      {error && (
        <StatusAlert tone="worse" icon={<TriangleAlert className="h-4 w-4 text-[var(--gc-status-error)]" />} title="Could not open workspace">
          <span data-testid="open-error" className="font-mono [overflow-wrap:anywhere]">
            {error}
          </span>
        </StatusAlert>
      )}
      {busy && (
        <StatusAlert tone="info" icon={<Loader2 className="h-4 w-4 animate-spin text-[var(--gc-accent)]" />} title="Working…">
          <span className="inline-flex items-center gap-1.5">
            <FileText className="h-3.5 w-3.5" aria-hidden /> Processing locally.
          </span>
        </StatusAlert>
      )}
    </div>
  );
}
