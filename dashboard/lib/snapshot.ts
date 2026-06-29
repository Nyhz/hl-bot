import type { Snapshot, Account } from "./types";

export const ZERO_ACCOUNT: Account = {
  equity: 0, session_pnl: 0, realized_pnl: 0, unrealized_pnl: 0,
  win_rate: 0, fees_paid: 0, funding: 0, open_count: 0, max_open: 0,
};

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function normalizeSnapshot(raw: any): Snapshot {
  return {
    state: raw?.state ?? "idle",
    paused: raw?.paused ?? false,
    mode: raw?.mode ?? "testnet",
    session_id: raw?.session_id ?? null,
    session_started_at: raw?.session_started_at ?? null,
    watchlist: raw?.watchlist ?? [],
    coins: raw?.coins ?? {},
    account: { ...ZERO_ACCOUNT, ...(raw?.account ?? {}) },
    positions: raw?.positions ?? [],
    tape_recent: raw?.tape_recent ?? [],
  };
}
