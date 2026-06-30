"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { GlobalStats as GS } from "@/lib/types";
import { GlobalStats } from "@/components/GlobalStats";

export default function SessionsPage() {
  const [stats, setStats] = useState<GS | null>(null);
  useEffect(() => { api.getStatsGlobal().then(setStats).catch(() => {}); }, []);
  return (
    <main style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minHeight: "100vh" }}>
      <div className="panel" style={{ padding: "10px 16px", display: "flex", gap: 16, alignItems: "center" }}>
        <span className="glow" style={{ color: "var(--neon-green)", fontWeight: 700 }}>NYHZ // TRACK RECORD</span>
        <Link href="/" style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12 }}>← LIVE</Link>
      </div>
      <div className="muted" style={{ fontSize: 11 }}>TRACK RECORD GLOBAL (testnet y mainnet separados)</div>
      {stats && <GlobalStats stats={stats} />}
    </main>
  );
}
