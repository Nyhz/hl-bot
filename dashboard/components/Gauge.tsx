export function Gauge({ pct, label, met }: { pct: number; label: string; met: boolean }) {
  const color = met ? "var(--neon-green)" : "var(--neon-amber)";
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
        <span className="muted">{label}</span>
        <span style={{ color }}>{met ? "✓" : `${Math.round(pct * 100)}%`}</span>
      </div>
      <div style={{ height: 4, background: "#1c1f26", borderRadius: 2 }}>
        <div style={{ width: `${pct * 100}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
    </div>
  );
}
