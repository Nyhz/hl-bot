# Dashboard 2b.2 — Terminal en vivo: Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Construir el terminal en vivo del MICRO-DEGEN TERMINAL: HeaderBar, EquityHero + curva de equity, StatTiles, OpenPositions (con sparkline), Watchlist (gauges de condiciones / ARMED), FocusChart (candles + triggers/EMAs) y Tape, ensamblados en un layout grid tiled, consumiendo el snapshot en vivo y la API REST.

**Architecture:** Componentes presentacionales en `dashboard/components/`, cada uno consume datos ya tipados (snapshot del hook `useLiveSnapshot` o fetch REST). La lógica de transformación (series de chart, vista de posición, % de condición, edad de sesión) vive en helpers PUROS en `dashboard/lib/` testeados con Vitest. Lightweight-Charts para curva de equity y candlestick. Página `app/page.tsx` ensambla el grid.

**Tech Stack:** Next.js + TS + Tailwind v4, lightweight-charts, Vitest. Backend `:3300` ya provee datos.

## Global Constraints

- Estética neón ya definida (`globals.css`): verde `#00ff88` (pos), rojo `#ff4466` (neg), ámbar `#ffaa00`, muted `#8a8f98`. Monoespaciado. Usa las CSS vars / clases existentes.
- Datos: `useLiveSnapshot()` da el snapshot normalizado (account SIEMPRE completo, positions/coins/tape_recent por defecto vacíos). REST vía `lib/api.ts`.
- **Gotchas del contrato:** `account.equity` y `/equity_curve.total_pnl` son EQUITY (graficar como curva de equity, no PnL). Posiciones traen `mark_px=null` → usar el `mid` vivo de `snapshot.coins[coin]?.mid` para entry→mark/PnL visual. PnL de posición = `unrealized_pnl` (del backend).
- Cada tarea: `npm run build` (typecheck) + `npm run lint` limpios + Vitest verde donde haya helper.
- Lightweight-Charts: usa la API de la versión instalada (v5: `chart.addSeries(AreaSeries, ...)`; v4: `chart.addAreaSeries(...)`). Confirma con la versión instalada y adapta; encapsula en el componente.
- Trabajar en `dashboard/`.

**Estructura (2b.2):**
```
dashboard/components/HeaderBar.tsx, StatTiles.tsx, EquityHero.tsx, EquityCurve.tsx,
  OpenPositions.tsx, Watchlist.tsx, FocusChart.tsx, Tape.tsx
dashboard/lib/view.ts        # helpers puros (fmtAge, positionView, conditionPct, equitySeries, candleSeries)
dashboard/lib/__tests__/view.test.ts
dashboard/app/page.tsx       # ensamblado grid tiled + estado de par enfocado
```

---

### Task 1: Helpers de vista + HeaderBar + StatTiles + layout shell

**Files:** Create: `dashboard/lib/view.ts`, `dashboard/lib/__tests__/view.test.ts`, `dashboard/components/HeaderBar.tsx`, `dashboard/components/StatTiles.tsx`. Modify: `dashboard/app/page.tsx` (shell grid temporal).

**Interfaces:**
- Produces: `fmtAge(sec: number): string` ("1m 05s" / "—" si null); `pnlColor(n: number): string` (var neón verde/rojo); `<HeaderBar snapshot/>`, `<StatTiles account/>`.

- [ ] **Step 1: Test que falla** `dashboard/lib/__tests__/view.test.ts`
```ts
import { describe, it, expect } from "vitest";
import { fmtAge, pnlColor } from "../view";

describe("view helpers", () => {
  it("fmtAge", () => {
    expect(fmtAge(65)).toBe("1m 05s");
    expect(fmtAge(0)).toBe("0m 00s");
    expect(fmtAge(null as unknown as number)).toBe("—");
  });
  it("pnlColor", () => {
    expect(pnlColor(1)).toBe("var(--neon-green)");
    expect(pnlColor(-1)).toBe("var(--neon-red)");
    expect(pnlColor(0)).toBe("var(--neon-green)");
  });
});
```

- [ ] **Step 2: Verificar fallo** — `cd dashboard && npm test -- view` → FAIL (no module).

- [ ] **Step 3: Implementar `dashboard/lib/view.ts`** (irá creciendo en tareas siguientes; empieza con):
```ts
export function fmtAge(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || Number.isNaN(sec)) return "—";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}m ${String(s).padStart(2, "0")}s`;
}

export function pnlColor(n: number): string {
  return n < 0 ? "var(--neon-red)" : "var(--neon-green)";
}
```

- [ ] **Step 4: Verificar PASS** — `cd dashboard && npm test -- view` → PASS.

- [ ] **Step 5: `dashboard/components/HeaderBar.tsx`**
```tsx
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
```

- [ ] **Step 6: `dashboard/components/StatTiles.tsx`**
```tsx
import type { Account } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor } from "@/lib/view";

export function StatTiles({ account }: { account: Account }) {
  const tiles: { label: string; value: string; color?: string }[] = [
    { label: "OPEN", value: `${account.open_count} / ${account.max_open}` },
    { label: "WIN RATE", value: fmtPct(account.win_rate), color: "var(--neon-green)" },
    { label: "REALIZED", value: fmtUsd(account.realized_pnl), color: pnlColor(account.realized_pnl) },
    { label: "FEES PAID", value: fmtUsd(account.fees_paid, 3), color: "var(--neon-red)" },
    { label: "FUNDING", value: fmtUsd(account.funding, 3), color: pnlColor(account.funding) },
  ];
  return (
    <div style={{ display: "grid", gridTemplateColumns: `repeat(${tiles.length}, 1fr)`, gap: 1 }}>
      {tiles.map((t) => (
        <div key={t.label} className="panel" style={{ padding: 12 }}>
          <div className="muted" style={{ fontSize: 11 }}>{t.label}</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: t.color ?? "var(--text)" }}>{t.value}</div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 7: Shell temporal en `app/page.tsx`** — renderiza HeaderBar + StatTiles bajo el hook (mantén EQUITY mínimo si quieres). Mínimo:
```tsx
"use client";
import { useLiveSnapshot } from "@/lib/useLiveSnapshot";
import { HeaderBar } from "@/components/HeaderBar";
import { StatTiles } from "@/components/StatTiles";

export default function Home() {
  const { snapshot, connected } = useLiveSnapshot();
  return (
    <main style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12, minHeight: "100vh" }}>
      <HeaderBar snapshot={snapshot} connected={connected} />
      {snapshot && <StatTiles account={snapshot.account} />}
    </main>
  );
}
```

- [ ] **Step 8: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard/lib dashboard/components dashboard/app/page.tsx
git commit -m "feat(web): helpers de vista + HeaderBar + StatTiles + shell"
```

---

### Task 2: EquityHero + EquityCurve (lightweight-charts)

**Files:** Create: `dashboard/components/EquityHero.tsx`, `dashboard/components/EquityCurve.tsx`. Modify: `dashboard/lib/view.ts` (+ `equitySeries`), `dashboard/lib/__tests__/view.test.ts`. Install lightweight-charts.

**Interfaces:**
- Produces: `equitySeries(rows: {ts:number; total_pnl:number}[]): {time:number; value:number}[]` (puro, ascendente por time); `<EquityHero account/>`, `<EquityCurve sessionId/>`.

- [ ] **Step 1: Instalar lightweight-charts** — `cd dashboard && npm install lightweight-charts`.

- [ ] **Step 2: Test que falla** (añadir a `view.test.ts`)
```ts
import { equitySeries } from "../view";
describe("equitySeries", () => {
  it("maps ts/total_pnl to time/value ascending", () => {
    const out = equitySeries([{ ts: 200, total_pnl: 50.4 }, { ts: 100, total_pnl: 50.0 }]);
    expect(out).toEqual([{ time: 100, value: 50.0 }, { time: 200, value: 50.4 }]);
  });
});
```

- [ ] **Step 3: Verificar fallo** — `npm test -- view` → FAIL.

- [ ] **Step 4: Implementar `equitySeries` en `view.ts`**
```ts
export function equitySeries(rows: { ts: number; total_pnl: number }[]): { time: number; value: number }[] {
  return rows
    .map((r) => ({ time: r.ts, value: r.total_pnl }))
    .sort((a, b) => a.time - b.time);
}
```

- [ ] **Step 5: Verificar PASS** — `npm test -- view` → PASS.

- [ ] **Step 6: `dashboard/components/EquityHero.tsx`**
```tsx
import type { Account } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor } from "@/lib/view";

export function EquityHero({ account }: { account: Account }) {
  const pnl = account.session_pnl;
  const pct = account.equity ? pnl / account.equity : 0;
  return (
    <div className="panel" style={{ padding: 20, display: "flex", justifyContent: "space-between" }}>
      <div>
        <div className="muted" style={{ fontSize: 12 }}>EQUITY</div>
        <div style={{ fontSize: 44, fontWeight: 800 }}>{fmtUsd(account.equity)}</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div className="muted" style={{ fontSize: 12 }}>SESSION P&amp;L</div>
        <div style={{ fontSize: 44, fontWeight: 800, color: pnlColor(pnl) }} className="glow">
          {fmtUsd(pnl)} <span style={{ fontSize: 18 }}>{fmtPct(pct)}</span>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 7: `dashboard/components/EquityCurve.tsx`** (chart de área; adapta la API a la versión de lightweight-charts instalada)
```tsx
"use client";
import { useEffect, useRef } from "react";
import { createChart, AreaSeries, type IChartApi } from "lightweight-charts";
import { api } from "@/lib/api";
import { equitySeries } from "@/lib/view";

export function EquityCurve({ sessionId }: { sessionId: number | null }) {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    const chart: IChartApi = createChart(ref.current, {
      height: 160, layout: { background: { color: "transparent" }, textColor: "#8a8f98" },
      grid: { vertLines: { visible: false }, horzLines: { color: "#1c1f26" } },
      timeScale: { visible: false }, rightPriceScale: { borderVisible: false },
    });
    // v5: addSeries(AreaSeries, ...). Si la versión es v4, usar chart.addAreaSeries(...).
    const series = chart.addSeries(AreaSeries, {
      lineColor: "#00ff88", topColor: "rgba(0,255,136,0.25)", bottomColor: "rgba(0,255,136,0.02)",
    });
    let cancelled = false;
    if (sessionId !== null) {
      api.getEquityCurve(sessionId).then((rows) => {
        if (!cancelled) series.setData(equitySeries(rows) as never);
      }).catch(() => {});
    }
    const onResize = () => ref.current && chart.applyOptions({ width: ref.current.clientWidth });
    onResize(); window.addEventListener("resize", onResize);
    return () => { cancelled = true; window.removeEventListener("resize", onResize); chart.remove(); };
  }, [sessionId]);
  return <div className="panel" ref={ref} style={{ width: "100%" }} />;
}
```
> Si `import { AreaSeries }` no existe en la versión instalada (v4), usa `chart.addAreaSeries({...})` y elimina el import de `AreaSeries`. Verifica con la versión instalada antes de cerrar.

- [ ] **Step 8: Wire en `page.tsx`** — añade `<EquityHero account>` y `<EquityCurve sessionId>` bajo HeaderBar.

- [ ] **Step 9: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): EquityHero + EquityCurve (lightweight-charts) + equitySeries"
```

---

### Task 3: OpenPositions (con sparkline)

**Files:** Create: `dashboard/components/OpenPositions.tsx`, `dashboard/components/Sparkline.tsx`. Modify: `dashboard/lib/view.ts` (+ `positionView`), test.

**Interfaces:**
- Produces: `positionView(pos: Position, mid: number | null): {sideColor, markPx, pnlColor, sideLabel}` (puro); `<OpenPositions positions, coins/>`; `<Sparkline points={number[]}/>` (SVG inline).

- [ ] **Step 1: Test que falla** (añadir a `view.test.ts`)
```ts
import { positionView } from "../view";
import type { Position } from "../types";
describe("positionView", () => {
  const base: Position = { coin: "ETH", side: "long", leverage: 3, notional: 12, size: 0.004,
    entry_px: 3000, mark_px: null, unrealized_pnl: 0.07, liq_px: 2000 };
  it("uses live mid when mark_px null and colors by pnl", () => {
    const v = positionView(base, 3050);
    expect(v.markPx).toBe(3050);
    expect(v.pnlColor).toBe("var(--neon-green)");
    expect(v.sideLabel).toBe("LONG");
  });
  it("falls back to entry when no mid", () => {
    expect(positionView(base, null).markPx).toBe(3000);
  });
});
```

- [ ] **Step 2: Verificar fallo** — `npm test -- view` → FAIL.

- [ ] **Step 3: Implementar `positionView` en `view.ts`**
```ts
import type { Position } from "./types";
export function positionView(pos: Position, mid: number | null) {
  const markPx = mid ?? pos.mark_px ?? pos.entry_px;
  const isLong = pos.side === "long";
  return {
    sideLabel: pos.side.toUpperCase(),
    sideColor: isLong ? "var(--neon-green)" : "var(--neon-red)",
    markPx,
    pnlColor: pos.unrealized_pnl < 0 ? "var(--neon-red)" : "var(--neon-green)",
  };
}
```

- [ ] **Step 4: Verificar PASS** — `npm test -- view` → PASS.

- [ ] **Step 5: `dashboard/components/Sparkline.tsx`** (SVG puro, sin deps)
```tsx
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
```

- [ ] **Step 6: `dashboard/components/OpenPositions.tsx`**
```tsx
import type { Position, CoinView } from "@/lib/types";
import { fmtUsd } from "@/lib/format";
import { positionView } from "@/lib/view";
import { Sparkline } from "./Sparkline";

export function OpenPositions({ positions, coins, onFocus }: {
  positions: Position[]; coins: Record<string, CoinView>; onFocus?: (coin: string) => void;
}) {
  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>OPEN POSITIONS</div>
      {positions.length === 0 && <div className="muted" style={{ fontSize: 12 }}>sin posiciones abiertas</div>}
      {positions.map((p) => {
        const mid = coins[p.coin]?.mid ?? null;
        const v = positionView(p, mid);
        return (
          <div key={p.coin} onClick={() => onFocus?.(p.coin)}
            style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 80px 1.2fr 1fr 1fr", alignItems: "center", gap: 8, padding: "10px 4px", borderBottom: "1px solid #1c1f26", cursor: "pointer" }}>
            <span><b>{p.coin}</b> <span style={{ color: v.sideColor }}>{v.sideLabel}</span> <span className="muted">{p.leverage ?? "-"}x</span></span>
            <span>{fmtUsd(p.notional)}</span>
            <Sparkline points={[p.entry_px, v.markPx]} color={v.pnlColor} />
            <span className="muted">{p.entry_px} → <b style={{ color: "var(--text)" }}>{v.markPx}</b></span>
            <span style={{ color: v.pnlColor }}>{fmtUsd(p.unrealized_pnl)}</span>
            <span className="muted" style={{ fontSize: 12 }}>liq {p.liq_px ?? "—"}</span>
          </div>
        );
      })}
    </div>
  );
}
```
> Sparkline con 2 puntos (entry→mark) por ahora; en una mejora futura se alimentará de la mini-serie de precios.

- [ ] **Step 7: Wire en `page.tsx`** (con estado de foco que se usará en Task 5).

- [ ] **Step 8: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): OpenPositions + Sparkline + positionView"
```

---

### Task 4: Watchlist (gauges de condiciones + ARMED)

**Files:** Create: `dashboard/components/Watchlist.tsx`, `dashboard/components/Gauge.tsx`. Modify: `dashboard/lib/view.ts` (+ `conditionPct`), test.

**Interfaces:**
- Produces: `conditionPct(c: Condition): number` (0..1, progreso hacia el umbral); `<Watchlist coins, positions, onFocus/>`; `<Gauge pct, label, met/>`.

- [ ] **Step 1: Test que falla** (añadir a `view.test.ts`)
```ts
import { conditionPct } from "../view";
describe("conditionPct", () => {
  it("ratio value/threshold clamped 0..1", () => {
    expect(conditionPct({ name: "adx", value: 12.5, threshold: 25, met: false })).toBeCloseTo(0.5);
    expect(conditionPct({ name: "adx", value: 30, threshold: 25, met: true })).toBe(1);
    expect(conditionPct({ name: "x", value: 5, threshold: 0, met: true })).toBe(1);
  });
});
```

- [ ] **Step 2: Verificar fallo** — `npm test -- view` → FAIL.

- [ ] **Step 3: Implementar `conditionPct` en `view.ts`**
```ts
import type { Condition } from "./types";
export function conditionPct(c: Condition): number {
  if (c.met) return 1;
  if (!c.threshold) return c.met ? 1 : 0;
  const r = Math.abs(c.value) / Math.abs(c.threshold);
  return Math.max(0, Math.min(1, r));
}
```

- [ ] **Step 4: Verificar PASS** — `npm test -- view` → PASS.

- [ ] **Step 5: `dashboard/components/Gauge.tsx`**
```tsx
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
```

- [ ] **Step 6: `dashboard/components/Watchlist.tsx`**
```tsx
import type { CoinView, Position } from "@/lib/types";
import { conditionPct } from "@/lib/view";
import { Gauge } from "./Gauge";

export function Watchlist({ coins, positions, onFocus }: {
  coins: Record<string, CoinView>; positions: Position[]; onFocus?: (coin: string) => void;
}) {
  const open = new Set(positions.map((p) => p.coin));
  const candidates = Object.entries(coins).filter(([c]) => !open.has(c));
  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>WATCHLIST · condiciones para abrir</div>
      {candidates.length === 0 && <div className="muted" style={{ fontSize: 12 }}>todos los pares con posición</div>}
      {candidates.map(([coin, cv]) => (
        <div key={coin} onClick={() => onFocus?.(coin)} style={{ padding: "8px 4px", borderBottom: "1px solid #1c1f26", cursor: "pointer" }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span><b>{coin}</b> <span className="muted">{cv.mode}</span> <span className="muted">{cv.mid}</span></span>
            {cv.armed && <span className="glow" style={{ color: "var(--neon-green)", fontWeight: 700 }}>ARMED</span>}
          </div>
          <div style={{ marginTop: 6 }}>
            {cv.conditions.map((c) => <Gauge key={c.name} label={c.name} pct={conditionPct(c)} met={c.met} />)}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 7: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): Watchlist + Gauge + conditionPct (condiciones/ARMED)"
```

---

### Task 5: FocusChart (candles + triggers/EMAs) + estado de foco

**Files:** Create: `dashboard/components/FocusChart.tsx`. Modify: `dashboard/lib/view.ts` (+ `candleSeries`), test; `app/page.tsx` (estado de par enfocado).

**Interfaces:**
- Produces: `candleSeries(candles: Candle[]): Candle[]` (ya vienen en segundos ascendente; passthrough tipado); `<FocusChart coin, coinView/>` que pinta candles + price-lines de triggers.

- [ ] **Step 1: Test que falla** (añadir a `view.test.ts`)
```ts
import { candleSeries } from "../view";
describe("candleSeries", () => {
  it("passes through sorted by time", () => {
    const out = candleSeries([{ time: 2, open: 1, high: 2, low: 1, close: 1.5 }, { time: 1, open: 1, high: 1, low: 1, close: 1 }] as never);
    expect(out.map((c) => c.time)).toEqual([1, 2]);
  });
});
```

- [ ] **Step 2: Verificar fallo** — `npm test -- view` → FAIL.

- [ ] **Step 3: Implementar `candleSeries` en `view.ts`**
```ts
import type { Candle } from "./types";
export function candleSeries(candles: Candle[]): Candle[] {
  return [...candles].sort((a, b) => a.time - b.time);
}
```

- [ ] **Step 4: Verificar PASS** — `npm test -- view` → PASS.

- [ ] **Step 5: `dashboard/components/FocusChart.tsx`** (candlestick + price lines de triggers; adapta API a la versión instalada)
```tsx
"use client";
import { useEffect, useRef } from "react";
import { createChart, CandlestickSeries, type IChartApi, type ISeriesApi } from "lightweight-charts";
import type { CoinView } from "@/lib/types";
import { api } from "@/lib/api";
import { candleSeries } from "@/lib/view";

export function FocusChart({ coin, coinView }: { coin: string | null; coinView: CoinView | undefined }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height: 320, layout: { background: { color: "transparent" }, textColor: "#8a8f98" },
      grid: { vertLines: { color: "#14171c" }, horzLines: { color: "#14171c" } },
      rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#00ff88", downColor: "#ff4466", wickUpColor: "#00ff88", wickDownColor: "#ff4466", borderVisible: false,
    });
    chartRef.current = chart; seriesRef.current = series;
    const onResize = () => ref.current && chart.applyOptions({ width: ref.current.clientWidth });
    onResize(); window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !coin) return;
    let cancelled = false;
    api.getCandles(coin).then((cs) => { if (!cancelled) series.setData(candleSeries(cs) as never); }).catch(() => {});
    return () => { cancelled = true; };
  }, [coin]);

  // Price lines de triggers (se recrean cuando cambian)
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const lines = (coinView?.triggers ?? []).map((t) =>
      series.createPriceLine({ price: t.level, color: t.side === "buy" ? "#00ff88" : "#ff4466", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: t.action }));
    return () => { lines.forEach((l) => series.removePriceLine(l)); };
  }, [coinView]);

  return (
    <div className="panel" style={{ padding: 8 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>{coin ?? "—"} · live</div>
      <div ref={ref} style={{ width: "100%" }} />
    </div>
  );
}
```
> Adapta `addSeries(CandlestickSeries,...)`/`createPriceLine`/`removePriceLine` a la versión instalada de lightweight-charts (v5 usa `addSeries(SeriesType, opts)`; v4 usa `addCandlestickSeries(opts)`). Verifica con la versión instalada.

- [ ] **Step 6: Estado de foco en `page.tsx`** — `const [focus, setFocus] = useState<string|null>(null)`; foco por defecto = primera posición o primera coin de la watchlist; pasar `onFocus={setFocus}` a OpenPositions/Watchlist y `<FocusChart coin={focus} coinView={snapshot?.coins[focus]} />`.

- [ ] **Step 7: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): FocusChart (candles + price-lines de triggers) + foco de par"
```

---

### Task 6: Tape + ensamblado grid tiled

**Files:** Create: `dashboard/components/Tape.tsx`. Modify: `dashboard/app/page.tsx` (layout grid final).

**Interfaces:**
- Produces: `<Tape events/>`; `app/page.tsx` con el grid tiled completo.

- [ ] **Step 1: `dashboard/components/Tape.tsx`**
```tsx
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
```

- [ ] **Step 2: Ensamblar `app/page.tsx`** (grid tiled: izquierda = hero+curva+stats+posiciones+tape; derecha = chart+watchlist)
```tsx
"use client";
import { useState } from "react";
import { useLiveSnapshot } from "@/lib/useLiveSnapshot";
import { HeaderBar } from "@/components/HeaderBar";
import { StatTiles } from "@/components/StatTiles";
import { EquityHero } from "@/components/EquityHero";
import { EquityCurve } from "@/components/EquityCurve";
import { OpenPositions } from "@/components/OpenPositions";
import { Watchlist } from "@/components/Watchlist";
import { FocusChart } from "@/components/FocusChart";
import { Tape } from "@/components/Tape";

export default function Home() {
  const { snapshot, connected } = useLiveSnapshot();
  const [focus, setFocus] = useState<string | null>(null);
  const coins = snapshot?.coins ?? {};
  const positions = snapshot?.positions ?? [];
  const effFocus = focus ?? positions[0]?.coin ?? Object.keys(coins)[0] ?? null;

  return (
    <main style={{ padding: 12, display: "flex", flexDirection: "column", gap: 12, minHeight: "100vh" }}>
      <HeaderBar snapshot={snapshot} connected={connected} />
      {snapshot && (
        <div style={{ display: "grid", gridTemplateColumns: "1.1fr 1fr", gap: 12 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <EquityHero account={snapshot.account} />
            <EquityCurve sessionId={snapshot.session_id} />
            <StatTiles account={snapshot.account} />
            <OpenPositions positions={positions} coins={coins} onFocus={setFocus} />
            <Tape events={snapshot.tape_recent} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <FocusChart coin={effFocus} coinView={effFocus ? coins[effFocus] : undefined} />
            <Watchlist coins={coins} positions={positions} onFocus={setFocus} />
          </div>
        </div>
      )}
    </main>
  );
}
```

- [ ] **Step 3: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): Tape + ensamblado del terminal grid tiled"
```

---

## Notas para el ejecutor
- **Lightweight-Charts**: el detalle más probable de ajuste es la API de series. Verifica la versión instalada (`npm ls lightweight-charts`) y usa su forma: v5 `chart.addSeries(AreaSeries|CandlestickSeries, opts)` (imports nombrados) o v4 `chart.addAreaSeries/addCandlestickSeries(opts)`. `createPriceLine`/`removePriceLine` existen en ambas. Mantén el componente compilando (`npm run build` es el gate).
- La verificación visual real la hace el usuario; deja `npm run dev` operativo. Con el bot en `:3300` IDLE, el snapshot llega pero con pocas posiciones; los paneles deben renderizar sin romper con datos vacíos (account normalizado, arrays vacíos).
- Siguiente slice: **2b.3 (control + estímulo)**.
