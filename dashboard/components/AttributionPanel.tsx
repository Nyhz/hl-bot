"use client";
import type { Account } from "@/lib/types";
import { fmtUsd } from "@/lib/format";
import { pnlColor } from "@/lib/view";

// Descompone el P&L de sesión: de dónde sale y a dónde se va el dinero.
export function AttributionPanel({ account }: { account: Account }) {
  const rows: { label: string; value: number; decimals?: number; sign?: boolean }[] = [
    { label: "realizado", value: account.realized_pnl },
    { label: "funding", value: account.funding, decimals: 3 },
    { label: "fees", value: -account.fees_paid, decimals: 3 },
    { label: "no realizado", value: account.unrealized_pnl },
  ];
  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>ATRIBUCIÓN P&amp;L · sesión</div>
      {rows.map((r) => (
        <div key={r.label} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "2px 0" }}>
          <span className="muted">{r.label}</span>
          <span style={{ color: pnlColor(r.value) }}>{fmtUsd(r.value, r.decimals)}</span>
        </div>
      ))}
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14, fontWeight: 700,
        borderTop: "1px solid #1c1f26", marginTop: 6, paddingTop: 6 }}>
        <span>neto sesión</span>
        <span style={{ color: pnlColor(account.session_pnl) }} className="glow">{fmtUsd(account.session_pnl)}</span>
      </div>
    </div>
  );
}
