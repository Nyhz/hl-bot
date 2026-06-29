import { describe, it, expect } from "vitest";
import { fmtUsd, fmtPct } from "../format";

describe("format", () => {
  it("fmtUsd", () => {
    expect(fmtUsd(49.16)).toBe("$49.16");
    expect(fmtUsd(-0.84)).toBe("-$0.84");
    expect(fmtUsd(0.049, 3)).toBe("$0.049");
  });
  it("fmtPct", () => {
    expect(fmtPct(-0.0169)).toBe("-1.69%");
    expect(fmtPct(0.67)).toBe("+67.00%");
  });
});
