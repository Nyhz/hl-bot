import { describe, it, expect } from "vitest";
import { fmtAge, fmtDuration, pnlColor, equitySeries, positionView, conditionPct, candleSeries } from "../view";
import type { Position } from "../types";

describe("fmtDuration", () => {
  it("formats", () => {
    expect(fmtDuration(null)).toBe("—");
    expect(fmtDuration(300)).toBe("5m");
    expect(fmtDuration(3725)).toBe("1h 02m");
  });
});

describe("view helpers", () => {
  it("fmtAge", () => {
    expect(fmtAge(65)).toBe("1m 05s");
    expect(fmtAge(0)).toBe("0m 00s");
    expect(fmtAge(null as unknown as number)).toBe("—");
  });
  it("pnlColor", () => {
    expect(pnlColor(1)).toBe("var(--neon-green)");
    expect(pnlColor(-1)).toBe("var(--neon-red)");
    expect(pnlColor(0)).toBe("var(--neon-green)");
  });
});

describe("equitySeries", () => {
  it("maps ts/total_pnl to time/value ascending", () => {
    const out = equitySeries([{ ts: 200, total_pnl: 50.4 }, { ts: 100, total_pnl: 50.0 }]);
    expect(out).toEqual([{ time: 100, value: 50.0 }, { time: 200, value: 50.4 }]);
  });
});

describe("conditionPct", () => {
  it("ratio value/threshold clamped 0..1", () => {
    expect(conditionPct({ name: "adx", value: 12.5, threshold: 25, met: false })).toBeCloseTo(0.5);
    expect(conditionPct({ name: "adx", value: 30, threshold: 25, met: true })).toBe(1);
    expect(conditionPct({ name: "x", value: 5, threshold: 0, met: true })).toBe(1);
  });
});

describe("candleSeries", () => {
  it("passes through sorted by time", () => {
    const out = candleSeries([{ time: 2, open: 1, high: 2, low: 1, close: 1.5 }, { time: 1, open: 1, high: 1, low: 1, close: 1 }] as never);
    expect(out.map((c) => c.time)).toEqual([1, 2]);
  });
});

describe("positionView", () => {
  const base: Position = { coin: "ETH", side: "long", leverage: 3, notional: 12, size: 0.004,
    entry_px: 3000, mark_px: null, unrealized_pnl: 0.07, liq_px: 2000 };
  it("uses live mid when mark_px null and colors by pnl", () => {
    const v = positionView(base, 3050);
    expect(v.markPx).toBe(3050);
    expect(v.pnlColor).toBe("var(--neon-green)");
    expect(v.sideLabel).toBe("LONG");
  });
  it("falls back to entry when no mid", () => {
    expect(positionView(base, null).markPx).toBe(3000);
  });
});
