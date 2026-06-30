import type { SessionSummary } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor, fmtDuration } from "@/lib/view";

export function SessionsList({ sessions, onSelect, selectedId }: {
  sessions: SessionSummary[]; onSelect: (id: number) => void; selectedId: number | null;
}) {
  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>SESIONES</div>
      {sessions.length === 0 && <div className="muted" style={{ fontSize: 12 }}>sin sesiones</div>}
      {sessions.map((s) => (
        <div key={s.id} onClick={() => onSelect(s.id)}
          style={{ display: "grid", gridTemplateColumns: "40px 80px 1fr 1fr 1fr 1fr", gap: 8, alignItems: "center",
            padding: "8px 4px", borderBottom: "1px solid #1c1f26", cursor: "pointer",
            background: s.id === selectedId ? "#14171c" : "transparent", fontSize: 12 }}>
          <span className="muted">#{s.id}</span>
          <span style={{ color: s.mode === "mainnet" ? "var(--neon-green)" : "var(--neon-amber)" }}>{s.mode}</span>
          <span style={{ color: pnlColor(s.net_pnl) }}>{fmtUsd(s.net_pnl)}</span>
          <span className="muted">{s.n_trades} trades</span>
          <span className="muted">{fmtPct(s.win_rate)}</span>
          <span className="muted">{fmtDuration(s.duration_s)}</span>
        </div>
      ))}
    </div>
  );
}
