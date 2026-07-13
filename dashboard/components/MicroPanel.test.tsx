import { describe, it, expect } from "vitest";
import { spreadBps, flowView, fmtBps, bpsColor } from "./MicroPanel";
import type { CoinView } from "@/lib/types";

const cv = (over: Partial<CoinView> = {}): CoinView => ({
  mid: 3000, mode: "grid", funding: null, triggers: [], conditions: [], armed: false,
  ...over,
});

describe("spreadBps", () => {
  it("calcula bps del BBO sobre el mid", () => {
    const s = spreadBps(cv({ bbo: [2999.4, 3000.6] }));
    expect(s).toBeCloseTo(4.0, 5);           // 1.2 / 3000 * 1e4
  });
  it("null sin bbo fresco (WS caído o backtest)", () => {
    expect(spreadBps(cv())).toBeNull();
    expect(spreadBps(cv({ bbo: [null, 3000.6] }))).toBeNull();
  });
});

describe("flowView", () => {
  it("flujo comprador: barra a la derecha, verde", () => {
    const v = flowView(0.5);
    expect(v.buyPct).toBe(50);
    expect(v.sellPct).toBe(0);
    expect(v.color).toBe("var(--neon-green)");
    expect(v.label).toBe("+50%");
  });
  it("flujo vendedor: barra a la izquierda, rojo", () => {
    const v = flowView(-0.8);
    expect(v.sellPct).toBe(80);
    expect(v.buyPct).toBe(0);
    expect(v.color).toBe("var(--neon-red)");
  });
  it("sin tape: guion y sin barras", () => {
    const v = flowView(null);
    expect(v.label).toBe("—");
    expect(v.buyPct + v.sellPct).toBe(0);
  });
  it("satura en ±100%", () => {
    expect(flowView(1.7).buyPct).toBe(100);
  });
});

describe("markout formatting", () => {
  it("fmtBps firma y redondea", () => {
    expect(fmtBps(1.234)).toBe("+1.2");
    expect(fmtBps(-0.55)).toBe("-0.6");
    expect(fmtBps(null)).toBe("—");
  });
  it("bpsColor: negativo = selección adversa = rojo", () => {
    expect(bpsColor(-1)).toBe("var(--neon-red)");
    expect(bpsColor(2)).toBe("var(--neon-green)");
    expect(bpsColor(null)).toBe("var(--muted)");
  });
});
