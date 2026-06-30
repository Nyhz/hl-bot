# Rediseño del Trade dashboard — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rediseñar la vista LIVE a 100vw×100vh sin scroll, con las posiciones abiertas en un grid adaptativo central (cada una con gráfica + datos + decisiones del bot encima), la config de lanzamiento en un modal, y banda superior (Session P&L + gráfica + stats) + raíl derecho (watchlist + tape).

**Architecture:** Solo frontend (Next.js 16 + TS). Reutiliza componentes existentes (`EquityHero`, `EquityCurve`, `StatTiles`, `AttributionPanel`, `Watchlist`, `Tape`, `SessionControls`, `FocusChart`, `Gauge`) y añade `TradeGrid`/`TradeSlot`/`LaunchModal` + clases CSS de layout a pantalla completa. La lógica de reparto es pura y testeada (`slotLayout`, `slotItems`).

**Tech Stack:** Next.js 16, React 19, TypeScript, lightweight-charts v5, Vitest. Comandos desde `dashboard/`: `npx vitest run`, `npm run lint`, `npm run build`.

## Global Constraints

- Solo frontend: NO se toca el bot/API/riesgo ni el contrato de control (proxy server-side con CONTROL_TOKEN intacto).
- 100vw×100vh sin scroll de página en ≥1024px; por debajo se permite scroll y las regiones se apilan.
- Grid central adaptativo por nº de posiciones: 0→idle, 1→un slot, 2→dos, 3-4→2×2. Tope real de posiciones = 4.
- Cada `TradeSlot` usa el `mid` vivo de `coins[coin].mid` (el backend manda `mark_px=null`).
- Editor TS diagnostics en archivos del dashboard pueden ser FALSOS POSITIVOS (tsconfig raíz excluye `dashboard/`); el gate real es `npm run build` + `lint` + `vitest`.
- TDD para lógica pura (Task 1). Los componentes (Tasks 2-5) se validan con build+lint+vitest verdes (no hay jsdom); render lo revisa el usuario.

---

## File Structure

- `dashboard/lib/view.ts` — añadir `slotLayout`, `slotItems` (+ tipo `SlotItem`).
- `dashboard/lib/view.test.ts` — tests de los helpers.
- `dashboard/components/FocusChart.tsx` — añadir prop `fill?: boolean` (la gráfica llena su contenedor en alto).
- `dashboard/components/TradeSlot.tsx` — NUEVO: una posición (cabecera de datos + FocusChart fill + condiciones).
- `dashboard/components/TradeGrid.tsx` — NUEVO: grid adaptativo de slots.
- `dashboard/components/LaunchModal.tsx` — NUEVO: overlay que envuelve `LaunchPanel`.
- `dashboard/components/LaunchPanel.tsx` — añadir prop `onLaunched?: () => void`.
- `dashboard/components/HeaderBar.tsx` — controles a la derecha: Launch (idle) / SessionControls (activa).
- `dashboard/app/globals.css` — clases de layout a pantalla completa.
- `dashboard/app/page.tsx` — relayout completo.

---

## Task 1: Helpers puros de reparto (`slotLayout`, `slotItems`)

**Files:**
- Modify: `dashboard/lib/view.ts`
- Test: `dashboard/lib/view.test.ts`

**Interfaces:**
- Produces: `slotLayout(n: number): "idle" | "one" | "two" | "grid"`; `interface SlotItem { coin: string; position: Position; coinView: CoinView | undefined }`; `slotItems(positions: Position[], coins: Record<string, CoinView>): SlotItem[]` (ordena por coin asc, cap 4, mapea coinView).

- [ ] **Step 1: Tests que fallan** — añadir a `dashboard/lib/view.test.ts`:

```ts
import { slotLayout, slotItems } from "./view";

describe("slotLayout", () => {
  it("mapea el nº de posiciones al reparto", () => {
    expect(slotLayout(0)).toBe("idle");
    expect(slotLayout(1)).toBe("one");
    expect(slotLayout(2)).toBe("two");
    expect(slotLayout(3)).toBe("grid");
    expect(slotLayout(4)).toBe("grid");
  });
});

describe("slotItems", () => {
  const pos = (coin: string) => ({ coin, side: "long", leverage: 2, notional: 10, size: 1,
    entry_px: 100, mark_px: null, unrealized_pnl: 0, liq_px: null });
  it("ordena por coin, capa a 4 y adjunta el coinView", () => {
    const positions = [pos("SOL"), pos("BTC"), pos("ETH")] as never;
    const coins = { BTC: { mid: 1 }, ETH: { mid: 2 }, SOL: { mid: 3 } } as never;
    const items = slotItems(positions, coins);
    expect(items.map((i) => i.coin)).toEqual(["BTC", "ETH", "SOL"]);
    expect(items[0].coinView).toEqual({ mid: 1 });
  });
  it("nunca devuelve más de 4", () => {
    const positions = ["A", "B", "C", "D", "E"].map(pos) as never;
    expect(slotItems(positions, {} as never).length).toBe(4);
  });
});
```

- [ ] **Step 2: Verificar fallo**

Run (desde `dashboard/`): `npx vitest run lib/view.test.ts`
Expected: FAIL (`slotLayout`/`slotItems` no existen).

- [ ] **Step 3: Implementar** — en `dashboard/lib/view.ts`, asegurar el import de tipos e implementar. Cambiar la primera línea de import si hace falta para incluir `Position, CoinView`:

```ts
import type { Candle, Condition, Position, CoinView } from "./types";
```

Y añadir al final del archivo:

```ts
export function slotLayout(n: number): "idle" | "one" | "two" | "grid" {
  if (n <= 0) return "idle";
  if (n === 1) return "one";
  if (n === 2) return "two";
  return "grid";
}

export interface SlotItem { coin: string; position: Position; coinView: CoinView | undefined; }

export function slotItems(positions: Position[], coins: Record<string, CoinView>): SlotItem[] {
  return [...positions]
    .sort((a, b) => a.coin.localeCompare(b.coin))
    .slice(0, 4)
    .map((p) => ({ coin: p.coin, position: p, coinView: coins[p.coin] }));
}
```

- [ ] **Step 4: Verificar que pasa**

Run (desde `dashboard/`): `npx vitest run lib/view.test.ts` (PASS), luego `npx vitest run` (todos) + `npm run lint`.
Expected: PASS / limpio.

- [ ] **Step 5: Commit**

```bash
git add dashboard/lib/view.ts dashboard/lib/view.test.ts
git commit -m "feat(redesign): helpers slotLayout/slotItems para el grid adaptativo"
```

---

## Task 2: `FocusChart` con `fill` + `TradeSlot`

**Files:**
- Modify: `dashboard/components/FocusChart.tsx` (prop `fill?: boolean`)
- Create: `dashboard/components/TradeSlot.tsx`
- (sin test unitario; gate build+lint)

**Interfaces:**
- Consumes: `positionView`, `conditionPct` (view.ts), `FocusChart`, `Gauge`, tipos `Position`/`CoinView`.
- Produces: `FocusChart` acepta `fill?: boolean` (cuando true, la gráfica llena el alto del contenedor y no dibuja su propio `.panel`). `TradeSlot({ position, coinView })` → panel con cabecera de datos + FocusChart fill + tira de condiciones.

- [ ] **Step 1: Implementar `fill` en `FocusChart.tsx`** — reemplazar el `useEffect` de creación del chart y el `return` por versiones que soporten `fill`. La firma pasa a:

```tsx
export function FocusChart({ coin, coinView, mid, fill }: { coin: string | null; coinView: CoinView | undefined; mid: number | null; fill?: boolean }) {
```

En el `useEffect` de creación, usar la altura del contenedor cuando `fill`:

```tsx
  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const chart = createChart(el, {
      height: fill ? (el.clientHeight || 240) : 320,
      layout: { background: { color: "transparent" }, textColor: "#8a8f98" },
      grid: { vertLines: { color: "#14171c" }, horzLines: { color: "#14171c" } },
      rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#00ff88", downColor: "#ff4466", wickUpColor: "#00ff88", wickDownColor: "#ff4466", borderVisible: false,
    });
    chartRef.current = chart; seriesRef.current = series;
    const fit = () => chart.applyOptions(fill
      ? { width: el.clientWidth, height: el.clientHeight }
      : { width: el.clientWidth });
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, [fill]);
```

Y el `return` para que, con `fill`, el componente llene el alto y no añada un `.panel` extra (el `TradeSlot` ya es el panel):

```tsx
  const rootStyle: React.CSSProperties = fill
    ? { display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }
    : { padding: 8 };
  const chartStyle: React.CSSProperties = fill
    ? { width: "100%", flex: 1, minHeight: 0 }
    : { width: "100%" };
  return (
    <div className={fill ? undefined : "panel"} style={rootStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
        <span className="muted" style={{ fontSize: 11 }}>{coin ?? "—"} · live{coinView ? ` · ${coinView.mode}` : ""}</span>
        <span style={{ fontSize: 11, color: fundingColor(coinView?.funding) }} title="funding horario">fund {fmtFunding(coinView?.funding)}</span>
      </div>
      <div ref={ref} style={chartStyle} />
    </div>
  );
```

(El resto de `FocusChart` —efectos de velas, triggers, mid— no cambia.)

- [ ] **Step 2: Crear `dashboard/components/TradeSlot.tsx`**:

```tsx
"use client";
import type { Position, CoinView } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { positionView, conditionPct } from "@/lib/view";
import { FocusChart } from "./FocusChart";
import { Gauge } from "./Gauge";

export function TradeSlot({ position, coinView }: { position: Position; coinView: CoinView | undefined }) {
  const mid = coinView?.mid ?? null;
  const v = positionView(position, mid);
  const pnlPct = position.notional ? position.unrealized_pnl / position.notional : 0;
  return (
    <div className="panel trade-slot">
      <div className="trade-slot-head">
        <span style={{ fontWeight: 700 }}>{position.coin}</span>
        <span style={{ color: v.sideColor }}>{v.sideLabel}</span>
        <span className="muted">{position.leverage ?? "-"}x</span>
        <span className="muted">{position.entry_px} → <b style={{ color: "var(--text)" }}>{v.markPx}</b></span>
        <span style={{ color: v.pnlColor, marginLeft: "auto", fontWeight: 700 }}>
          {fmtUsd(position.unrealized_pnl)} <span style={{ fontSize: 11 }}>{fmtPct(pnlPct)}</span>
        </span>
        <span className="muted" style={{ fontSize: 11 }}>liq {position.liq_px ?? "—"}</span>
      </div>
      <div className="trade-slot-chart">
        <FocusChart coin={position.coin} coinView={coinView} mid={mid} fill />
      </div>
      {coinView && coinView.conditions.length > 0 && (
        <div className="trade-slot-conds">
          {coinView.conditions.map((c) => <Gauge key={c.name} label={c.name} pct={conditionPct(c)} met={c.met} />)}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Verificar** — `npm run lint` (limpio) + `npm run build` (verde) + `npx vitest run` (sin romper). El `FocusChart` no-fill sigue usándose donde estaba; confirmar que el build no se queja del nuevo prop.

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/FocusChart.tsx dashboard/components/TradeSlot.tsx
git commit -m "feat(redesign): FocusChart fill + TradeSlot (datos + gráfica + condiciones)"
```

---

## Task 3: `TradeGrid` (grid adaptativo)

**Files:**
- Create: `dashboard/components/TradeGrid.tsx`
- (sin test unitario; la lógica vive en `slotLayout`/`slotItems` ya testeados)

**Interfaces:**
- Consumes: `slotLayout`, `slotItems` (Task 1), `TradeSlot` (Task 2), tipos `Position`/`CoinView`.
- Produces: `TradeGrid({ positions, coins, watchlistCount })` → contenedor `.trade-grid[data-layout]` con un `TradeSlot` por posición, o estado idle.

- [ ] **Step 1: Implementar** — `dashboard/components/TradeGrid.tsx`:

```tsx
"use client";
import type { Position, CoinView } from "@/lib/types";
import { slotLayout, slotItems } from "@/lib/view";
import { TradeSlot } from "./TradeSlot";

export function TradeGrid({ positions, coins, watchlistCount }: {
  positions: Position[]; coins: Record<string, CoinView>; watchlistCount: number;
}) {
  const layout = slotLayout(positions.length);
  if (layout === "idle") {
    return (
      <div className="panel trade-grid-idle muted">
        sin posiciones abiertas · vigilando {watchlistCount} {watchlistCount === 1 ? "par" : "pares"}
      </div>
    );
  }
  const items = slotItems(positions, coins);
  return (
    <div className="trade-grid" data-layout={layout}>
      {items.map((it) => <TradeSlot key={it.coin} position={it.position} coinView={it.coinView} />)}
    </div>
  );
}
```

- [ ] **Step 2: Verificar** — `npm run lint` + `npm run build` + `npx vitest run` (verdes).

- [ ] **Step 3: Commit**

```bash
git add dashboard/components/TradeGrid.tsx
git commit -m "feat(redesign): TradeGrid adaptativo (0/1/2/3-4 posiciones)"
```

---

## Task 4: `LaunchModal` + `LaunchPanel.onLaunched`

**Files:**
- Modify: `dashboard/components/LaunchPanel.tsx` (prop `onLaunched?`)
- Create: `dashboard/components/LaunchModal.tsx`

**Interfaces:**
- Consumes: `LaunchPanel` (existente).
- Produces: `LaunchPanel` acepta `onLaunched?: () => void` (se llama tras launch OK). `LaunchModal({ coins, state, open, onClose })` → overlay fijo que renderiza `LaunchPanel` y cierra con X/Esc/click-fondo y al lanzar.

- [ ] **Step 1: `LaunchPanel.onLaunched`** — en `dashboard/components/LaunchPanel.tsx`, cambiar la firma para aceptar el callback y llamarlo tras éxito. Firma:

```tsx
export function LaunchPanel({ coins, state, onLaunched }: { coins: { name: string }[]; state: string; onLaunched?: () => void }) {
```

En `launch()`, tras `if (r.ok) toast.success("Sesión lanzada");`, añadir la llamada:

```tsx
    if (r.ok) { toast.success("Sesión lanzada"); onLaunched?.(); }
    else toast.error(`No se pudo lanzar (${r.status}): ${(r.data as { detail?: string })?.detail ?? ""}`);
```

(Sin otros cambios; el resto del panel queda igual.)

- [ ] **Step 2: Crear `dashboard/components/LaunchModal.tsx`**:

```tsx
"use client";
import { useEffect } from "react";
import { LaunchPanel } from "./LaunchPanel";

export function LaunchModal({ coins, state, open, onClose }: {
  coins: { name: string }[]; state: string; open: boolean; onClose: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div onClick={onClose}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.6)", zIndex: 50,
        display: "flex", alignItems: "flex-start", justifyContent: "center", padding: "6vh 12px" }}>
      <div onClick={(e) => e.stopPropagation()} style={{ width: "min(560px, 94vw)", maxHeight: "88vh", overflow: "auto" }}>
        <LaunchPanel coins={coins} state={state} onLaunched={onClose} />
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Verificar** — `npm run lint` + `npm run build` + `npx vitest run` (verdes).

- [ ] **Step 4: Commit**

```bash
git add dashboard/components/LaunchPanel.tsx dashboard/components/LaunchModal.tsx
git commit -m "feat(redesign): LaunchModal envolviendo LaunchPanel (+onLaunched)"
```

---

## Task 5: Topbar (controles), CSS a pantalla completa y relayout de `page.tsx`

**Files:**
- Modify: `dashboard/components/HeaderBar.tsx`
- Modify: `dashboard/app/globals.css`
- Modify: `dashboard/app/page.tsx`

**Interfaces:**
- Consumes: `TradeGrid`, `LaunchModal` (Tasks 3-4), `SessionControls`, banda (`EquityHero`/`EquityCurve`/`StatTiles`/`AttributionPanel`), raíl (`Watchlist`/`Tape`).
- Produces: layout final 100vh.

- [ ] **Step 1: `HeaderBar` — controles a la derecha.** En `dashboard/components/HeaderBar.tsx`, ampliar la firma con `state` y `onLaunch`, e importar `SessionControls`. Añadir el import:

```tsx
import { SessionControls } from "./SessionControls";
```

Firma:

```tsx
export function HeaderBar({ snapshot, connected, state, onLaunch }: { snapshot: Snapshot | null; connected: boolean; state: string; onLaunch: () => void }) {
```

Antes del `</div>` de cierre de la `.header-bar` (después del `<span className="muted">{(snapshot?.state ?? "—").toUpperCase()}</span>`), añadir la región de controles:

```tsx
      <span style={{ marginLeft: 8 }}>
        {state === "idle"
          ? <button onClick={onLaunch}
              style={{ padding: "4px 12px", border: "none", borderRadius: 6, background: "var(--neon-green)",
                color: "#000", fontWeight: 700, cursor: "pointer", fontSize: 12 }}>▶ Launch</button>
          : <SessionControls state={state} />}
      </span>
```

- [ ] **Step 2: CSS a pantalla completa.** Añadir al final de `dashboard/app/globals.css`:

```css
/* ---- Trade dashboard 100vh ---- */
.app-100vh { height: 100vh; display: flex; flex-direction: column; gap: 8px; padding: 8px; overflow: hidden; }
.trade-body { flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 8px; }
.top-band { display: grid; grid-template-columns: minmax(200px,1fr) minmax(280px,1.6fr) minmax(240px,1.4fr) minmax(190px,1fr); gap: 8px; flex: 0 0 auto; }
.trade-main { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0,3fr) minmax(260px,1fr); gap: 8px; }
.center-stage { min-width: 0; min-height: 0; display: flex; }
.right-rail { display: flex; flex-direction: column; gap: 8px; min-height: 0; }
.right-rail > * { min-height: 0; overflow: auto; }
.trade-grid { flex: 1; min-height: 0; width: 100%; display: grid; gap: 8px; }
.trade-grid[data-layout="one"]  { grid-template-columns: 1fr;     grid-template-rows: 1fr; }
.trade-grid[data-layout="two"]  { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr; }
.trade-grid[data-layout="grid"] { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }
.trade-grid-idle { flex: 1; display: flex; align-items: center; justify-content: center; font-size: 13px; }
.trade-slot { display: flex; flex-direction: column; min-height: 0; min-width: 0; padding: 8px; gap: 6px; }
.trade-slot-head { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; font-size: 12px; }
.trade-slot-chart { flex: 1; min-height: 0; }
.trade-slot-conds { flex: 0 0 auto; }
@media (max-width: 1100px) { .top-band { grid-template-columns: 1fr 1fr; } }
@media (max-width: 1024px) {
  .app-100vh { height: auto; overflow: visible; }
  .trade-main { grid-template-columns: 1fr; }
  .trade-grid[data-layout] { grid-template-rows: none; }
  .trade-slot { min-height: 320px; }
}
```

- [ ] **Step 3: Relayout de `page.tsx`.** Reemplazar TODO el contenido de `dashboard/app/page.tsx` por:

```tsx
"use client";
import { useState, useEffect } from "react";
import { useLiveSnapshot } from "@/lib/useLiveSnapshot";
import { api } from "@/lib/api";
import { HeaderBar } from "@/components/HeaderBar";
import { EquityHero } from "@/components/EquityHero";
import { EquityCurve } from "@/components/EquityCurve";
import { StatTiles } from "@/components/StatTiles";
import { AttributionPanel } from "@/components/AttributionPanel";
import { TradeGrid } from "@/components/TradeGrid";
import { Watchlist } from "@/components/Watchlist";
import { Tape } from "@/components/Tape";
import { LaunchModal } from "@/components/LaunchModal";
import { useEventFeedback } from "@/hooks/useEventFeedback";

export default function Home() {
  const { snapshot, connected } = useLiveSnapshot();
  useEventFeedback(snapshot);
  const [coinsList, setCoinsList] = useState<{ name: string }[]>([]);
  const [launchOpen, setLaunchOpen] = useState(false);
  useEffect(() => { api.getCoins().then(setCoinsList).catch(() => {}); }, []);
  const sessionState = snapshot?.state ?? "idle";

  return (
    <main className="app-100vh">
      <HeaderBar snapshot={snapshot} connected={connected} state={sessionState} onLaunch={() => setLaunchOpen(true)} />
      {snapshot ? (
        <div className="trade-body">
          <div className="top-band">
            <EquityHero account={snapshot.account} />
            <EquityCurve sessionId={snapshot.session_id} equity={snapshot.account.equity} />
            <StatTiles account={snapshot.account} />
            <AttributionPanel account={snapshot.account} />
          </div>
          <div className="trade-main">
            <div className="center-stage">
              <TradeGrid positions={snapshot.positions} coins={snapshot.coins} watchlistCount={snapshot.watchlist.length} />
            </div>
            <div className="right-rail">
              <Watchlist coins={snapshot.coins} positions={snapshot.positions} />
              <Tape events={snapshot.tape_recent} />
            </div>
          </div>
        </div>
      ) : (
        <div className="panel muted" style={{ padding: 16 }}>conectando…</div>
      )}
      <LaunchModal coins={coinsList} state={sessionState} open={launchOpen} onClose={() => setLaunchOpen(false)} />
    </main>
  );
}
```

(Nota: `Watchlist` ya tiene `onFocus?` opcional — se omite, ya no hay gráfica central de foco. `EquityCurve` y `StatTiles`/`AttributionPanel` se reutilizan tal cual dentro de la banda.)

- [ ] **Step 4: Verificar** — desde `dashboard/`: `npm run lint` (limpio), `npm run build` (verde), `npx vitest run` (todos verdes).

- [ ] **Step 5: Commit**

```bash
git add dashboard/components/HeaderBar.tsx dashboard/app/globals.css dashboard/app/page.tsx
git commit -m "feat(redesign): topbar con Launch/Close/Kill, CSS 100vh y relayout (banda + grid + raíl)"
```

---

## Notas de integración (para el revisor final)

- `SessionControls` ya gestiona Close/Kill (con confirmación de kill) según `state`; solo se reubica en la topbar.
- `EquityCurve` en la banda mantiene su uso `sessionId`+`equity` (append en vivo gated por `equity>0`) — sin `seed`.
- `FocusChart fill` reusa los efectos de velas/triggers/mid; solo cambia el dimensionado (ahora también alto vía ResizeObserver) y que no pinta `.panel` cuando `fill` (el `.trade-slot` es el panel).
- El grid central usa `min-height:0`/`min-width:0` en toda la cadena (app-100vh → trade-body → trade-main → center-stage → trade-grid → trade-slot → trade-slot-chart) para que lightweight-charts pueda encoger y llenar; si una gráfica no se ve, casi siempre falta un `min-height:0` en algún eslabón.
- Responsive <1024px: se permite scroll y se apila (no romper móvil); los slots toman `min-height:320px`.
- No se toca `/sessions` ni `/backtest` ni el bot.
