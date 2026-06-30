"use client";
import type { BacktestResult, BacktestMetrics } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor } from "@/lib/view";
import { EquityCurve } from "./EquityCurve";

export function metricRows(m: BacktestMetrics): { label: string; value: string; color?: string }[] {
  return [
    { label: "PnL neto", value: fmtUsd(m.net_pnl), color: pnlColor(m.net_pnl) },
    { label: "realizado", value: fmtUsd(m.realized_pnl), color: pnlColor(m.realized_pnl) },
    { label: "fees", value: fmtUsd(-m.fees, 3), color: "var(--neon-red)" },
    { label: "funding", value: fmtUsd(m.funding, 3), color: pnlColor(m.funding) },
    { label: "max drawdown", value: fmtUsd(-m.max_drawdown), color: "var(--neon-red)" },
    { label: "trades (cierres)", value: String(m.n_trades) },
    { label: "win rate", value: fmtPct(m.win_rate), color: "var(--neon-green)" },
  ];
}

export function BacktestResults({ result }: { result: BacktestResult }) {
  const m = result.metrics;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="stat-tiles">
        {metricRows(m).map((r) => (
          <div key={r.label} className="panel" style={{ padding: 12, minWidth: 0 }}>
            <div className="muted" style={{ fontSize: 11 }}>{r.label}</div>
            <div style={{ fontSize: 18, fontWeight: 700, color: r.color ?? "var(--text)" }}>{r.value}</div>
          </div>
        ))}
      </div>
      <EquityCurve key={`${result.equity_curve.length}:${result.equity_curve[0]?.ts ?? 0}`}
                   sessionId={null} equity={0} seed={result.equity_curve} />
      <div className="panel" style={{ padding: 12 }}>
        <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>
          EJECUCIONES ({result.trades.length}) · el PnL se realiza al cerrar (las aperturas van a —)
        </div>
        {result.trades.slice(-50).map((t, i) => {
          const isClose = t.dir.includes("Close");
          return (
            <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, padding: "2px 0" }}>
              <span className="muted">{new Date(t.ts * 1000).toLocaleString()}</span>
              <span style={{ width: 90 }}>{t.dir}</span>
              <span className="muted">@{t.price}</span>
              <span style={{ marginLeft: "auto", color: isClose ? pnlColor(t.closed_pnl) : "var(--muted)" }}>
                {isClose ? fmtUsd(t.closed_pnl) : "—"}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
