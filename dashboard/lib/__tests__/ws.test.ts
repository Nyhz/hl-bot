import { describe, it, expect } from "vitest";
import { controlAllowed } from "../ws";

describe("controlAllowed", () => {
  it("permite acciones válidas", () => {
    for (const a of ["launch", "close", "kill", "limits"]) expect(controlAllowed(a)).toBe(true);
  });
  it("rechaza lo demás", () => {
    expect(controlAllowed("../secrets")).toBe(false);
    expect(controlAllowed("drop")).toBe(false);
  });
});
