"use client";
import { useEffect, useState } from "react";
import type { WhaleFill } from "@/lib/types";
import { api } from "@/lib/api";
import { fmtAge } from "@/lib/view";

export function shortAddr(a: string): string {
  return a.length > 10 ? `${a.slice(0, 6)}…${a.slice(-4)}` : a;
}

// Aplana el tape de todas las direcciones, más nuevo primero.
export function whaleRows(data: Record<string, WhaleFill[]>, limit = 12) {
  return Object.entries(data)
    .flatMap(([addr, fills]) => fills.map((f) => ({ ...f, addr })))
    .sort((a, b) => b.ts - a.ts)
    .slice(0, limit);
}

export function WhalePanel() {
  const [data, setData] = useState<Record<string, WhaleFill[]>>({});
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    let alive = true;
    const load = () =>
      api.getWhales().then((r) => { if (alive) setData(r); }).catch(() => {});
    load();
    const t = setInterval(() => { load(); setNow(Math.floor(Date.now() / 1000)); }, 10_000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const rows = whaleRows(data);
  if (rows.length === 0) return null;   // sin direcciones seguidas o sin fills aún

  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>
        SHADOW WHALES · fills en vivo de direcciones seguidas
      </div>
      {rows.map((r) => (
        <div key={`${r.addr}-${r.tid}`}
             style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 11, padding: "3px 0" }}>
          <span className="muted" style={{ flexShrink: 0 }}>{shortAddr(r.addr)}</span>
          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            <b>{r.coin}</b>{" "}
            <span style={{ color: r.side === "B" ? "var(--neon-green)" : "var(--neon-red)" }}>
              {r.side === "B" ? "BUY" : "SELL"}
            </span>{" "}
            {r.sz}@{r.px} <span className="muted">{r.dir}</span>
          </span>
          <span className="muted" style={{ flexShrink: 0 }}>{fmtAge(now - r.ts)}</span>
        </div>
      ))}
    </div>
  );
}
