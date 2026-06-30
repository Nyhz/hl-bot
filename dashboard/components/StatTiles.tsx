"use client";
import type { Account } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor } from "@/lib/view";
import { NumberTicker } from "./NumberTicker";

export function StatTiles({ account }: { account: Account }) {
  const staticTiles: { label: string; value: string; color?: string }[] = [
    { label: "OPEN", value: `${account.open_count} / ${account.max_open}` },
    { label: "WIN RATE", value: fmtPct(account.win_rate), color: "var(--neon-green)" },
  ];
  const numericTiles: { label: string; value: number; decimals?: number; color: string }[] = [
    { label: "REALIZED", value: account.realized_pnl, color: pnlColor(account.realized_pnl) },
    { label: "FEES PAID", value: account.fees_paid, decimals: 3, color: "var(--neon-red)" },
    { label: "FUNDING", value: account.funding, decimals: 3, color: pnlColor(account.funding) },
  ];
  const totalCols = staticTiles.length + numericTiles.length;
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${totalCols}, 1fr)`, gap: 1 }}>
      {staticTiles.map((t) => (
        <div key={t.label} className="panel" style={{ padding: 12 }}>
          <div className="muted" style={{ fontSize: 11 }}>{t.label}</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: t.color ?? "var(--text)" }}>{t.value}</div>
        </div>
      ))}
      {numericTiles.map((t) => (
        <div key={t.label} className="panel" style={{ padding: 12 }}>
          <div className="muted" style={{ fontSize: 11 }}>{t.label}</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: t.color }}>
            <NumberTicker value={t.value} format={(n) => fmtUsd(n, t.decimals)} />
          </div>
        </div>
      ))}
    </div>
  );
}
