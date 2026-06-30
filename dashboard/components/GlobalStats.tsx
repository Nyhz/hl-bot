import type { GlobalStats as GS } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor } from "@/lib/view";

function ModeCol({ title, color, m }: { title: string; color: string; m: GS["testnet"] }) {
  const rows: [string, string, string?][] = [
    ["sesiones", String(m.n_sessions)],
    ["net PnL", fmtUsd(m.net_pnl), pnlColor(m.net_pnl)],
    ["realizado", fmtUsd(m.realized_pnl), pnlColor(m.realized_pnl)],
    ["fees", fmtUsd(m.fees, 3)],
    ["funding", fmtUsd(m.funding, 3)],
    ["win rate", fmtPct(m.win_rate)],
  ];
  return (
    <div className="panel" style={{ padding: 12, flex: 1 }}>
      <div className="glow" style={{ color, fontWeight: 700, marginBottom: 8 }}>{title}</div>
      {rows.map(([label, value, c]) => (
        <div key={label} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "3px 0" }}>
          <span className="muted">{label}</span>
          <span style={{ color: c ?? "var(--text)" }}>{value}</span>
        </div>
      ))}
    </div>
  );
}
export function GlobalStats({ stats }: { stats: GS }) {
  return (
    <div style={{ display: "flex", gap: 12 }}>
      <ModeCol title="TESTNET" color="var(--neon-amber)" m={stats.testnet} />
      <ModeCol title="MAINNET" color="var(--neon-green)" m={stats.mainnet} />
    </div>
  );
}
