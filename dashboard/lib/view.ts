import type { Position } from "./types";

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
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function pnlColor(n: number): string {
  return n < 0 ? "var(--neon-red)" : "var(--neon-green)";
}

export function equitySeries(rows: { ts: number; total_pnl: number }[]): { time: number; value: number }[] {
  return rows
    .map((r) => ({ time: r.ts, value: r.total_pnl }))
    .sort((a, b) => a.time - b.time);
}
