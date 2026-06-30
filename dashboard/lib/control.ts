export interface LaunchForm {
  watchlist: string[]; capital: number; gridN: number; gridRangePct: number; adxThreshold: number;
  maxPositionNotional: number; maxOpenPositions: number; maxLeverage: number;
  dailyLossLimit: number; totalLossLimit: number;
}
export interface LaunchBody {
  watchlist: string[]; capital: number; grid_n: number; grid_range_pct: number; adx_threshold: number;
  limits: { max_position_notional: number; max_open_positions: number; max_leverage: number; daily_loss_limit: number; total_loss_limit: number };
}
export function buildLaunchBody(f: LaunchForm): LaunchBody {
  return {
    watchlist: f.watchlist, capital: f.capital, grid_n: f.gridN,
    grid_range_pct: f.gridRangePct, adx_threshold: f.adxThreshold,
    limits: {
      max_position_notional: f.maxPositionNotional, max_open_positions: f.maxOpenPositions,
      max_leverage: f.maxLeverage, daily_loss_limit: f.dailyLossLimit, total_loss_limit: f.totalLossLimit,
    },
  };
}
export async function postControl(action: string, body?: unknown): Promise<{ ok: boolean; status: number; data: unknown }> {
  const res = await fetch(`/api/control/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  let data: unknown = null;
  try { data = await res.json(); } catch { /* sin cuerpo */ }
  return { ok: res.ok, status: res.status, data };
}
