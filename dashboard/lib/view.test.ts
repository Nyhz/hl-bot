import { describe, it, expect } from "vitest";
import { slotLayout, slotItems } from "./view";

describe("slotLayout", () => {
  it("mapea el nº de posiciones al reparto", () => {
    expect(slotLayout(0)).toBe("idle");
    expect(slotLayout(1)).toBe("one");
    expect(slotLayout(2)).toBe("two");
    expect(slotLayout(3)).toBe("grid");
    expect(slotLayout(4)).toBe("grid");
  });
});

describe("slotItems", () => {
  const pos = (coin: string) => ({ coin, side: "long", leverage: 2, notional: 10, size: 1,
    entry_px: 100, mark_px: null, unrealized_pnl: 0, liq_px: null });
  it("ordena por coin, capa a 4 y adjunta el coinView", () => {
    const positions = [pos("SOL"), pos("BTC"), pos("ETH")] as never;
    const coins = { BTC: { mid: 1 }, ETH: { mid: 2 }, SOL: { mid: 3 } } as never;
    const items = slotItems(positions, coins);
    expect(items.map((i) => i.coin)).toEqual(["BTC", "ETH", "SOL"]);
    expect(items[0].coinView).toEqual({ mid: 1 });
  });
  it("nunca devuelve más de 4", () => {
    const positions = ["A", "B", "C", "D", "E"].map(pos) as never;
    expect(slotItems(positions, {} as never).length).toBe(4);
  });
});
