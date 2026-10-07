import { useEffect, useMemo, useRef, useState } from "react";
import type { InspectResult, NavId, WorkspacePayload } from "./bridge/types";
import { AppSidebar, NAV } from "./components/layout/AppSidebar";
import { StatusBadge } from "./components/StatusBadge";
import { NoWorkspaceState } from "./components/NoWorkspaceState";
import { StatusBadge as Chip } from "./components/ui/StatusBadge";
import { eyebrow, pageHeaderTitle } from "./lib/premium-theme";
import { cn } from "./lib/utils";
import { AnalysisPage } from "./pages/AnalysisPage";
import { BlackboxPage } from "./pages/BlackboxPage";
import { ChirpPage } from "./pages/ChirpPage";
import { CliPage } from "./pages/CliPage";
import { ComparePage } from "./pages/ComparePage";
import { DiagnosticsPage } from "./pages/DiagnosticsPage";
import { OpenPage } from "./pages/OpenPage";
import { OverviewPage } from "./pages/OverviewPage";
import { SafetyPage } from "./pages/SafetyPage";
import { TunePage } from "./pages/TunePage";

const COLLAPSE_KEY = "gyrocore.sidebar.collapsed";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSE_KEY) === "true";
  } catch {
    return false;
  }
}

export default function App() {
  const [nav, setNav] = useState<NavId>("open");
  const [ws, setWs] = useState<WorkspacePayload | null>(null);
  const [inspect, setInspect] = useState<InspectResult | null>(null);
  const [collapsed, setCollapsed] = useState<boolean>(readCollapsed);

  const title = useMemo(() => NAV.find((n) => n.id === nav)?.label || "GyroCore", [nav]);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    contentRef.current?.scrollTo?.({ top: 0 });
  }, [nav, ws]);

  function onLoaded(payload: WorkspacePayload, insp?: InspectResult | null) {
    setWs(payload);
    setInspect(insp || null);
    setNav("overview");
  }

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(COLLAPSE_KEY, String(next));
      } catch {
        /* preference only */
      }
      return next;
    });
  }

  return (
    <div className="flex h-screen overflow-hidden text-[var(--gc-text-primary)]" data-testid="app-shell">
      <AppSidebar
        nav={nav}
        onNav={setNav}
        collapsed={collapsed}
        onToggleCollapsed={toggleCollapsed}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="topbar shrink-0 border-b border-[var(--gc-border-subtle)] bg-[var(--gc-bg-base)]/70 backdrop-blur-xl">
          <div className="mx-auto flex w-full max-w-[1520px] flex-wrap items-center justify-between gap-x-6 gap-y-2 px-6 py-4 xl:px-10">
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className={eyebrow}>{ws ? "Workspace" : "GyroCore desktop"}</span>
              <h1 className={cn(pageHeaderTitle, "title m-0 text-xl")}>{title}</h1>
            </div>
            <div className="meta flex min-w-0 flex-wrap items-center justify-end gap-2" data-testid="workspace-meta">
              {ws ? (
                <>
                  {ws.demo && <Chip tone="warning">DEMO</Chip>}
                  <Chip tone="neutral" className="font-mono">
                    {ws.scenario}
                  </Chip>
                  <span className="inline-flex items-center gap-1.5 text-xs text-[var(--gc-text-tertiary)]">
                    CLI <StatusBadge value={ws.cli?.state || "n/a"} />
                  </span>
                  {inspect && (
                    <Chip tone="neutral" className="max-w-[260px] truncate font-mono" title={inspect.filename}>
                      {inspect.filename}
                    </Chip>
                  )}
                </>
              ) : (
                <Chip tone="muted">No workspace loaded</Chip>
              )}
            </div>
          </div>
        </header>
        <div ref={contentRef} className="content min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[1520px] px-6 py-7 xl:px-10">
            {nav === "open" && <OpenPage onLoaded={onLoaded} />}
            {nav === "overview" && ws && <OverviewPage ws={ws} />}
            {nav === "blackbox" && ws && <BlackboxPage ws={ws} />}
            {nav === "analysis" && ws && <AnalysisPage ws={ws} />}
            {nav === "chirp" && ws && <ChirpPage ws={ws} />}
            {nav === "tune" && ws && <TunePage ws={ws} />}
            {nav === "safety" && ws && <SafetyPage ws={ws} />}
            {nav === "compare" && ws && <ComparePage ws={ws} />}
            {nav === "cli" && ws && <CliPage ws={ws} />}
            {nav === "diagnostics" && ws && <DiagnosticsPage ws={ws} />}
            {nav !== "open" && !ws && <NoWorkspaceState page={nav} onOpen={() => setNav("open")} />}
          </div>
        </div>
      </main>
    </div>
  );
}
