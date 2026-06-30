"use client";
import { useLiveSnapshot } from "@/lib/useLiveSnapshot";
import { HeaderBar } from "@/components/HeaderBar";
import { StatTiles } from "@/components/StatTiles";
import { EquityHero } from "@/components/EquityHero";
import { EquityCurve } from "@/components/EquityCurve";

export default function Home() {
  const { snapshot, connected } = useLiveSnapshot();
  return (
    <main style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minHeight: "100vh" }}>
      <HeaderBar snapshot={snapshot} connected={connected} />
      {snapshot && <EquityHero account={snapshot.account} />}
      <EquityCurve sessionId={snapshot?.session_id ?? null} />
      {snapshot && <StatTiles account={snapshot.account} />}
    </main>
  );
}
