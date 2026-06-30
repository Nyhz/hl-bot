"use client";
import type { Position, CoinView } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { positionView, conditionPct } from "@/lib/view";
import { FocusChart } from "./FocusChart";
import { Gauge } from "./Gauge";

export function TradeSlot({ position, coinView }: { position: Position; coinView: CoinView | undefined }) {
  const mid = coinView?.mid ?? null;
  const v = positionView(position, mid);
  const pnlPct = position.notional ? position.unrealized_pnl / position.notional : 0;
  return (
    <div className="panel trade-slot">
      <div className="trade-slot-head">
        <span style={{ fontWeight: 700 }}>{position.coin}</span>
        <span style={{ color: v.sideColor }}>{v.sideLabel}</span>
        <span className="muted">{position.leverage ?? "-"}x</span>
        <span className="muted">{position.entry_px} → <b style={{ color: "var(--text)" }}>{v.markPx}</b></span>
        <span style={{ color: v.pnlColor, marginLeft: "auto", fontWeight: 700 }}>
          {fmtUsd(position.unrealized_pnl)} <span style={{ fontSize: 11 }}>{fmtPct(pnlPct)}</span>
        </span>
        <span className="muted" style={{ fontSize: 11 }}>liq {position.liq_px ?? "—"}</span>
      </div>
      <div className="trade-slot-chart">
        <FocusChart coin={position.coin} coinView={coinView} mid={mid} fill />
      </div>
      {coinView && coinView.conditions.length > 0 && (
        <div className="trade-slot-conds">
          {coinView.conditions.map((c) => <Gauge key={c.name} label={c.name} pct={conditionPct(c)} met={c.met} />)}
        </div>
      )}
    </div>
  );
}
