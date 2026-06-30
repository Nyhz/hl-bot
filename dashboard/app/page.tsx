"use client";
import { useState, useEffect } from "react";
import { useLiveSnapshot } from "@/lib/useLiveSnapshot";
import { api } from "@/lib/api";
import { HeaderBar } from "@/components/HeaderBar";
import { StatTiles } from "@/components/StatTiles";
import { AttributionPanel } from "@/components/AttributionPanel";
import { EquityHero } from "@/components/EquityHero";
import { EquityCurve } from "@/components/EquityCurve";
import { OpenPositions } from "@/components/OpenPositions";
import { Watchlist } from "@/components/Watchlist";
import { FocusChart } from "@/components/FocusChart";
import { Tape } from "@/components/Tape";
import { LaunchPanel } from "@/components/LaunchPanel";
import { SessionControls } from "@/components/SessionControls";
import { useEventFeedback } from "@/hooks/useEventFeedback";

export default function Home() {
  const { snapshot, connected } = useLiveSnapshot();
  useEventFeedback(snapshot);
  const [focusCoin, setFocusCoin] = useState<string | null>(null);
  const [coinsList, setCoinsList] = useState<{ name: string }[]>([]);

  useEffect(() => {
    api.getCoins().then((coins) => setCoinsList(coins)).catch(() => {});
  }, []);

  // Default focus: first position or first watchlist coin (derived state — no effect needed)
  const displayedCoin = focusCoin ?? snapshot?.positions[0]?.coin ?? snapshot?.watchlist[0] ?? null;
  const sessionState = snapshot?.state ?? "idle";

  return (
    <main style={{ padding: 12, display: "flex", flexDirection: "column", gap: 12, minHeight: "100vh" }}>
      <HeaderBar snapshot={snapshot} connected={connected} />
      <div style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "flex-end" }}>
        <SessionControls state={sessionState} />
      </div>
      {snapshot && (
        <div className="terminal-grid">
          <div className="terminal-col">
            <EquityHero account={snapshot.account} />
            <EquityCurve sessionId={snapshot.session_id} equity={snapshot.account.equity} />
            <StatTiles account={snapshot.account} />
            <AttributionPanel account={snapshot.account} />
            <OpenPositions positions={snapshot.positions} coins={snapshot.coins} onFocus={setFocusCoin} />
            <Tape events={snapshot.tape_recent} />
          </div>
          <div className="terminal-col">
            <LaunchPanel coins={coinsList} state={sessionState} />
            <FocusChart coin={displayedCoin} coinView={displayedCoin ? snapshot.coins[displayedCoin] : undefined} mid={displayedCoin ? snapshot.coins[displayedCoin]?.mid ?? null : null} />
            <Watchlist coins={snapshot.coins} positions={snapshot.positions} onFocus={setFocusCoin} />
          </div>
        </div>
      )}
      {!snapshot && (
        <LaunchPanel coins={coinsList} state={sessionState} />
      )}
    </main>
  );
}
