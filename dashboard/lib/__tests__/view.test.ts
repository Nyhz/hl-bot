import { describe, it, expect } from "vitest";
import { fmtAge, pnlColor } from "../view";

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
