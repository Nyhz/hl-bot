"use client";
import { useEffect, useState } from "react";
import type { CoinView, MarkoutRow, Snapshot } from "@/lib/types";
import { api } from "@/lib/api";

// Spread del BBO en bps sobre el mid; null sin datos frescos de WebSocket.
export function spreadBps(cv: CoinView): number | null {
  const bid = cv.bbo?.[0], ask = cv.bbo?.[1];
  if (bid == null || ask == null || !cv.mid) return null;
  return ((ask - bid) / cv.mid) * 1e4;
}

// Vista del flujo del tape: texto, color y anchos de la barra bilateral.
export function flowView(ratio: number | null | undefined) {
  if (ratio == null) return { label: "—", color: "var(--muted)", buyPct: 0, sellPct: 0 };
  const pct = Math.min(1, Math.abs(ratio)) * 100;
  return {
    label: `${ratio > 0 ? "+" : ""}${(ratio * 100).toFixed(0)}%`,
    color: ratio > 0 ? "var(--neon-green)" : "var(--neon-red)",
    buyPct: ratio > 0 ? pct : 0,
    sellPct: ratio < 0 ? pct : 0,
  };
}

export function fmtBps(n: number | null | undefined): string {
  if (n == null) return "—";
  return `${n > 0 ? "+" : ""}${n.toFixed(1)}`;
}

export function bpsColor(n: number | null | undefined): string {
  if (n == null) return "var(--muted)";
  return n < 0 ? "var(--neon-red)" : "var(--neon-green)";
}

function FlowBar({ ratio }: { ratio: number | null | undefined }) {
  const v = flowView(ratio);
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span style={{ display: "inline-flex", width: 60, height: 6, background: "#1c1f26", borderRadius: 3, overflow: "hidden" }}>
        <span style={{ width: "50%", display: "flex", justifyContent: "flex-end" }}>
          <span style={{ width: `${v.sellPct}%`, background: "var(--neon-red)" }} />
        </span>
        <span style={{ width: "50%", display: "flex" }}>
          <span style={{ width: `${v.buyPct}%`, background: "var(--neon-green)" }} />
        </span>
      </span>
      <span style={{ fontSize: 10, color: v.color, minWidth: 32 }}>{v.label}</span>
    </span>
  );
}

export function MicroPanel({ snapshot }: { snapshot: Snapshot }) {
  // El padre remonta con key=session_id: el estado se resetea solo al cambiar
  // de sesión (patrón del repo para el lint set-state-in-effect de Next 16).
  const [markouts, setMarkouts] = useState<MarkoutRow[]>([]);
  const sid = snapshot.session_id;
  useEffect(() => {
    if (sid == null) return;
    let alive = true;
    const load = () =>
      api.getMarkouts(sid).then((r) => { if (alive) setMarkouts(r); }).catch(() => {});
    load();
    const t = setInterval(load, 30_000);
    return () => { alive = false; clearInterval(t); };
  }, [sid]);

  const coins = Object.entries(snapshot.coins);
  const l1 = snapshot.l1_actions;
  if (coins.length === 0 && !l1) return null;

  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>
        MICROESTRUCTURA · spread / flujo del tape
      </div>
      {coins.length === 0 && <div className="muted" style={{ fontSize: 12 }}>sin sesión</div>}
      {coins.map(([coin, cv]) => {
        const sp = spreadBps(cv);
        return (
          <div key={coin} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "4px 0", fontSize: 12 }}>
            <b style={{ minWidth: 42 }}>{coin}</b>
            {cv.toxic ? (
              <span title="toxicity gate: flujo agresivo, grid retirado"
                    style={{ fontSize: 10, color: "var(--neon-red)", fontWeight: 700 }}>
                PULLED
              </span>
            ) : (
              <span className="muted" title="spread del BBO en bps" style={{ fontSize: 11 }}>
                {sp == null ? "ws —" : `${sp.toFixed(1)} bps`}
              </span>
            )}
            <FlowBar ratio={cv.flow_ratio} />
          </div>
        );
      })}
      {markouts.length > 0 && (
        <div style={{ marginTop: 8, borderTop: "1px solid #1c1f26", paddingTop: 6 }}>
          <div className="muted" title="bps medios a favor del fill; negativo = selección adversa" style={{ fontSize: 11, marginBottom: 4 }}>
            FILL QUALITY · markout bps (+5s/+30s/+2m)
          </div>
          {markouts.map((m) => (
            <div key={m.coin} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, padding: "2px 0" }}>
              <span><b>{m.coin}</b> <span className="muted">×{m.n}</span></span>
              <span>
                <span style={{ color: bpsColor(m.m5) }}>{fmtBps(m.m5)}</span>
                {" / "}
                <span style={{ color: bpsColor(m.m30) }}>{fmtBps(m.m30)}</span>
                {" / "}
                <span style={{ color: bpsColor(m.m120) }}>{fmtBps(m.m120)}</span>
              </span>
            </div>
          ))}
        </div>
      )}
      {l1 && (
        <div className="muted" title="acciones L1 gastadas (presupuesto: 10k + 1 por USDC negociado)"
             style={{ marginTop: 8, borderTop: "1px solid #1c1f26", paddingTop: 6, fontSize: 11 }}>
          L1 · órdenes {l1.orders} · cancels {l1.cancels} · total {l1.total}
        </div>
      )}
    </div>
  );
}
