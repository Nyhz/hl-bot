"use client";
import { useEffect, useState } from "react";
import type { Snapshot } from "@/lib/types";
import { fmtAge } from "@/lib/view";

export function HeaderBar({ snapshot, connected }: { snapshot: Snapshot | null; connected: boolean }) {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000));
  useEffect(() => {
    const t = setInterval(() => setNow(Math.floor(Date.now() / 1000)), 1000);
    return () => clearInterval(t);
  }, []);
  const mode = snapshot?.mode ?? "testnet";
  const modeColor = mode === "mainnet" ? "var(--neon-green)" : "var(--neon-amber)";
  const started = snapshot?.session_started_at ?? null;
  const age = started ? now - started : null;
  return (
    <div className="panel" style={{ display: "flex", alignItems: "center", gap: 16, padding: "10px 16px" }}>
      <span className="glow" style={{ color: modeColor, fontWeight: 700 }}>NYHZ // MICRO-DEGEN TERMINAL</span>
      <span className="muted" style={{ fontSize: 12 }}>toy fund · céntimos pa&apos; arriba</span>
      <span style={{ marginLeft: "auto", color: modeColor, fontWeight: 700 }}>{mode.toUpperCase()}</span>
      <span style={{ color: connected ? "var(--neon-green)" : "var(--neon-red)" }}>{connected ? "● LIVE" : "○ OFFLINE"}</span>
      <span className="muted">session {fmtAge(age)}</span>
      <span className="muted">{(snapshot?.state ?? "—").toUpperCase()}</span>
    </div>
  );
}
