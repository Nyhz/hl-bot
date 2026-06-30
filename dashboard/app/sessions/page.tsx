"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { GlobalStats as GS, SessionSummary } from "@/lib/types";
import { GlobalStats } from "@/components/GlobalStats";
import { SessionsList } from "@/components/SessionsList";
import { SessionDetail } from "@/components/SessionDetail";

export default function SessionsPage() {
  const [stats, setStats] = useState<GS | null>(null);
  const [mode, setMode] = useState<"all" | "testnet" | "mainnet">("all");
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  useEffect(() => { api.getStatsGlobal().then(setStats).catch(() => {}); }, []);
  useEffect(() => {
    let cancelled = false;
    api.getSessions(mode === "all" ? undefined : mode).then((r) => { if (!cancelled) setSessions(r); }).catch(() => {});
    return () => { cancelled = true; };
  }, [mode]);
  return (
    <main style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minHeight: "100vh" }}>
      <div className="panel" style={{ padding: "10px 16px", display: "flex", gap: 16, alignItems: "center" }}>
        <span className="glow" style={{ color: "var(--neon-green)", fontWeight: 700 }}>NYHZ // TRACK RECORD</span>
        <Link href="/" style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12 }}>← LIVE</Link>
      </div>
      <div className="muted" style={{ fontSize: 11 }}>TRACK RECORD GLOBAL (testnet y mainnet separados)</div>
      {stats && <GlobalStats stats={stats} />}
      <div style={{ display: "flex", gap: 6 }}>
        {(["all","testnet","mainnet"] as const).map((m) => (
          <button key={m} onClick={() => { setMode(m); setSelectedId(null); }}
            style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid #1c1f26", cursor: "pointer", fontSize: 12,
              background: mode === m ? "var(--neon-green)" : "transparent", color: mode === m ? "#000" : "var(--text)" }}>{m}</button>
        ))}
      </div>
      <SessionsList sessions={sessions} onSelect={setSelectedId} selectedId={selectedId} />
      {selectedId !== null && <SessionDetail key={selectedId} sessionId={selectedId} />}
    </main>
  );
}
