"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import type { Snapshot } from "@/lib/types";
import { fmtAge } from "@/lib/view";
import { SessionControls } from "./SessionControls";

export function HeaderBar({ snapshot, connected, state, onLaunch }: { snapshot: Snapshot | null; connected: boolean; state: string; onLaunch: () => void }) {
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
    <div className="panel header-bar">
      <span className="glow" style={{ color: modeColor, fontWeight: 700 }}>NYHZ // MICRO-DEGEN TERMINAL</span>
      <Link href="/" style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12 }}>LIVE</Link>
      <Link href="/sessions" style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12 }}>HISTORY</Link>
      <Link href="/backtest" style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12 }}>BACKTEST</Link>
      <span className="muted" style={{ fontSize: 12 }}>toy fund · céntimos pa&apos; arriba</span>
      <span className="header-spacer" style={{ color: modeColor, fontWeight: 700 }}>{mode.toUpperCase()}</span>
      <span className={connected ? "live-pulse" : undefined} style={{ color: connected ? "var(--neon-green)" : "var(--neon-red)" }}>{connected ? "● LIVE" : "○ OFFLINE"}</span>
      <span className="muted">session {fmtAge(age)}</span>
      <span className="muted">{(snapshot?.state ?? "—").toUpperCase()}</span>
      <span style={{ marginLeft: 8 }}>
        {state === "idle"
          ? <button onClick={onLaunch}
              style={{ padding: "4px 12px", border: "none", borderRadius: 6, background: "var(--neon-green)",
                color: "#000", fontWeight: 700, cursor: "pointer", fontSize: 12 }}>▶ Launch</button>
          : <SessionControls state={state} />}
      </span>
    </div>
  );
}
