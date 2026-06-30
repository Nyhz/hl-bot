"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SessionDetail as SD } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor, fmtDuration } from "@/lib/view";
import { EquityCurve } from "./EquityCurve";

export function SessionDetail({ sessionId }: { sessionId: number }) {
  const [d, setD] = useState<SD | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.getSession(sessionId).then((r) => { if (!cancelled) setD(r); }).catch(() => {});
    return () => { cancelled = true; };
  }, [sessionId]);
  if (!d) return <div className="panel muted" style={{ padding: 12 }}>cargando…</div>;
  const s = d.summary;
  return (
    <div className="panel" style={{ padding: 12, display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 16, alignItems: "baseline" }}>
        <span style={{ fontWeight: 700 }}>Sesión #{s.id}</span>
        <span style={{ color: s.mode === "mainnet" ? "var(--neon-green)" : "var(--neon-amber)" }}>{s.mode}</span>
        <span style={{ color: pnlColor(s.net_pnl), fontWeight: 700 }}>{fmtUsd(s.net_pnl)}</span>
        <span className="muted">realizado {fmtUsd(s.realized_pnl)} · fees {fmtUsd(s.fees, 3)} · funding {fmtUsd(s.funding, 3)}</span>
        <span className="muted">{s.n_trades} trades · {fmtPct(s.win_rate)} · {fmtDuration(s.duration_s)}</span>
      </div>
      <EquityCurve sessionId={s.id} equity={0} />
      <div>
        <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>TRADES</div>
        {d.trades.length === 0 && <div className="muted" style={{ fontSize: 12 }}>sin trades</div>}
        {d.trades.map((t, i) => (
          <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, padding: "2px 0" }}>
            <span className="muted">{new Date(t.ts * 1000).toLocaleTimeString()}</span>
            <span style={{ width: 90 }}>{t.dir}</span>
            <span>{t.coin}</span>
            <span className="muted">@{t.price}</span>
            <span style={{ color: pnlColor(t.closed_pnl), marginLeft: "auto" }}>{fmtUsd(t.closed_pnl)}</span>
          </div>
        ))}
      </div>
      <div>
        <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>DECISIONES</div>
        {d.decisions.slice(-30).map((dec, i) => (
          <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, padding: "2px 0" }}>
            <span className="muted">{new Date(dec.ts * 1000).toLocaleTimeString()}</span>
            <span style={{ width: 90 }}>{dec.action}</span>
            <span>{dec.coin}</span>
            <span className="muted" style={{ fontStyle: "italic", marginLeft: "auto" }}>{dec.reason}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
