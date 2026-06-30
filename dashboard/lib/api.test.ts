import { describe, it, expect, vi, afterEach } from "vitest";
import { api } from "./api";

afterEach(() => vi.restoreAllMocks());

describe("runBacktest", () => {
  it("POSTs params to /backtest and returns the result", async () => {
    const result = { metrics: { net_pnl: 1 }, equity_curve: [], trades: [], decisions: [] };
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(result), { status: 200 }));
    const r = await api.runBacktest({ coin: "ETH", capital: 40, n_candles: 100 } as never);
    expect(r).toEqual(result);
    const [url, opts] = spy.mock.calls[0];
    expect(String(url)).toContain("/backtest");
    expect((opts as RequestInit).method).toBe("POST");
  });
});
