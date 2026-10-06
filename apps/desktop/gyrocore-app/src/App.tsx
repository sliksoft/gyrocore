import { useMemo, useState } from "react";
import type { InspectResult, NavId, WorkspacePayload } from "./bridge/types";
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
import "./styles.css";

const NAV: Array<{ id: NavId; label: string }> = [
  { id: "open", label: "Open" },
  { id: "overview", label: "Overview" },
  { id: "blackbox", label: "Blackbox" },
  { id: "analysis", label: "Analysis" },
  { id: "chirp", label: "CHIRP" },
  { id: "tune", label: "Tune" },
  { id: "safety", label: "Safety" },
  { id: "compare", label: "Compare" },
  { id: "cli", label: "CLI" },
  { id: "diagnostics", label: "Diagnostics" },
];

export default function App() {
  const [nav, setNav] = useState<NavId>("open");
  const [ws, setWs] = useState<WorkspacePayload | null>(null);
  const [inspect, setInspect] = useState<InspectResult | null>(null);

  const title = useMemo(() => NAV.find((n) => n.id === nav)?.label || "GyroCore", [nav]);

  function onLoaded(payload: WorkspacePayload, insp?: InspectResult | null) {
    setWs(payload);
    setInspect(insp || null);
    setNav("overview");
  }

  return (
    <div className="app" data-testid="app-shell">
      <aside className="nav">
        <div className="brand">
          GyroCore
          <span>local · offline · no FC write</span>
        </div>
        {NAV.map((item) => (
          <button
            key={item.id}
            type="button"
            className={nav === item.id ? "active" : ""}
            data-testid={`nav-${item.id}`}
            onClick={() => setNav(item.id)}
            disabled={item.id !== "open" && !ws}
          >
            {item.label}
          </button>
        ))}
        <div className="hint">
          Engine: Python Core
          <br />
          CLI: authorize_cli only
          <br />
          No MSP / serial / apply-to-FC
        </div>
      </aside>
      <main className="main">
        <div className="topbar">
          <div className="title">{title}</div>
          <div className="meta">
            {ws
              ? `${ws.demo ? "DEMO · " : ""}${ws.scenario} · CLI ${ws.cli?.state || "n/a"}`
              : "No workspace loaded"}
            {inspect ? ` · ${inspect.filename}` : ""}
          </div>
        </div>
        <div className="content">
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
          {nav !== "open" && !ws && (
            <div className="panel">
              <p className="muted">Load a log or demo fixture first.</p>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
