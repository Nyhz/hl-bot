export function Sparkline({ points, color = "#00ff88", w = 80, h = 24 }: { points: number[]; color?: string; w?: number; h?: number }) {
  if (points.length < 2) return <svg width={w} height={h} />;
  const min = Math.min(...points), max = Math.max(...points), span = max - min || 1;
  const d = points.map((p, i) => {
    const x = (i / (points.length - 1)) * w;
    const y = h - ((p - min) / span) * h;
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return <svg width={w} height={h}><path d={d} fill="none" stroke={color} strokeWidth={1.5} /></svg>;
}
