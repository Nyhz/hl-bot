"use client";
import type { Position, CoinView } from "@/lib/types";
import { slotLayout, slotItems } from "@/lib/view";
import { TradeSlot } from "./TradeSlot";

export function TradeGrid({ positions, coins, watchlistCount }: {
  positions: Position[]; coins: Record<string, CoinView>; watchlistCount: number;
}) {
  const layout = slotLayout(positions.length);
  if (layout === "idle") {
    return (
      <div className="panel trade-grid-idle muted">
        sin posiciones abiertas · vigilando {watchlistCount} {watchlistCount === 1 ? "par" : "pares"}
      </div>
    );
  }
  const items = slotItems(positions, coins);
  return (
    <div className="trade-grid" data-layout={layout}>
      {items.map((it) => <TradeSlot key={it.coin} position={it.position} coinView={it.coinView} />)}
    </div>
  );
}
