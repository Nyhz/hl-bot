import type { Account } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor } from "@/lib/view";

export function StatTiles({ account }: { account: Account }) {
  const tiles: { label: string; value: string; color?: string }[] = [
    { label: "OPEN", value: `${account.open_count} / ${account.max_open}` },
    { label: "WIN RATE", value: fmtPct(account.win_rate), color: "var(--neon-green)" },
    { label: "REALIZED", value: fmtUsd(account.realized_pnl), color: pnlColor(account.realized_pnl) },
    { label: "FEES PAID", value: fmtUsd(account.fees_paid, 3), color: "var(--neon-red)" },
    { label: "FUNDING", value: fmtUsd(account.funding, 3), color: pnlColor(account.funding) },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${tiles.length}, 1fr)`, gap: 1 }}>
      {tiles.map((t) => (
        <div key={t.label} className="panel" style={{ padding: 12 }}>
          <div className="muted" style={{ fontSize: 11 }}>{t.label}</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: t.color ?? "var(--text)" }}>{t.value}</div>
        </div>
      ))}
    </div>
  );
}
