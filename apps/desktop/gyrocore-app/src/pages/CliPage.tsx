import { useState } from "react";
import type { WorkspacePayload } from "../bridge/types";
import { StatusBadge } from "../components/StatusBadge";

async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

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

  return (
    <div className="stack" data-testid="cli-page">
      <div className="panel">
        <h2>
          CLI output <StatusBadge value={cli.state} />
        </h2>
        <p className="muted">{cli.label}</p>
        <div className="kv">
          <div>Authorized</div>
          <div>{String(cli.authorized)}</div>
          <div>Actionable</div>
          <div>{String(cli.actionable)}</div>
          {cli.source_profile != null && (
            <>
              <div>PID profile</div>
              <div className="mono">
                {cli.source_profile} → {cli.target_profile}
              </div>
            </>
          )}
          {cli.bundle_id && (
            <>
              <div>Bundle</div>
              <div className="mono">{cli.bundle_id}</div>
            </>
          )}
          {cli.firmware_provenance && (
            <>
              <div>Firmware</div>
              <div className="mono">{JSON.stringify(cli.firmware_provenance)}</div>
            </>
          )}
        </div>
        {/* Explicit absence of FC apply */}
        <p className="muted" data-testid="no-fc-apply">
          No Apply to FC · No MSP · No serial — copy CLI text only.
        </p>
      </div>

      {cli.state === "authorized" && (
        <div className="grid2">
          <div className="panel" data-testid="apply-cli-panel">
            <h3>AUTHORIZED APPLY CLI</h3>
            <div className="cli-box">{cli.apply_cli}</div>
            <div className="row" style={{ marginTop: "0.5rem" }}>
              <button type="button" className="primary" data-testid="copy-apply" onClick={() => onCopy("apply")}>
                Copy APPLY CLI
              </button>
            </div>
          </div>
          <div className="panel" data-testid="rollback-cli-panel">
            <h3>AUTHORIZED ROLLBACK CLI</h3>
            <div className="cli-box">{cli.rollback_cli}</div>
            <div className="row" style={{ marginTop: "0.5rem" }}>
              <button type="button" data-testid="copy-rollback" onClick={() => onCopy("rollback")}>
                Copy ROLLBACK CLI
              </button>
            </div>
          </div>
        </div>
      )}

      {cli.state === "preview" && (
        <div className="panel" data-testid="preview-cli-panel">
          <h3>WARN PREVIEW — NOT PASTE-READY</h3>
          <div className="cli-box preview">{cli.preview_cli}</div>
          <ul className="checks">
            {(cli.reasons || []).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {cli.state === "denied" && (
        <div className="panel" data-testid="denied-cli-panel">
          <h3>BLOCK — no apply CLI</h3>
          <div className="cli-box denied">No apply_cli / paste_ready_cli fields.</div>
          <ul className="checks">
            {(cli.blocked_reasons || []).map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </div>
      )}

      {cli.changed_settings && (
        <div className="panel">
          <h3>Changed settings</h3>
          <pre className="mono muted">{JSON.stringify(cli.changed_settings, null, 2)}</pre>
        </div>
      )}
      {cli.safety_provenance && (
        <div className="panel">
          <h3>Safety provenance</h3>
          <pre className="mono muted" style={{ maxHeight: 240, overflow: "auto" }}>
            {JSON.stringify(cli.safety_provenance, null, 2)}
          </pre>
        </div>
      )}
      {note && <div className="banner info">{note}</div>}
    </div>
  );
}
