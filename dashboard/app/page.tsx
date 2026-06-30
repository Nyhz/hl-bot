"use client";
import { useState } from "react";
import { useLiveSnapshot } from "@/lib/useLiveSnapshot";
import { HeaderBar } from "@/components/HeaderBar";
import { StatTiles } from "@/components/StatTiles";
import { EquityHero } from "@/components/EquityHero";
import { EquityCurve } from "@/components/EquityCurve";
import { OpenPositions } from "@/components/OpenPositions";

export default function Home() {
  const { snapshot, connected } = useLiveSnapshot();
  const [focusCoin, setFocusCoin] = useState<string | null>(null);
  return (
    <main style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minHeight: "100vh" }}>
      <HeaderBar snapshot={snapshot} connected={connected} />
      {snapshot && <EquityHero account={snapshot.account} />}
      <EquityCurve sessionId={snapshot?.session_id ?? null} />
      {snapshot && <StatTiles account={snapshot.account} />}
      {snapshot && (
        <OpenPositions
          positions={snapshot.positions}
          coins={snapshot.coins}
          onFocus={setFocusCoin}
        />
      )}
    </main>
  );
}
