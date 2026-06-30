"use client";
import { useState } from "react";
import { useLiveSnapshot } from "@/lib/useLiveSnapshot";
import { HeaderBar } from "@/components/HeaderBar";
import { StatTiles } from "@/components/StatTiles";
import { EquityHero } from "@/components/EquityHero";
import { EquityCurve } from "@/components/EquityCurve";
import { OpenPositions } from "@/components/OpenPositions";
import { Watchlist } from "@/components/Watchlist";
import { FocusChart } from "@/components/FocusChart";
import { Tape } from "@/components/Tape";

export default function Home() {
  const { snapshot, connected } = useLiveSnapshot();
  const [focusCoin, setFocusCoin] = useState<string | null>(null);

  // Default focus: first position or first watchlist coin (derived state — no effect needed)
  const displayedCoin = focusCoin ?? snapshot?.positions[0]?.coin ?? snapshot?.watchlist[0] ?? null;

  return (
    <main style={{ padding: 12, display: "flex", flexDirection: "column", gap: 12, minHeight: "100vh" }}>
      <HeaderBar snapshot={snapshot} connected={connected} />
      {snapshot && (
        <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <EquityHero account={snapshot.account} />
            <EquityCurve sessionId={snapshot.session_id} />
            <StatTiles account={snapshot.account} />
            <OpenPositions positions={snapshot.positions} coins={snapshot.coins} onFocus={setFocusCoin} />
            <Tape events={snapshot.tape_recent} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <FocusChart coin={displayedCoin} coinView={displayedCoin ? snapshot.coins[displayedCoin] : undefined} />
            <Watchlist coins={snapshot.coins} positions={snapshot.positions} onFocus={setFocusCoin} />
          </div>
        </div>
      )}
    </main>
  );
}
