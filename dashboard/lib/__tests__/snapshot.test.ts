import { describe, it, expect } from "vitest";
import { normalizeSnapshot, ZERO_ACCOUNT } from "../snapshot";

describe("normalizeSnapshot", () => {
  it("fills defaults when account/arrays missing (idle backend)", () => {
    const s = normalizeSnapshot({ state: "idle", mode: "testnet" });
    expect(s.account).toEqual(ZERO_ACCOUNT);
    expect(s.positions).toEqual([]);
    expect(s.coins).toEqual({});
    expect(s.tape_recent).toEqual([]);
  });
  it("merges provided account fields over zeros", () => {
    const s = normalizeSnapshot({ account: { equity: 49.16, realized_pnl: -0.12 } });
    expect(s.account.equity).toBe(49.16);
    expect(s.account.realized_pnl).toBe(-0.12);
    expect(s.account.fees_paid).toBe(0);
  });
});
