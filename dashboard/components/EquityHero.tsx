"use client";
import type { Account } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor } from "@/lib/view";
import { NumberTicker } from "./NumberTicker";

export function EquityHero({ account }: { account: Account }) {
  const pnl = account.session_pnl;
  const pct = account.equity ? pnl / account.equity : 0;
  return (
    <div className="panel equity-hero" style={{ padding: 20 }}>
      <div style={{ minWidth: 0 }}>
        <div className="muted" style={{ fontSize: 12 }}>EQUITY</div>
        <div style={{ fontSize: 44, fontWeight: 800 }}><NumberTicker value={account.equity} format={(n) => fmtUsd(n)} /></div>
      </div>
      <div className="hero-pnl" style={{ textAlign: "right", minWidth: 0 }}>
        <div className="muted" style={{ fontSize: 12 }}>SESSION P&amp;L</div>
        <div style={{ fontSize: 44, fontWeight: 800, color: pnlColor(pnl) }} className="glow">
          <NumberTicker value={pnl} format={(n) => fmtUsd(n)} /> <span style={{ fontSize: 18 }}>{fmtPct(pct)}</span>
        </div>
      </div>
    </div>
  );
}
