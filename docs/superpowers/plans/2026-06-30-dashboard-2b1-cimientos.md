# Dashboard 2b.1 — Cimientos + capa de datos: Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Scaffold del frontend Next.js (tema dark/neón monoespaciado), capa de datos (tipos, cliente REST, hook WebSocket, proxy de control con token) y una página mínima que muestre estado + modo + `● LIVE` + EQUITY en vivo desde la API del bot en `:3300`.

**Architecture:** Next.js App Router + TS + Tailwind en `dashboard/`. Tema neón vía CSS variables en `globals.css` (robusto a la versión de Tailwind). `lib/` contiene tipos, cliente REST y el hook de WebSocket; el control pasa por route handlers server-side que inyectan el `CONTROL_TOKEN`. Vitest para lógica pura.

**Tech Stack:** Next.js (latest), React, TypeScript, Tailwind, Vitest. Backend ya existente en `:3300`.

## Global Constraints

- Frontend PURO: solo habla con la API del bot (REST `NEXT_PUBLIC_BOT_HTTP`, WS `NEXT_PUBLIC_BOT_WS`). El token de control vive SOLO en el servidor de Next.js (`CONTROL_TOKEN`), nunca en el cliente.
- Estética: dark, monoespaciada, paleta neón (verde `#00ff88`, rojo `#ff4466`, ámbar `#ffaa00`, muted `#8a8f98`).
- Modo: `snapshot.mode` = testnet→naranja(`#ffaa00`) / mainnet→verde(`#00ff88`).
- Gotcha: `account.equity` es el valor de cuenta; mostrar como EQUITY. (PnL neto y curva se tratan en slices posteriores.)
- Cada tarea: `npm run build` (typecheck) y `npm run lint` limpios + Vitest verde donde aplique.
- Trabajar dentro de `dashboard/` (se crea en Task 1). `.env.local` va en `.gitignore`.

**Estructura de ficheros (2b.1):**
```
dashboard/                      # scaffold create-next-app
├── .env.local / .env.example   # NEXT_PUBLIC_BOT_HTTP/WS, BOT_API_URL, CONTROL_TOKEN
├── app/globals.css             # tema neón (CSS vars + base)
├── app/page.tsx                # página mínima en vivo
├── lib/types.ts                # tipos del snapshot/API
├── lib/api.ts                  # cliente REST
├── lib/useLiveSnapshot.ts      # hook WebSocket
├── lib/format.ts               # formateadores puros (usd, pct)
├── lib/__tests__/*.test.ts     # vitest
├── app/api/control/[action]/route.ts  # proxy de control (token server-side)
├── vitest.config.ts
└── package.json / tsconfig / next.config
```

---

### Task 1: Scaffold + tema + tooling

**Files:** Create: `dashboard/` (scaffold), `dashboard/app/globals.css` (tema), `dashboard/vitest.config.ts`, `dashboard/lib/format.ts`, `dashboard/lib/__tests__/format.test.ts`, `dashboard/.env.example`.

**Interfaces:**
- Produces: proyecto Next.js que compila; `lib/format.ts` con `fmtUsd(n: number, dp?: number): string` y `fmtPct(n: number): string` (puras); script `npm test` (vitest).

- [ ] **Step 1: Scaffold Next.js** (desde la raíz del repo)
```bash
npx --yes create-next-app@latest dashboard --ts --tailwind --app --no-src-dir --eslint --import-alias "@/*" --use-npm
```
Expected: crea `dashboard/` con app router, TS, Tailwind, ESLint.

- [ ] **Step 2: Añadir Vitest** (en `dashboard/`)
```bash
cd dashboard && npm install -D vitest
```
Crea `dashboard/vitest.config.ts`:
```ts
import { defineConfig } from "vitest/config";
export default defineConfig({ test: { environment: "node" } });
```
Añade a `dashboard/package.json` scripts: `"test": "vitest run"`.

- [ ] **Step 3: Escribir el test que falla** `dashboard/lib/__tests__/format.test.ts`
```ts
import { describe, it, expect } from "vitest";
import { fmtUsd, fmtPct } from "../format";

describe("format", () => {
  it("fmtUsd", () => {
    expect(fmtUsd(49.16)).toBe("$49.16");
    expect(fmtUsd(-0.84)).toBe("-$0.84");
    expect(fmtUsd(0.049, 3)).toBe("$0.049");
  });
  it("fmtPct", () => {
    expect(fmtPct(-0.0169)).toBe("-1.69%");
    expect(fmtPct(0.67)).toBe("+67.00%");
  });
});
```

- [ ] **Step 4: Ejecutar y verificar que falla**
Run: `cd dashboard && npm test`
Expected: FAIL (no module `../format`)

- [ ] **Step 5: Implementar `dashboard/lib/format.ts`**
```ts
export function fmtUsd(n: number, dp = 2): string {
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toFixed(dp)}`;
}

export function fmtPct(n: number): string {
  const v = n * 100;
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}
```

- [ ] **Step 6: Implementar el tema** — reemplaza `dashboard/app/globals.css` añadiendo al inicio (tras las directivas de Tailwind que genere el scaffold) las variables y base:
```css
:root {
  --bg: #0a0b0d;
  --panel: #111317;
  --neon-green: #00ff88;
  --neon-red: #ff4466;
  --neon-amber: #ffaa00;
  --muted: #8a8f98;
  --text: #e6e8eb;
}
html, body {
  background: var(--bg);
  color: var(--text);
  font-family: ui-monospace, "JetBrains Mono", "SF Mono", Menlo, monospace;
  letter-spacing: 0.02em;
}
.neon-green { color: var(--neon-green); }
.neon-red { color: var(--neon-red); }
.neon-amber { color: var(--neon-amber); }
.muted { color: var(--muted); }
.panel { background: var(--panel); border: 1px solid #1c1f26; border-radius: 8px; }
.glow { text-shadow: 0 0 8px currentColor; }
```

- [ ] **Step 7: `.env.example`** (`dashboard/.env.example`)
```bash
NEXT_PUBLIC_BOT_HTTP=http://localhost:3300
NEXT_PUBLIC_BOT_WS=ws://localhost:3300/ws
BOT_API_URL=http://localhost:3300
CONTROL_TOKEN=cambia-esto
```
(Confirma que `.gitignore` del scaffold ignora `.env*`; si no, añádelo.)

- [ ] **Step 8: Verificar build + lint + test**
Run: `cd dashboard && npm test && npm run build && npm run lint`
Expected: tests PASS; build OK (typecheck); lint limpio.

- [ ] **Step 9: Commit**
```bash
git add dashboard
git commit -m "feat(web): scaffold Next.js + tema neon + vitest + format"
```

---

### Task 2: Tipos + cliente REST

**Files:** Create: `dashboard/lib/types.ts`, `dashboard/lib/api.ts`, `dashboard/lib/__tests__/api.test.ts`.

**Interfaces:**
- Consumes: nada (usa `fetch`).
- Produces: tipos `Snapshot`, `Account`, `Position`, `Condition`, `Trigger`, `Candle`, `TapeEvent`, `SessionSummary`, `GlobalStats`; cliente `api` con `getCandles(coin)`, `getEquityCurve(sessionId)`, `getCoins()`, `getTape(limit?)`, `getSessions(mode?)`, `getSession(id)`, `getStatsGlobal()` (todas devuelven Promesas tipadas; base `NEXT_PUBLIC_BOT_HTTP`).

- [ ] **Step 1: Escribir el test que falla** `dashboard/lib/__tests__/api.test.ts`
```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import { api } from "../api";

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => ({
    ok: true, json: async () => ({ url }),
  })) as any);
  vi.stubEnv("NEXT_PUBLIC_BOT_HTTP", "http://localhost:3300");
});

describe("api", () => {
  it("getCandles builds the right URL", async () => {
    await api.getCandles("ETH");
    expect((fetch as any).mock.calls[0][0]).toBe("http://localhost:3300/candles/ETH?interval=1m");
  });
  it("getSessions passes mode", async () => {
    await api.getSessions("testnet");
    expect((fetch as any).mock.calls[0][0]).toBe("http://localhost:3300/sessions?mode=testnet");
  });
  it("getStatsGlobal", async () => {
    await api.getStatsGlobal();
    expect((fetch as any).mock.calls[0][0]).toBe("http://localhost:3300/stats/global");
  });
});
```

- [ ] **Step 2: Ejecutar y verificar que falla**
Run: `cd dashboard && npm test -- api`
Expected: FAIL (no module `../api`)

- [ ] **Step 3: Implementar `dashboard/lib/types.ts`**
```ts
export type Mode = "testnet" | "mainnet";
export type SessionState = "idle" | "scanning" | "active" | "closing";

export interface Condition { name: string; value: number; threshold: number; met: boolean; }
export interface Trigger { coin: string; level: number; side: string; action: string; description: string; }
export interface CoinView {
  mid: number; mode: "grid" | "trend";
  triggers: Trigger[]; conditions: Condition[]; armed: boolean;
}
export interface Position {
  coin: string; side: string; leverage: number | null; notional: number;
  size: number; entry_px: number; mark_px: number | null;
  unrealized_pnl: number; liq_px: number | null;
}
export interface Account {
  equity: number; session_pnl: number; realized_pnl: number; unrealized_pnl: number;
  win_rate: number; fees_paid: number; funding: number; open_count: number; max_open: number;
}
export interface TapeEvent {
  ts: number; kind: "open" | "close" | "decision"; coin: string | null;
  side: string | null; price: number | null; pnl: number | null; reason: string;
}
export interface Snapshot {
  state: SessionState; paused: boolean; mode: Mode;
  session_id: number | null; session_started_at: number | null;
  watchlist: string[]; coins: Record<string, CoinView>;
  account: Account; positions: Position[]; tape_recent: TapeEvent[];
}
export interface Candle { time: number; open: number; high: number; low: number; close: number; }
export interface SessionSummary {
  id: number; mode: Mode; started_at: number | null; ended_at: number | null;
  duration_s: number | null; capital: number; n_trades: number; wins: number;
  realized_pnl: number; fees: number; funding: number; win_rate: number; net_pnl: number;
}
export interface GlobalStatsMode {
  n_sessions: number; realized_pnl: number; fees: number; funding: number;
  net_pnl: number; win_rate: number; best_session: number | null; worst_session: number | null;
}
export interface GlobalStats { testnet: GlobalStatsMode; mainnet: GlobalStatsMode; }
```

- [ ] **Step 4: Implementar `dashboard/lib/api.ts`**
```ts
import type { Candle, SessionSummary, GlobalStats, TapeEvent } from "./types";

const BASE = () => process.env.NEXT_PUBLIC_BOT_HTTP ?? "http://localhost:3300";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE()}${path}`);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return res.json() as Promise<T>;
}

export const api = {
  getCandles: (coin: string, interval = "1m") =>
    get<Candle[]>(`/candles/${coin}?interval=${interval}`),
  getEquityCurve: (sessionId: number) =>
    get<{ ts: number; total_pnl: number }[]>(`/equity_curve?session_id=${sessionId}`),
  getCoins: () => get<{ name: string; szDecimals: number }[]>(`/coins`),
  getTape: (limit = 50) => get<TapeEvent[]>(`/tape?limit=${limit}`),
  getSessions: (mode?: string) =>
    get<SessionSummary[]>(`/sessions${mode ? `?mode=${mode}` : ""}`),
  getSession: (id: number) => get<any>(`/sessions/${id}`),
  getStatsGlobal: () => get<GlobalStats>(`/stats/global`),
};
```

- [ ] **Step 5: Ejecutar y verificar que pasan**
Run: `cd dashboard && npm test`
Expected: PASS

- [ ] **Step 6: Build + commit**
```bash
cd dashboard && npm run build && npm run lint
git add dashboard/lib
git commit -m "feat(web): tipos + cliente REST de la API del bot"
```

---

### Task 3: Hook WebSocket + proxy de control

**Files:** Create: `dashboard/lib/useLiveSnapshot.ts`, `dashboard/lib/ws.ts`, `dashboard/lib/__tests__/ws.test.ts`, `dashboard/app/api/control/[action]/route.ts`.

**Interfaces:**
- Produces: `useLiveSnapshot(): { snapshot: Snapshot | null; connected: boolean }` (hook React que abre el WS y reconecta); helper puro `controlAllowed(action: string): boolean` (whitelist) testeado; route handler POST `/api/control/[action]` que reenvía a `BOT_API_URL` con `X-Control-Token`.

- [ ] **Step 1: Escribir el test que falla** `dashboard/lib/__tests__/ws.test.ts`
```ts
import { describe, it, expect } from "vitest";
import { controlAllowed } from "../ws";

describe("controlAllowed", () => {
  it("permite acciones válidas", () => {
    for (const a of ["launch", "close", "kill", "limits"]) expect(controlAllowed(a)).toBe(true);
  });
  it("rechaza lo demás", () => {
    expect(controlAllowed("../secrets")).toBe(false);
    expect(controlAllowed("drop")).toBe(false);
  });
});
```

- [ ] **Step 2: Ejecutar y verificar que falla**
Run: `cd dashboard && npm test -- ws`
Expected: FAIL (no module `../ws`)

- [ ] **Step 3: Implementar `dashboard/lib/ws.ts`** (helper puro compartido por el proxy)
```ts
const ACTIONS = new Set(["launch", "close", "kill", "limits"]);
export function controlAllowed(action: string): boolean {
  return ACTIONS.has(action);
}
```

- [ ] **Step 4: Implementar `dashboard/lib/useLiveSnapshot.ts`**
```ts
"use client";
import { useEffect, useRef, useState } from "react";
import type { Snapshot } from "./types";

export function useLiveSnapshot(): { snapshot: Snapshot | null; connected: boolean } {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const url = process.env.NEXT_PUBLIC_BOT_WS ?? "ws://localhost:3300/ws";

    const connect = () => {
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => {
        try { setSnapshot(JSON.parse(e.data) as Snapshot); } catch {}
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 2000); // backoff simple
      };
      ws.onerror = () => ws.close();
    };
    connect();

    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      wsRef.current?.close();
    };
  }, []);

  return { snapshot, connected };
}
```

- [ ] **Step 5: Implementar el proxy de control** `dashboard/app/api/control/[action]/route.ts`
```ts
import { NextRequest, NextResponse } from "next/server";
import { controlAllowed } from "@/lib/ws";

export async function POST(req: NextRequest, ctx: { params: Promise<{ action: string }> }) {
  const { action } = await ctx.params;
  if (!controlAllowed(action)) {
    return NextResponse.json({ error: "accion no permitida" }, { status: 400 });
  }
  const base = process.env.BOT_API_URL ?? "http://localhost:3300";
  const token = process.env.CONTROL_TOKEN ?? "";
  const body = await req.text();
  const res = await fetch(`${base}/session/${action === "limits" ? "" : ""}${action}`.replace("/session/limits", "/limits"), {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Control-Token": token },
    body: body || "{}",
  });
  const text = await res.text();
  return new NextResponse(text, { status: res.status, headers: { "Content-Type": "application/json" } });
}
```
> Nota de rutas del bot: `launch`/`close`/`kill` están bajo `/session/<action>`; `limits` está en `/limits`. El `.replace` mapea `limits` a `/limits` y deja el resto como `/session/<action>`.

- [ ] **Step 6: Ejecutar y verificar que pasan**
Run: `cd dashboard && npm test`
Expected: PASS (controlAllowed)

- [ ] **Step 7: Build + commit**
```bash
cd dashboard && npm run build && npm run lint
git add dashboard/lib dashboard/app/api
git commit -m "feat(web): hook useLiveSnapshot (WS) + proxy de control con token"
```

---

### Task 4: Página mínima en vivo

**Files:** Modify: `dashboard/app/page.tsx`.

**Interfaces:**
- Consumes: `useLiveSnapshot`, `fmtUsd`, tipos.
- Produces: una página cliente que muestra estado, modo (color), `● LIVE`/`○` según conexión, y EQUITY.

- [ ] **Step 1: Implementar `dashboard/app/page.tsx`**
```tsx
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
```

- [ ] **Step 2: Build + lint + arranque del dev server (smoke)**
Run: `cd dashboard && npm run build && npm run lint`
Expected: build OK, lint limpio.
Smoke (opcional, no bloqueante): `npm run dev` arranca en `:3000`; con el bot en `:3300`, la página muestra el estado y `● LIVE`. (La verificación visual completa la hace el usuario.)

- [ ] **Step 3: Commit**
```bash
git add dashboard/app/page.tsx
git commit -m "feat(web): pagina minima en vivo (estado/modo/LIVE/equity)"
```

---

## Notas para el ejecutor
- Si `create-next-app` instala Tailwind v4 (config CSS-first), el tema por CSS variables en `globals.css` funciona igual; usa estilos inline/clases propias para el neón y Tailwind para layout.
- `npm run build` hace el typecheck (es el gate principal del frontend); `npm run lint` debe quedar limpio.
- Siguiente slice: **2b.2 (terminal en vivo)** con los paneles y los charts.
