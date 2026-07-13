import { describe, it, expect } from "vitest";
import { whaleRows, shortAddr } from "./WhalePanel";
import type { WhaleFill } from "@/lib/types";

const f = (tid: string, ts: number, coin = "BTC"): WhaleFill => ({
  ts, coin, side: "B", px: 61000, sz: 0.001, dir: "Open Long", closed_pnl: 0, tid,
});

describe("whaleRows", () => {
  it("aplana direcciones y ordena por ts desc", () => {
    const rows = whaleRows({
      "0xaaa": [f("1", 100), f("2", 300)],
      "0xbbb": [f("3", 200)],
    });
    expect(rows.map((r) => r.tid)).toEqual(["2", "3", "1"]);
    expect(rows[1].addr).toBe("0xbbb");
  });
  it("respeta el límite", () => {
    const rows = whaleRows({ "0xaaa": Array.from({ length: 30 }, (_, i) => f(String(i), i)) }, 5);
    expect(rows).toHaveLength(5);
  });
  it("vacío sin datos", () => {
    expect(whaleRows({})).toEqual([]);
  });
});

describe("shortAddr", () => {
  it("acorta direcciones largas", () => {
    expect(shortAddr("0xd1d61234567890abcdef1234567890abcdefb01F")).toBe("0xd1d6…b01F");
  });
  it("deja cortas intactas", () => {
    expect(shortAddr("0xabc")).toBe("0xabc");
  });
});
