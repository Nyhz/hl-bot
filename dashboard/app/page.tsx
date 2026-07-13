"use client";
import { useState, useEffect } from "react";
import { useLiveSnapshot } from "@/lib/useLiveSnapshot";
import { api } from "@/lib/api";
import { HeaderBar } from "@/components/HeaderBar";
import { EquityHero } from "@/components/EquityHero";
import { EquityCurve } from "@/components/EquityCurve";
import { StatTiles } from "@/components/StatTiles";
import { AttributionPanel } from "@/components/AttributionPanel";
import { TradeGrid } from "@/components/TradeGrid";
import { Watchlist } from "@/components/Watchlist";
import { MicroPanel } from "@/components/MicroPanel";
import { WhalePanel } from "@/components/WhalePanel";
import { Tape } from "@/components/Tape";
import { LaunchModal } from "@/components/LaunchModal";
import { useEventFeedback } from "@/hooks/useEventFeedback";

export default function Home() {
  const { snapshot, connected } = useLiveSnapshot();
  useEventFeedback(snapshot);
  const [coinsList, setCoinsList] = useState<{ name: string }[]>([]);
  const [launchOpen, setLaunchOpen] = useState(false);
  useEffect(() => { api.getCoins().then(setCoinsList).catch(() => {}); }, []);
  const sessionState = snapshot?.state ?? "idle";

  return (
    <main className="app-100vh">
      <HeaderBar snapshot={snapshot} connected={connected} state={sessionState} onLaunch={() => setLaunchOpen(true)} />
      {snapshot ? (
        <div className="trade-shell">
          <div className="left-col">
            <div className="top-band">
              <EquityHero account={snapshot.account} />
              <EquityCurve sessionId={snapshot.session_id} equity={snapshot.account.equity} />
              <StatTiles account={snapshot.account} />
            </div>
            <div className="center-stage">
              <TradeGrid positions={snapshot.positions} coins={snapshot.coins} watchlistCount={snapshot.watchlist.length} />
            </div>
          </div>
          <div className="right-rail">
            <AttributionPanel account={snapshot.account} />
            <MicroPanel key={snapshot.session_id ?? "idle"} snapshot={snapshot} />
            <Watchlist coins={snapshot.coins} positions={snapshot.positions} />
            <WhalePanel />
            <Tape events={snapshot.tape_recent} />
          </div>
        </div>
      ) : (
        <div className="panel muted" style={{ padding: 16 }}>conectando…</div>
      )}
      <LaunchModal coins={coinsList} state={sessionState} open={launchOpen} onClose={() => setLaunchOpen(false)} />
    </main>
  );
}
