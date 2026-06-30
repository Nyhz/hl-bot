"use client";
import { useState } from "react";
import { buildLaunchBody, postControl, type LaunchForm } from "@/lib/control";
import { toast } from "sonner";
import { Hint } from "./Hint";

const MAX_OPEN = 4;  // tope duro de posiciones simultáneas (fijado en el servidor)
const DEFAULTS: LaunchForm = {
  watchlist: [], capital: 40, gridN: 4, gridRangePct: 0.02, adxThreshold: 25,
  maxPositionNotional: 10, maxOpenPositions: MAX_OPEN, maxLeverage: 2, maxCoinNotional: 30,
  dailyLossLimit: 5, totalLossLimit: 20,
};

export function LaunchPanel({ coins, state, onLaunched }: { coins: { name: string }[]; state: string; onLaunched?: () => void }) {
  const [f, setF] = useState<LaunchForm>(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const idle = state === "idle";
  const toggle = (c: string) =>
    setF((p) => ({ ...p, watchlist: p.watchlist.includes(c) ? p.watchlist.filter((x) => x !== c) : [...p.watchlist, c] }));
  const num = (k: keyof LaunchForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: Number(e.target.value) }));

  async function launch() {
    if (!f.watchlist.length) { toast.error("Elige al menos un par"); return; }
    setBusy(true);
    const r = await postControl("launch", buildLaunchBody(f));
    setBusy(false);
    if (r.ok) { toast.success("Sesión lanzada"); onLaunched?.(); }
    else toast.error(`No se pudo lanzar (${r.status}): ${(r.data as { detail?: string })?.detail ?? ""}`);
  }

  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>LAUNCH SESSION</div>
      {!idle && <div className="muted" style={{ fontSize: 12 }}>sesión activa — cierra para lanzar otra</div>}
      {idle && (
        <>
          <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>
            Pares a vigilar <Hint text="Monedas que la sesión vigila y opera. Elige al menos una." />
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
            {coins.map((c) => (
              <button key={c.name} onClick={() => toggle(c.name)}
                style={{ padding: "4px 8px", border: "1px solid #1c1f26", borderRadius: 6,
                  background: f.watchlist.includes(c.name) ? "var(--neon-green)" : "transparent",
                  color: f.watchlist.includes(c.name) ? "#000" : "var(--text)", cursor: "pointer", fontSize: 12 }}>
                {c.name}
              </button>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 12 }}>
            <label>Tamaño de posición ($) <Hint text="USDC por orden/posición. Mínimo $10 (el de Hyperliquid). Lo usan cada rung del grid y cada entrada de tendencia." /><input type="number" min={10} step={1} defaultValue={f.maxPositionNotional} onChange={num("maxPositionNotional")} style={inputS} /></label>
            <label>Capital ($) <Hint text="USDC asignado a la sesión. Debe cubrir grid_n × tamaño de posición." /><input type="number" defaultValue={f.capital} onChange={num("capital")} style={inputS} /></label>
            <label>Rungs del grid (grid_n) <Hint text="Nº de escalones (órdenes) por lado del grid. Más rungs = más órdenes y más fees." /><input type="number" defaultValue={f.gridN} onChange={num("gridN")} style={inputS} /></label>
            <label>Apalancamiento máx (×) <Hint text="Leverage máximo; el bot lo fija isolated por moneda y rechaza órdenes que lo superen." /><input type="number" defaultValue={f.maxLeverage} onChange={num("maxLeverage")} style={inputS} /></label>
            <label>Tope por moneda ($) <Hint text="Notional máximo de posición abierta por moneda. Evita que una sola acapare o que se apile grid+tendencia." /><input type="number" defaultValue={f.maxCoinNotional} onChange={num("maxCoinNotional")} style={inputS} /></label>
            <label>Umbral ADX <Hint text="Fuerza de tendencia (ADX) a partir de la cual el bot pasa de grid a modo tendencia. Típico 25." /><input type="number" defaultValue={f.adxThreshold} onChange={num("adxThreshold")} style={inputS} /></label>
            <label>Stop pérdida diaria ($) <Hint text="Si la pérdida del día llega a este valor, el bot pausa y cierra la sesión automáticamente." /><input type="number" defaultValue={f.dailyLossLimit} onChange={num("dailyLossLimit")} style={inputS} /></label>
            <label>Stop pérdida total ($) <Hint text="Si la pérdida total de la sesión llega a este valor, el bot pausa y cierra automáticamente." /><input type="number" defaultValue={f.totalLossLimit} onChange={num("totalLossLimit")} style={inputS} /></label>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>
            máx {MAX_OPEN} posiciones simultáneas <Hint text="Tope duro fijado en el servidor; no editable." />
          </div>
          <button onClick={launch} disabled={busy}
            style={{ marginTop: 10, width: "100%", padding: 10, border: "none", borderRadius: 6,
              background: "var(--neon-green)", color: "#000", fontWeight: 700, cursor: "pointer" }}>
            {busy ? "…" : "▶ LAUNCH"}
          </button>
        </>
      )}
    </div>
  );
}
const inputS: React.CSSProperties = { width: "100%", background: "#0a0b0d", border: "1px solid #1c1f26", color: "var(--text)", borderRadius: 4, padding: "2px 6px", marginTop: 2 };
