# Dashboard 2b.3 — Control + estímulo: Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Permitir lanzar/cerrar/matar sesiones desde el dashboard (vía el proxy de control con token server-side), dar feedback de estímulo (toasts + sonido al abrir/cerrar posición), hacer que los charts actualicen en vivo (sin recargar), y añadir micro-animaciones (number-tickers, pulsos, LIVE/ARMED glow).

**Architecture:** LaunchPanel (formulario → `fetch('/api/control/...')` que ya inyecta el token). Lógica pura testeable en `lib/control.ts` (buildLaunchBody) y `lib/diff.ts` (diffPositions para detectar aperturas/cierres entre snapshots). Toasts con `sonner` + un beep WebAudio (sin assets). Charts: `series.update()` por tick (equity + vela en formación). Animaciones con CSS keyframes + un NumberTicker rAF (sin dependencias pesadas nuevas).

**Tech Stack:** Next.js + TS + Tailwind v4, lightweight-charts v5, sonner, Vitest. Backend `:3300` (control endpoints exigen token, inyectado por el proxy de Next.js).

## Global Constraints

- Control SOLO vía las rutas `/api/control/<action>` de Next.js (el token vive server-side; el navegador nunca lo ve). Acciones: launch/close/kill/limits.
- Body de launch debe coincidir con el `LaunchBody` del bot: `{watchlist: string[], capital: number, limits: {max_position_notional, max_open_positions, max_leverage, daily_loss_limit, total_loss_limit}, grid_n, grid_range_pct, adx_threshold}`. Kill exige `{confirm: true}`.
- Errores del backend: launch puede devolver 409 (estado no IDLE) o 422 (grid inasequible) — mostrar el detalle al usuario. Kill 400 si falta confirm.
- Estímulo: toast + sonido SOLO en transición (posición que aparece/desaparece entre snapshots), no en cada tick.
- Sin dependencias pesadas nuevas más allá de `sonner` (animaciones con CSS/rAF).
- Cada tarea: `npm run build` + `npm run lint` limpios + Vitest verde donde haya helper. Trabajar en `dashboard/`.

**Estructura (2b.3):**
```
dashboard/lib/control.ts          # buildLaunchBody (puro) + tipos del form
dashboard/lib/diff.ts             # diffPositions (puro)
dashboard/lib/sound.ts            # playBeep (WebAudio)
dashboard/lib/__tests__/control.test.ts, diff.test.ts
dashboard/components/LaunchPanel.tsx
dashboard/components/SessionControls.tsx   # Close / Kill (con confirm)
dashboard/components/NumberTicker.tsx
dashboard/hooks/useEventFeedback.ts        # toasts + sonido en transiciones
dashboard/app/layout.tsx          # <Toaster /> de sonner
dashboard/app/globals.css         # keyframes pulse/glow
```

---

### Task 1: LaunchPanel + SessionControls (control vía proxy)

**Files:** Create: `dashboard/lib/control.ts`, `dashboard/lib/__tests__/control.test.ts`, `dashboard/components/LaunchPanel.tsx`, `dashboard/components/SessionControls.tsx`. Modify: `dashboard/app/page.tsx` (montar los controles).

**Interfaces:**
- Produces: `buildLaunchBody(form: LaunchForm): LaunchBody` (puro); `<LaunchPanel coins, state/>` (formulario + Launch); `<SessionControls state/>` (Close/Kill con confirm). `postControl(action, body?)` helper.

- [ ] **Step 1: Test que falla** `dashboard/lib/__tests__/control.test.ts`
```ts
import { describe, it, expect } from "vitest";
import { buildLaunchBody } from "../control";

describe("buildLaunchBody", () => {
  it("builds the bot LaunchBody from form state", () => {
    const body = buildLaunchBody({
      watchlist: ["ETH", "BTC"], capital: 40, gridN: 4, gridRangePct: 0.02, adxThreshold: 25,
      maxPositionNotional: 15, maxOpenPositions: 3, maxLeverage: 2, dailyLossLimit: 5, totalLossLimit: 20,
    });
    expect(body).toEqual({
      watchlist: ["ETH", "BTC"], capital: 40, grid_n: 4, grid_range_pct: 0.02, adx_threshold: 25,
      limits: { max_position_notional: 15, max_open_positions: 3, max_leverage: 2, daily_loss_limit: 5, total_loss_limit: 20 },
    });
  });
});
```

- [ ] **Step 2: Verificar fallo** — `cd dashboard && npm test -- control` → FAIL.

- [ ] **Step 3: Implementar `dashboard/lib/control.ts`**
```ts
export interface LaunchForm {
  watchlist: string[]; capital: number; gridN: number; gridRangePct: number; adxThreshold: number;
  maxPositionNotional: number; maxOpenPositions: number; maxLeverage: number;
  dailyLossLimit: number; totalLossLimit: number;
}
export interface LaunchBody {
  watchlist: string[]; capital: number; grid_n: number; grid_range_pct: number; adx_threshold: number;
  limits: { max_position_notional: number; max_open_positions: number; max_leverage: number; daily_loss_limit: number; total_loss_limit: number };
}
export function buildLaunchBody(f: LaunchForm): LaunchBody {
  return {
    watchlist: f.watchlist, capital: f.capital, grid_n: f.gridN,
    grid_range_pct: f.gridRangePct, adx_threshold: f.adxThreshold,
    limits: {
      max_position_notional: f.maxPositionNotional, max_open_positions: f.maxOpenPositions,
      max_leverage: f.maxLeverage, daily_loss_limit: f.dailyLossLimit, total_loss_limit: f.totalLossLimit,
    },
  };
}
export async function postControl(action: string, body?: unknown): Promise<{ ok: boolean; status: number; data: unknown }> {
  const res = await fetch(`/api/control/${action}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body ?? {}),
  });
  let data: unknown = null;
  try { data = await res.json(); } catch { /* sin cuerpo */ }
  return { ok: res.ok, status: res.status, data };
}
```

- [ ] **Step 4: Verificar PASS** — `npm test -- control` → PASS.

- [ ] **Step 5: `dashboard/components/LaunchPanel.tsx`** (formulario; sólo habilitado cuando state==="idle")
```tsx
"use client";
import { useState } from "react";
import { buildLaunchBody, postControl, type LaunchForm } from "@/lib/control";
import { toast } from "sonner";

const DEFAULTS: LaunchForm = {
  watchlist: [], capital: 40, gridN: 4, gridRangePct: 0.02, adxThreshold: 25,
  maxPositionNotional: 15, maxOpenPositions: 3, maxLeverage: 2, dailyLossLimit: 5, totalLossLimit: 20,
};

export function LaunchPanel({ coins, state }: { coins: { name: string }[]; state: string }) {
  const [f, setF] = useState<LaunchForm>(DEFAULTS);
  const [busy, setBusy] = useState(false);
  const idle = state === "idle";
  const toggle = (c: string) =>
    setF((p) => ({ ...p, watchlist: p.watchlist.includes(c) ? p.watchlist.filter((x) => x !== c) : [...p.watchlist, c] }));
  const num = (k: keyof LaunchForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setF((p) => ({ ...p, [k]: Number(e.target.value) }));

  async function launch() {
    if (!f.watchlist.length) { toast.error("Elige al menos un par"); return; }
    setBusy(true);
    const r = await postControl("launch", buildLaunchBody(f));
    setBusy(false);
    if (r.ok) toast.success("Sesión lanzada");
    else toast.error(`No se pudo lanzar (${r.status}): ${(r.data as { detail?: string })?.detail ?? ""}`);
  }

  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>LAUNCH SESSION</div>
      {!idle && <div className="muted" style={{ fontSize: 12 }}>sesión activa — cierra para lanzar otra</div>}
      {idle && (
        <>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 8 }}>
            {coins.map((c) => (
              <button key={c.name} onClick={() => toggle(c.name)}
                style={{ padding: "4px 8px", border: "1px solid #1c1f26", borderRadius: 6,
                  background: f.watchlist.includes(c.name) ? "var(--neon-green)" : "transparent",
                  color: f.watchlist.includes(c.name) ? "#000" : "var(--text)", cursor: "pointer", fontSize: 12 }}>
                {c.name}
              </button>
            ))}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6, fontSize: 12 }}>
            <label>capital <input type="number" defaultValue={f.capital} onChange={num("capital")} style={inputS} /></label>
            <label>grid_n <input type="number" defaultValue={f.gridN} onChange={num("gridN")} style={inputS} /></label>
            <label>max pos $ <input type="number" defaultValue={f.maxPositionNotional} onChange={num("maxPositionNotional")} style={inputS} /></label>
            <label>max abiertas <input type="number" defaultValue={f.maxOpenPositions} onChange={num("maxOpenPositions")} style={inputS} /></label>
            <label>max lev <input type="number" defaultValue={f.maxLeverage} onChange={num("maxLeverage")} style={inputS} /></label>
            <label>adx umbral <input type="number" defaultValue={f.adxThreshold} onChange={num("adxThreshold")} style={inputS} /></label>
            <label>pérdida diaria <input type="number" defaultValue={f.dailyLossLimit} onChange={num("dailyLossLimit")} style={inputS} /></label>
            <label>pérdida total <input type="number" defaultValue={f.totalLossLimit} onChange={num("totalLossLimit")} style={inputS} /></label>
          </div>
          <button onClick={launch} disabled={busy}
            style={{ marginTop: 10, width: "100%", padding: 10, border: "none", borderRadius: 6,
              background: "var(--neon-green)", color: "#000", fontWeight: 700, cursor: "pointer" }}>
            {busy ? "…" : "▶ LAUNCH"}
          </button>
        </>
      )}
    </div>
  );
}
const inputS: React.CSSProperties = { width: "100%", background: "#0a0b0d", border: "1px solid #1c1f26", color: "var(--text)", borderRadius: 4, padding: "2px 6px", marginTop: 2 };
```

- [ ] **Step 6: `dashboard/components/SessionControls.tsx`** (Close / Kill con confirmación)
```tsx
"use client";
import { useState } from "react";
import { postControl } from "@/lib/control";
import { toast } from "sonner";

export function SessionControls({ state }: { state: string }) {
  const [confirmKill, setConfirmKill] = useState(false);
  const active = state !== "idle";
  async function close() {
    const r = await postControl("close");
    r.ok ? toast("Cerrando sesión (posiciones a término)") : toast.error("Error al cerrar");
  }
  async function kill() {
    const r = await postControl("kill", { confirm: true });
    setConfirmKill(false);
    r.ok ? toast.success("KILL: cerrando todo") : toast.error("Error en kill");
  }
  if (!active) return null;
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <button onClick={close} style={btn("#ffaa00")}>Close</button>
      {!confirmKill
        ? <button onClick={() => setConfirmKill(true)} style={btn("#ff4466")}>Kill</button>
        : <button onClick={kill} style={{ ...btn("#ff4466"), fontWeight: 800 }}>¿Seguro? KILL TODO</button>}
    </div>
  );
}
function btn(color: string): React.CSSProperties {
  return { padding: "6px 12px", border: `1px solid ${color}`, color, background: "transparent", borderRadius: 6, cursor: "pointer", fontSize: 12 };
}
```

- [ ] **Step 7: Montar en `page.tsx`** — añade `<LaunchPanel coins={Object.keys(coins).map(name=>({name}))...}` o desde `/coins`. Más simple: pasar `coins` derivadas. Recomendado: usar la lista de la API `/coins`. Para no introducir fetch aquí, deriva del snapshot: `Object.keys(coins).map(name => ({ name }))` para la watchlist (los pares vigilados) — pero en IDLE el snapshot no trae coins. Por eso: en `page.tsx` haz un `useEffect` que llame `api.getCoins()` una vez y guarde la lista; pásala a LaunchPanel. Coloca `<SessionControls state={snapshot.state}/>` en el HeaderBar o junto al LaunchPanel. Añade `<LaunchPanel coins={coinsList} state={snapshot?.state ?? "idle"} />` en la columna derecha o como panel superior.

- [ ] **Step 8: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): LaunchPanel + SessionControls (control vía proxy) + buildLaunchBody"
```

---

### Task 2: Toasts + sonido en aperturas/cierres

**Files:** Create: `dashboard/lib/diff.ts`, `dashboard/lib/__tests__/diff.test.ts`, `dashboard/lib/sound.ts`, `dashboard/hooks/useEventFeedback.ts`. Modify: `dashboard/app/layout.tsx` (`<Toaster/>` de sonner), `dashboard/app/page.tsx` (usar el hook). Instalar `sonner`.

**Interfaces:**
- Produces: `diffPositions(prev: Position[], next: Position[]): {opened: string[]; closed: string[]}` (puro); `playBeep(freq?: number)` (WebAudio); `useEventFeedback(snapshot)` (dispara toast+beep en transiciones).

- [ ] **Step 1: Instalar sonner** — `cd dashboard && npm install sonner`.

- [ ] **Step 2: Test que falla** `dashboard/lib/__tests__/diff.test.ts`
```ts
import { describe, it, expect } from "vitest";
import { diffPositions } from "../diff";
import type { Position } from "../types";
const p = (coin: string): Position => ({ coin, side: "long", leverage: 2, notional: 10, size: 1, entry_px: 1, mark_px: null, unrealized_pnl: 0, liq_px: null });

describe("diffPositions", () => {
  it("detects opened and closed by coin", () => {
    const r = diffPositions([p("ETH"), p("BTC")], [p("BTC"), p("SOL")]);
    expect(r.opened).toEqual(["SOL"]);
    expect(r.closed).toEqual(["ETH"]);
  });
  it("no change", () => {
    expect(diffPositions([p("ETH")], [p("ETH")])).toEqual({ opened: [], closed: [] });
  });
});
```

- [ ] **Step 3: Verificar fallo** — `npm test -- diff` → FAIL.

- [ ] **Step 4: Implementar `dashboard/lib/diff.ts`**
```ts
import type { Position } from "./types";
export function diffPositions(prev: Position[], next: Position[]): { opened: string[]; closed: string[] } {
  const a = new Set(prev.map((p) => p.coin));
  const b = new Set(next.map((p) => p.coin));
  return {
    opened: next.filter((p) => !a.has(p.coin)).map((p) => p.coin),
    closed: prev.filter((p) => !b.has(p.coin)).map((p) => p.coin),
  };
}
```

- [ ] **Step 5: Verificar PASS** — `npm test -- diff` → PASS.

- [ ] **Step 6: `dashboard/lib/sound.ts`** (beep WebAudio, sin assets; no-op en SSR)
```ts
export function playBeep(freq = 660, ms = 120): void {
  if (typeof window === "undefined") return;
  try {
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.frequency.value = freq;
    osc.type = "sine";
    gain.gain.value = 0.05;
    osc.connect(gain); gain.connect(ctx.destination);
    osc.start();
    setTimeout(() => { osc.stop(); ctx.close(); }, ms);
  } catch { /* audio no disponible */ }
}
```

- [ ] **Step 7: `dashboard/hooks/useEventFeedback.ts`**
```ts
"use client";
import { useEffect, useRef } from "react";
import { toast } from "sonner";
import type { Snapshot } from "@/lib/types";
import { diffPositions } from "@/lib/diff";
import { playBeep } from "@/lib/sound";

export function useEventFeedback(snapshot: Snapshot | null): void {
  const prev = useRef<Snapshot["positions"]>([]);
  useEffect(() => {
    if (!snapshot) return;
    const { opened, closed } = diffPositions(prev.current, snapshot.positions);
    opened.forEach((c) => { toast.success(`▲ OPEN ${c}`); playBeep(720); });
    closed.forEach((c) => { toast(`▼ CLOSE ${c}`); playBeep(420); });
    prev.current = snapshot.positions;
  }, [snapshot]);
}
```

- [ ] **Step 8: `<Toaster/>` en `app/layout.tsx`** — importar `{ Toaster } from "sonner"` y renderizar `<Toaster theme="dark" position="bottom-right" />` dentro del `<body>`. Usar `useEventFeedback(snapshot)` en `page.tsx`.

- [ ] **Step 9: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): toasts + beep en aperturas/cierres (diffPositions + sonner)"
```

---

### Task 3: Charts en vivo (series.update por tick)

**Files:** Modify: `dashboard/components/EquityCurve.tsx`, `dashboard/components/FocusChart.tsx`, `dashboard/app/page.tsx`.

**Interfaces:**
- `EquityCurve` recibe `equity: number` (además de `sessionId`) y hace `series.update({time: nowSec, value: equity})` cuando cambia. `FocusChart` recibe `mid: number | null` y actualiza la última vela (cierre) por tick.

- [ ] **Step 1: EquityCurve live point** — añade prop `equity: number`. Tras el fetch inicial, en un `useEffect([equity])` (con la `series` en ref), si `equity>0` hace `series.update({ time: Math.floor(Date.now()/1000) as never, value: equity })`. Guarda la `series` en un ref para poder actualizarla fuera del effect de creación.
```tsx
// añadir a EquityCurve: const seriesRef = useRef<ISeriesApi<"Area"> | null>(null) y asignarlo al crear.
// nuevo effect:
useEffect(() => {
  const s = seriesRef.current;
  if (s && equity > 0) s.update({ time: Math.floor(Date.now() / 1000) as never, value: equity });
}, [equity]);
```
(Importa `ISeriesApi` de lightweight-charts; mantén el fetch inicial por sessionId.)

- [ ] **Step 2: FocusChart live candle** — añade prop `mid: number | null`. Mantén un `lastRef` con la última vela. En un `useEffect([mid])`, si hay `mid` y `series`, actualiza la vela en formación: si el minuto actual coincide con `lastRef.current.time`, actualiza `close`/`high`/`low`; si no, crea una nueva vela con o=h=l=c=mid. Usa `series.update(candle)`.
```tsx
// const lastRef = useRef<{time:number;open:number;high:number;low:number;close:number} | null>(null);
useEffect(() => {
  const s = seriesRef.current;
  if (!s || mid == null) return;
  const t = Math.floor(Date.now() / 60000) * 60; // bucket de 1 min en segundos
  const last = lastRef.current;
  const c = (last && last.time === t)
    ? { time: t, open: last.open, high: Math.max(last.high, mid), low: Math.min(last.low, mid), close: mid }
    : { time: t, open: mid, high: mid, low: mid, close: mid };
  lastRef.current = c;
  s.update(c as never);
}, [mid]);
```
(Al cargar las velas iniciales por `coin`, setea `lastRef.current` a la última vela cargada.)

- [ ] **Step 3: Wire en `page.tsx`** — pasa `equity={snapshot.account.equity}` a EquityCurve y `mid={displayedCoin ? coins[displayedCoin]?.mid ?? null : null}` a FocusChart.

- [ ] **Step 4: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): charts en vivo (equity point + vela en formación via series.update)"
```

---

### Task 4: Animaciones (NumberTicker + pulsos/glow)

**Files:** Create: `dashboard/components/NumberTicker.tsx`. Modify: `dashboard/app/globals.css` (keyframes), `dashboard/components/EquityHero.tsx` y `StatTiles.tsx` (usar NumberTicker), `HeaderBar.tsx` (LIVE pulse), `Watchlist.tsx` (ARMED glow anim).

**Interfaces:**
- Produces: `<NumberTicker value={number} format={(n)=>string} />` (count-up rAF, sin deps).

- [ ] **Step 1: `dashboard/components/NumberTicker.tsx`** (tween con requestAnimationFrame)
```tsx
"use client";
import { useEffect, useRef, useState } from "react";

export function NumberTicker({ value, format, ms = 400 }: { value: number; format: (n: number) => string; ms?: number }) {
  const [display, setDisplay] = useState(value);
  const fromRef = useRef(value);
  useEffect(() => {
    const from = fromRef.current, to = value, start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / ms);
      setDisplay(from + (to - from) * p);
      if (p < 1) raf = requestAnimationFrame(tick); else fromRef.current = to;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, ms]);
  return <span>{format(display)}</span>;
}
```

- [ ] **Step 2: Keyframes en `globals.css`**
```css
@keyframes livePulse { 0%,100% { opacity: 1; } 50% { opacity: 0.35; } }
@keyframes armedGlow { 0%,100% { text-shadow: 0 0 4px currentColor; } 50% { text-shadow: 0 0 12px currentColor; } }
.live-pulse { animation: livePulse 1.6s ease-in-out infinite; }
.armed-glow { animation: armedGlow 1.2s ease-in-out infinite; }
```

- [ ] **Step 3: Usar NumberTicker** — en `EquityHero` envuelve equity y session P&L con `<NumberTicker value={...} format={(n)=>fmtUsd(n)} />`; en `StatTiles` envuelve REALIZED/FEES/FUNDING. En `HeaderBar`, añade `className="live-pulse"` al `● LIVE` cuando connected. En `Watchlist`, añade `className="armed-glow"` al badge ARMED.

- [ ] **Step 4: Build + lint + commit**
```bash
cd dashboard && npm run build && npm run lint && npm test
git add dashboard
git commit -m "feat(web): NumberTicker + pulsos LIVE/ARMED + tickers en equity/stats"
```

---

## Notas para el ejecutor
- `series.update()` con `time` como número (epoch segundos) requiere el mismo cast `as never` ya usado en setData (v5 acepta timestamps numéricos). Mantén el build verde.
- `playBeep` y el AudioContext requieren un gesto del usuario en algunos navegadores; si el primer beep no suena hasta interactuar, es esperado (no romper).
- Verificación visual real la hace el usuario; deja `npm run dev` operativo. Siguiente slice: **2b.4 (past sessions)**.
