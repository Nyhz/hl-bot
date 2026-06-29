"use client";
import { useLiveSnapshot } from "@/lib/useLiveSnapshot";
import { fmtUsd } from "@/lib/format";

export default function Home() {
  const { snapshot, connected } = useLiveSnapshot();
  const mode = snapshot?.mode ?? "testnet";
  const modeColor = mode === "mainnet" ? "var(--neon-green)" : "var(--neon-amber)";
  const equity = snapshot?.account?.equity ?? 0;

  return (
    <main style={{ padding: 24, minHeight: "100vh" }}>
      <header style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <span className="glow" style={{ color: modeColor, fontWeight: 700 }}>
          NYHZ // MICRO-DEGEN TERMINAL
        </span>
        <span className="muted">{snapshot?.state ?? "—"}</span>
        <span style={{ color: modeColor }}>{mode.toUpperCase()}</span>
        <span style={{ color: connected ? "var(--neon-green)" : "var(--neon-red)" }}>
          {connected ? "● LIVE" : "○ OFFLINE"}
        </span>
      </header>
      <section style={{ marginTop: 32 }}>
        <div className="muted" style={{ fontSize: 12 }}>EQUITY</div>
        <div style={{ fontSize: 48, fontWeight: 700 }}>{fmtUsd(equity)}</div>
      </section>
    </main>
  );
}
