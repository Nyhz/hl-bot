export type Mode = "testnet" | "mainnet";
export type SessionState = "idle" | "scanning" | "active" | "closing";

export interface Condition { name: string; value: number; threshold: number; met: boolean; }
export interface Trigger { coin: string; level: number; side: string; action: string; description: string; }
export interface CoinView {
  mid: number; mode: "grid" | "trend"; funding: number | null;
  triggers: Trigger[]; conditions: Condition[]; armed: boolean;
  // microestructura (F3.5) — null/ausente sin WebSocket fresco en el bot
  bbo?: [number | null, number | null];
  microprice?: number | null;
  sigma?: number | null;
  flow_ratio?: number | null;
  toxic?: boolean;          // grid retirado por toxicity gate
}
export interface WhaleFill {
  ts: number; coin: string; side: string; px: number; sz: number;
  dir: string; closed_pnl: number; tid: string;
}
export interface L1Actions { orders: number; cancels: number; other: number; total: number; }
export interface MarkoutRow {
  coin: string; n: number;
  m5: number | null; m30: number | null; m120: number | null;
}
export interface Position {
  coin: string; side: string; leverage: number | null; notional: number;
  size: number; entry_px: number; mark_px: number | null;
  unrealized_pnl: number; liq_px: number | null;
}
export interface Account {
  equity: number; session_pnl: number; realized_pnl: number; unrealized_pnl: number;
  win_rate: number; fees_paid: number; funding: number; open_count: number; max_open: number;
}
export interface TapeEvent {
  ts: number; kind: "open" | "close" | "decision"; coin: string | null;
  side: string | null; price: number | null; pnl: number | null; reason: string;
}
export interface Snapshot {
  state: SessionState; paused: boolean; mode: Mode;
  session_id: number | null; session_started_at: number | null;
  watchlist: string[]; coins: Record<string, CoinView>;
  account: Account; positions: Position[]; tape_recent: TapeEvent[];
  l1_actions?: L1Actions;
}
export interface Candle { time: number; open: number; high: number; low: number; close: number; }
export interface SessionSummary {
  id: number; mode: Mode; started_at: number | null; ended_at: number | null;
  duration_s: number | null; capital: number; n_trades: number; wins: number;
  realized_pnl: number; fees: number; funding: number; win_rate: number; net_pnl: number;
}
export interface GlobalStatsMode {
  n_sessions: number; realized_pnl: number; fees: number; funding: number;
  net_pnl: number; win_rate: number; best_session: number | null; worst_session: number | null;
}
export interface GlobalStats { testnet: GlobalStatsMode; mainnet: GlobalStatsMode; }
export interface SessionDetail {
  summary: SessionSummary;
  trades: { coin: string; side: string; dir: string; price: number; size: number; fee: number; closed_pnl: number; ts: number }[];
  equity_curve: { ts: number; total_pnl: number }[];
  decisions: { ts: number; coin: string; action: string; reason: string }[];
}
export interface BacktestParams {
  coin: string; capital: number; interval?: string; n_candles: number;
  grid_n?: number; grid_range_pct?: number; skew_strength?: number; spread_vol_mult?: number;
  adx_threshold?: number; atr_stop_mult?: number; max_position_notional?: number; max_coin_notional?: number;
}
export interface BacktestMetrics {
  start_equity: number; final_equity: number; net_pnl: number; realized_pnl: number;
  fees: number; funding: number; n_trades: number; win_rate: number; max_drawdown: number;
}
export interface BacktestResult {
  metrics: BacktestMetrics;
  equity_curve: { ts: number; total_pnl: number }[];
  trades: { coin: string; dir: string; price: number; size: number; fee: number; closed_pnl: number; ts: number }[];
  decisions: { ts: number; coin: string; action: string; reason: string }[];
}
