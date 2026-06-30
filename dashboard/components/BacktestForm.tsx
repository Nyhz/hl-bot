"use client";
import { useState } from "react";
import type { BacktestParams } from "@/lib/types";

const DEFAULTS: BacktestParams = {
  coin: "BTC", capital: 40, interval: "1m", n_candles: 1000,
  grid_n: 4, grid_range_pct: 0.02, skew_strength: 1.5, spread_vol_mult: 0.5,
  adx_threshold: 25, atr_stop_mult: 2, max_position_notional: 10, max_coin_notional: 30,
};

const inputS: React.CSSProperties = { width: "100%", background: "#0a0b0d", border: "1px solid #1c1f26", color: "var(--text)", borderRadius: 4, padding: "2px 6px", marginTop: 2 };

export function BacktestForm({ coins, busy, onRun }: {
  coins: { name: string }[]; busy: boolean; onRun: (p: BacktestParams) => void;
}) {
  const [f, setF] = useState<BacktestParams>(DEFAULTS);
  const num = (k: keyof BacktestParams) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: Number(e.target.value) }));
  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>BACKTEST LAB</div>
      <label style={{ fontSize: 12 }}>moneda
        <select value={f.coin} onChange={(e) => setF((p) => ({ ...p, coin: e.target.value }))} style={inputS}>
          {coins.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
        </select>
      </label>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 12, marginTop: 6 }}>
        <label>nº velas <input type="number" defaultValue={f.n_candles} onChange={num("n_candles")} style={inputS} /></label>
        <label>capital <input type="number" defaultValue={f.capital} onChange={num("capital")} style={inputS} /></label>
        <label>grid_n <input type="number" defaultValue={f.grid_n} onChange={num("grid_n")} style={inputS} /></label>
        <label>rango <input type="number" step={0.005} defaultValue={f.grid_range_pct} onChange={num("grid_range_pct")} style={inputS} /></label>
        <label>skew <input type="number" step={0.1} defaultValue={f.skew_strength} onChange={num("skew_strength")} style={inputS} /></label>
        <label>spread mult <input type="number" step={0.1} defaultValue={f.spread_vol_mult} onChange={num("spread_vol_mult")} style={inputS} /></label>
        <label>adx umbral <input type="number" defaultValue={f.adx_threshold} onChange={num("adx_threshold")} style={inputS} /></label>
        <label>atr stop <input type="number" step={0.1} defaultValue={f.atr_stop_mult} onChange={num("atr_stop_mult")} style={inputS} /></label>
        <label>posición $ <input type="number" defaultValue={f.max_position_notional} onChange={num("max_position_notional")} style={inputS} /></label>
        <label>cap moneda $ <input type="number" defaultValue={f.max_coin_notional} onChange={num("max_coin_notional")} style={inputS} /></label>
      </div>
      <button onClick={() => onRun(f)} disabled={busy}
        style={{ marginTop: 10, width: "100%", padding: 10, border: "none", borderRadius: 6,
          background: "var(--neon-green)", color: "#000", fontWeight: 700, cursor: "pointer" }}>
        {busy ? "corriendo…" : "▶ RUN BACKTEST"}
      </button>
    </div>
  );
}
