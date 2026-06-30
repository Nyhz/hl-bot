import type { CoinView, Position } from "@/lib/types";
import { conditionPct, fmtFunding, fundingColor } from "@/lib/view";
import { Gauge } from "./Gauge";

export function Watchlist({ coins, positions, onFocus }: {
  coins: Record<string, CoinView>; positions: Position[]; onFocus?: (coin: string) => void;
}) {
  const open = new Set(positions.map((p) => p.coin));
  const candidates = Object.entries(coins).filter(([c]) => !open.has(c));
  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>WATCHLIST · condiciones para abrir</div>
      {candidates.length === 0 && <div className="muted" style={{ fontSize: 12 }}>todos los pares con posición</div>}
      {candidates.map(([coin, cv]) => (
        <div key={coin} onClick={() => onFocus?.(coin)} style={{ padding: "8px 4px", borderBottom: "1px solid #1c1f26", cursor: "pointer" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
            <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              <b>{coin}</b> <span className="muted">{cv.mode}</span> <span className="muted">{cv.mid}</span>
            </span>
            <span style={{ display: "flex", gap: 8, alignItems: "baseline", flexShrink: 0 }}>
              <span title="funding horario (largo paga si +)" style={{ fontSize: 11, color: fundingColor(cv.funding) }}>
                fund {fmtFunding(cv.funding)}
              </span>
              {cv.armed && <span className="armed-glow" style={{ color: "var(--neon-green)", fontWeight: 700 }}>ARMED</span>}
            </span>
          </div>
          <div style={{ marginTop: 6 }}>
            {cv.conditions.map((c) => <Gauge key={c.name} label={c.name} pct={conditionPct(c)} met={c.met} />)}
          </div>
        </div>
      ))}
    </div>
  );
}
