/* eslint-disable @typescript-eslint/no-explicit-any */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "../api";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
    ok: true, json: async () => ({ url }),
  })) as any);
  vi.stubEnv("NEXT_PUBLIC_BOT_HTTP", "http://localhost:3300");
});

describe("api", () => {
  it("getCandles builds the right URL", async () => {
    await api.getCandles("ETH");
    expect((fetch as any).mock.calls[0][0]).toBe("http://localhost:3300/candles/ETH?interval=1m");
  });
  it("getSessions passes mode", async () => {
    await api.getSessions("testnet");
    expect((fetch as any).mock.calls[0][0]).toBe("http://localhost:3300/sessions?mode=testnet");
  });
  it("getStatsGlobal", async () => {
    await api.getStatsGlobal();
    expect((fetch as any).mock.calls[0][0]).toBe("http://localhost:3300/stats/global");
  });
});
