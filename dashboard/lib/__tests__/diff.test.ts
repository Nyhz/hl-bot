import { describe, it, expect } from "vitest";
import { diffPositions } from "../diff";
import type { Position } from "../types";
const p = (coin: string): Position => ({ coin, side: "long", leverage: 2, notional: 10, size: 1, entry_px: 1, mark_px: null, unrealized_pnl: 0, liq_px: null });

describe("diffPositions", () => {
  it("detects opened and closed by coin", () => {
    const r = diffPositions([p("ETH"), p("BTC")], [p("BTC"), p("SOL")]);
    expect(r.opened).toEqual(["SOL"]);
    expect(r.closed).toEqual(["ETH"]);
  });
  it("no change", () => {
    expect(diffPositions([p("ETH")], [p("ETH")])).toEqual({ opened: [], closed: [] });
  });
});
