"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { BacktestParams, BacktestResult } from "@/lib/types";
import { BacktestForm } from "@/components/BacktestForm";
import { BacktestResults } from "@/components/BacktestResults";

export default function BacktestPage() {
  const [coins, setCoins] = useState<{ name: string }[]>([]);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [runId, setRunId] = useState(0);
  useEffect(() => { api.getCoins().then(setCoins).catch(() => {}); }, []);
  async function run(p: BacktestParams) {
    setBusy(true); setError(null);
    try { setResult(await api.runBacktest(p)); setRunId((n) => n + 1); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }
  return (
    <main style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minHeight: "100vh" }}>
      <div className="panel" style={{ padding: "10px 16px", display: "flex", gap: 16, alignItems: "center" }}>
        <span className="glow" style={{ color: "var(--neon-green)", fontWeight: 700 }}>NYHZ // BACKTEST</span>
        <Link href="/" style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12 }}>← TRADE</Link>
      </div>
      <div className="terminal-grid">
        <div className="terminal-col"><BacktestForm coins={coins} busy={busy} onRun={run} /></div>
        <div className="terminal-col">
          {error && <div className="panel" style={{ padding: 12, color: "var(--neon-red)" }}>{error}</div>}
          {result ? <BacktestResults key={runId} result={result} /> : <div className="panel muted" style={{ padding: 12 }}>configura y pulsa RUN</div>}
        </div>
      </div>
    </main>
  );
}
