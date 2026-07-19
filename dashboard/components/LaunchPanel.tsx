"use client";
import { useState } from "react";
import { buildLaunchBody, postControl, type LaunchForm } from "@/lib/control";
import { toast } from "sonner";
import { Hint } from "./Hint";

// El resto del perfil (pares, spread, grid, caps de exposición, freno de
// régimen) es FIJO en el servidor: son parámetros de rentabilidad validados
// con test runs y no se eligen por sesión.
const MIN_CAPITAL = 30; // grid_n(3) × $10 por rung; el bot lo valida igual
const DEFAULTS: LaunchForm = { capital: 60, maxLoss: 10 };

export function LaunchPanel({ state, onLaunched }: { state: string; onLaunched?: () => void }) {
  const [f, setF] = useState<LaunchForm>(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const idle = state === "idle";
  const num = (k: keyof LaunchForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: Number(e.target.value) }));

  async function launch() {
    if (f.capital < MIN_CAPITAL) { toast.error(`Capital mínimo $${MIN_CAPITAL}`); return; }
    if (f.maxLoss <= 0) { toast.error("La pérdida máxima debe ser mayor que 0"); return; }
    if (f.maxLoss > f.capital) { toast.error("La pérdida máxima no puede superar el capital"); return; }
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
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 12 }}>
            <label>Capital ($) <Hint text={`USDC asignado a la sesión. Mínimo $${MIN_CAPITAL} (3 rungs de $10 por lado del grid).`} /><input type="number" min={MIN_CAPITAL} step={5} defaultValue={f.capital} onChange={num("capital")} style={inputS} /></label>
            <label>Pérdida máxima ($) <Hint text="Si la pérdida (diaria o total) llega a este valor, el bot deja de abrir y cierra la sesión automáticamente." /><input type="number" min={1} step={1} defaultValue={f.maxLoss} onChange={num("maxLoss")} style={inputS} /></label>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 10, lineHeight: 1.7 }}>
            Perfil fijo <Hint text="Parámetros de estrategia validados con los test runs; se cambian en código, no por sesión." />:
            BTC + ETH · grid A-S 3 rungs/lado · spread suelo 15 bps · momentum off ·
            caps $10/orden · $30/moneda · Δneto $45 · 2× isolated
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
