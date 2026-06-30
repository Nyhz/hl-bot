import { describe, it, expect } from "vitest";
import { fmtAge, pnlColor, equitySeries } from "../view";

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
