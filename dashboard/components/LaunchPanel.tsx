"use client";
import { useState } from "react";
import { buildLaunchBody, postControl, type LaunchForm } from "@/lib/control";
import { toast } from "sonner";

const MAX_OPEN = 4;  // tope duro de posiciones simultáneas (fijado en el servidor)
const DEFAULTS: LaunchForm = {
  watchlist: [], capital: 40, gridN: 4, gridRangePct: 0.02, adxThreshold: 25,
  maxPositionNotional: 10, maxOpenPositions: MAX_OPEN, maxLeverage: 2, maxCoinNotional: 30,
  dailyLossLimit: 5, totalLossLimit: 20,
};

export function LaunchPanel({ coins, state }: { coins: { name: string }[]; state: string }) {
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
    if (r.ok) toast.success("Sesión lanzada");
    else toast.error(`No se pudo lanzar (${r.status}): ${(r.data as { detail?: string })?.detail ?? ""}`);
  }

  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>LAUNCH SESSION</div>
      {!idle && <div className="muted" style={{ fontSize: 12 }}>sesión activa — cierra para lanzar otra</div>}
      {idle && (
        <>
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
            <label>posición $ (≥10) <input type="number" min={10} step={1} defaultValue={f.maxPositionNotional} onChange={num("maxPositionNotional")} style={inputS} /></label>
            <label>capital <input type="number" defaultValue={f.capital} onChange={num("capital")} style={inputS} /></label>
            <label>grid_n <input type="number" defaultValue={f.gridN} onChange={num("gridN")} style={inputS} /></label>
            <label>max lev <input type="number" defaultValue={f.maxLeverage} onChange={num("maxLeverage")} style={inputS} /></label>
            <label>cap moneda $ <input type="number" defaultValue={f.maxCoinNotional} onChange={num("maxCoinNotional")} style={inputS} /></label>
            <label>adx umbral <input type="number" defaultValue={f.adxThreshold} onChange={num("adxThreshold")} style={inputS} /></label>
            <label>pérdida diaria <input type="number" defaultValue={f.dailyLossLimit} onChange={num("dailyLossLimit")} style={inputS} /></label>
            <label>pérdida total <input type="number" defaultValue={f.totalLossLimit} onChange={num("totalLossLimit")} style={inputS} /></label>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 8 }}>máx {MAX_OPEN} posiciones simultáneas (fijo)</div>
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
