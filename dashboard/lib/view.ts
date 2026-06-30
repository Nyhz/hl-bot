import type { Candle, Condition, Position } from "./types";

export function conditionPct(c: Condition): number {
  if (c.met) return 1;
  if (!c.threshold) return 0;
  const r = Math.abs(c.value) / Math.abs(c.threshold);
  return Math.max(0, Math.min(1, r));
}

export function positionView(pos: Position, mid: number | null) {
  const markPx = mid ?? pos.mark_px ?? pos.entry_px;
  const isLong = pos.side === "long";
  return {
    sideLabel: pos.side.toUpperCase(),
    sideColor: isLong ? "var(--neon-green)" : "var(--neon-red)",
    markPx,
    pnlColor: pos.unrealized_pnl < 0 ? "var(--neon-red)" : "var(--neon-green)",
  };
}

export function fmtAge(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return "—";
  if (sec < 0) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function pnlColor(n: number): string {
  return n < 0 ? "var(--neon-red)" : "var(--neon-green)";
}

// Funding horario como porcentaje. Positivo = los largos pagan (coste si estás largo).
export function fmtFunding(f: number | null | undefined): string {
  if (f === null || f === undefined || Number.isNaN(f)) return "—";
  return `${(f * 100).toFixed(4)}%/h`;
}

// Color desde la óptica de un largo: funding positivo = pagas (rojo), negativo = cobras (verde).
export function fundingColor(f: number | null | undefined): string {
  if (f === null || f === undefined || Number.isNaN(f) || f === 0) return "var(--muted)";
  return f > 0 ? "var(--neon-red)" : "var(--neon-green)";
}

export function fmtDuration(sec: number | null): string {
  if (sec === null || sec === undefined || Number.isNaN(sec) || sec < 0) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}

export function candleSeries(candles: Candle[]): Candle[] {
  return [...candles].sort((a, b) => a.time - b.time);
}

export function equitySeries(rows: { ts: number; total_pnl: number }[]): { time: number; value: number }[] {
  return rows
    .map((r) => ({ time: r.ts, value: r.total_pnl }))
    .sort((a, b) => a.time - b.time);
}
