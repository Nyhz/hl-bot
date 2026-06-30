import { describe, it, expect } from "vitest";
import { buildLaunchBody } from "../control";

describe("buildLaunchBody", () => {
  it("builds the bot LaunchBody from form state", () => {
    const body = buildLaunchBody({
      watchlist: ["ETH", "BTC"], capital: 40, gridN: 4, gridRangePct: 0.02, adxThreshold: 25,
      maxPositionNotional: 15, maxOpenPositions: 3, maxLeverage: 2, dailyLossLimit: 5, totalLossLimit: 20,
    });
    expect(body).toEqual({
      watchlist: ["ETH", "BTC"], capital: 40, grid_n: 4, grid_range_pct: 0.02, adx_threshold: 25,
      limits: { max_position_notional: 15, max_open_positions: 3, max_leverage: 2, daily_loss_limit: 5, total_loss_limit: 20 },
    });
  });
});
