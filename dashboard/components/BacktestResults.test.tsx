import { describe, it, expect } from "vitest";
import { metricRows } from "./BacktestResults";

describe("metricRows", () => {
  it("incluye PnL neto, fees, funding y win rate con las métricas dadas", () => {
    const rows = metricRows({
      start_equity: 1000, final_equity: 1010, net_pnl: 10, realized_pnl: 12,
      fees: 1.5, funding: -0.5, n_trades: 8, win_rate: 0.5, max_drawdown: 20,
    });
    const labels = rows.map((r) => r.label);
    expect(labels).toContain("PnL neto");
    expect(labels).toContain("fees");
    expect(labels).toContain("win rate");
    const net = rows.find((r) => r.label === "PnL neto")!;
    expect(net.value).toContain("10");           // formateado como USD
  });
});
