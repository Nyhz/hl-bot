import type { Candle, SessionSummary, GlobalStats, SessionDetail, TapeEvent, BacktestParams, BacktestResult, MarkoutRow, WhaleFill } from "./types";

const BASE = () => process.env.NEXT_PUBLIC_BOT_HTTP ?? "http://localhost:3300";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE()}${path}`);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  getCandles: (coin: string, interval = "1m") =>
    get<Candle[]>(`/candles/${coin}?interval=${interval}`),
  getEquityCurve: (sessionId: number) =>
    get<{ ts: number; total_pnl: number }[]>(`/equity_curve?session_id=${sessionId}`),
  getCoins: () => get<{ name: string; szDecimals: number }[]>(`/coins`),
  getTape: (limit = 50) => get<TapeEvent[]>(`/tape?limit=${limit}`),
  getSessions: (mode?: string) =>
    get<SessionSummary[]>(`/sessions${mode ? `?mode=${mode}` : ""}`),
  getSession: (id: number) => get<SessionDetail>(`/sessions/${id}`),
  getStatsGlobal: () => get<GlobalStats>(`/stats/global`),
  getMarkouts: (sessionId?: number | null) =>
    get<MarkoutRow[]>(`/markouts${sessionId != null ? `?session_id=${sessionId}` : ""}`),
  getWhales: () => get<Record<string, WhaleFill[]>>(`/whales`),
  runBacktest: async (params: BacktestParams): Promise<BacktestResult> => {
    const res = await fetch(`${BASE()}/backtest`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
    });
    if (!res.ok) throw new Error(`POST /backtest -> ${res.status}`);
    return res.json() as Promise<BacktestResult>;
  },
};
