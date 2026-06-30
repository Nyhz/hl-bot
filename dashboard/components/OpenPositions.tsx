import type { Position, CoinView } from "@/lib/types";
import { fmtUsd } from "@/lib/format";
import { positionView } from "@/lib/view";
import { Sparkline } from "./Sparkline";

export function OpenPositions({ positions, coins, onFocus }: {
  positions: Position[]; coins: Record<string, CoinView>; onFocus?: (coin: string) => void;
}) {
  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>OPEN POSITIONS</div>
      {positions.length === 0 && <div className="muted" style={{ fontSize: 12 }}>sin posiciones abiertas</div>}
      {positions.map((p) => {
        const mid = coins[p.coin]?.mid ?? null;
        const v = positionView(p, mid);
        return (
          <div key={p.coin} onClick={() => onFocus?.(p.coin)}
            style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 80px 1.2fr 1fr 1fr", alignItems: "center", gap: 8, padding: "10px 4px", borderBottom: "1px solid #1c1f26", cursor: "pointer" }}>
            <span><b>{p.coin}</b> <span style={{ color: v.sideColor }}>{v.sideLabel}</span> <span className="muted">{p.leverage ?? "-"}x</span></span>
            <span>{fmtUsd(p.notional)}</span>
            <Sparkline points={[p.entry_px, v.markPx]} color={v.pnlColor} />
            <span className="muted">{p.entry_px} → <b style={{ color: "var(--text)" }}>{v.markPx}</b></span>
            <span style={{ color: v.pnlColor }}>{fmtUsd(p.unrealized_pnl)}</span>
            <span className="muted" style={{ fontSize: 12 }}>liq {p.liq_px ?? "—"}</span>
          </div>
        );
      })}
    </div>
  );
}
