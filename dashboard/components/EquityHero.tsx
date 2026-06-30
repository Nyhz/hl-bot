import type { Account } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor } from "@/lib/view";

export function EquityHero({ account }: { account: Account }) {
  const pnl = account.session_pnl;
  const pct = account.equity ? pnl / account.equity : 0;
  return (
    <div className="panel" style={{ padding: 20, display: "flex", justifyContent: "space-between" }}>
      <div>
        <div className="muted" style={{ fontSize: 12 }}>EQUITY</div>
        <div style={{ fontSize: 44, fontWeight: 800 }}>{fmtUsd(account.equity)}</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div className="muted" style={{ fontSize: 12 }}>SESSION P&amp;L</div>
        <div style={{ fontSize: 44, fontWeight: 800, color: pnlColor(pnl) }} className="glow">
          {fmtUsd(pnl)} <span style={{ fontSize: 18 }}>{fmtPct(pct)}</span>
        </div>
      </div>
    </div>
  );
}
