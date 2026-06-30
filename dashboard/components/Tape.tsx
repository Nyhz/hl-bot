import type { TapeEvent } from "@/lib/types";
import { fmtUsd } from "@/lib/format";

function kindColor(k: string) {
  return k === "close" ? "var(--neon-amber)" : k === "open" ? "var(--neon-green)" : "var(--muted)";
}
export function Tape({ events }: { events: TapeEvent[] }) {
  return (
    <div className="panel" style={{ padding: 12, maxHeight: 240, overflowY: "auto" }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>TAPE</div>
      {events.length === 0 && <div className="muted" style={{ fontSize: 12 }}>sin actividad</div>}
      {events.map((e, i) => (
        <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, padding: "3px 0", fontFamily: "Menlo, monospace" }}>
          <span className="muted">{new Date(e.ts * 1000).toLocaleTimeString()}</span>
          <span style={{ color: kindColor(e.kind), textTransform: "uppercase", width: 64 }}>{e.kind}</span>
          <span>{e.coin ?? ""}</span>
          {e.pnl !== null && <span style={{ color: e.pnl < 0 ? "var(--neon-red)" : "var(--neon-green)" }}>{fmtUsd(e.pnl)}</span>}
          <span className="muted" style={{ marginLeft: "auto", fontStyle: "italic" }}>{(e.reason || "").slice(0, 40)}</span>
        </div>
      ))}
    </div>
  );
}
