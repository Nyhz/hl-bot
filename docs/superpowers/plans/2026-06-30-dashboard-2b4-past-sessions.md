# Dashboard 2b.4 — Past Sessions: Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Añadir la vista "Past Sessions": un track record global por modo (testnet/mainnet separados), una lista de sesiones filtrable por modo, y el detalle de cada sesión (resumen, curva de equity, trades, decisiones), en una ruta `/sessions` navegable desde el terminal en vivo.

**Architecture:** Nueva ruta App Router `app/sessions/page.tsx` (cliente) que consume `api.getStatsGlobal/getSessions/getSession`. Componentes presentacionales (`GlobalStats`, `SessionsList`, `SessionDetail`). Reusa `EquityCurve` (ya acepta `sessionId`) para la curva del detalle. Helper puro `fmtDuration`. Navegación LIVE/HISTORY en el header.

**Tech Stack:** Next.js App Router + TS + Tailwind v4, lightweight-charts (reuse), Vitest.

## Global Constraints

- Track record SEPARADO testnet vs mainnet (nunca mezclar) — `/stats/global` ya devuelve `{testnet:{...}, mainnet:{...}}`.
- Gotcha: `net_pnl` (de session_summary y global) es el PnL neto (delta de equity); `realized_pnl` es PnL realizado de trades; la curva (`equity_curve`/`/equity_curve`) es EQUITY absoluta. Mostrar net_pnl como resultado de sesión.
- Frontend puro (solo `api.*`). Estética neón existente (verde/rojo/ámbar/muted, mono).
- Cada tarea: `npm run build` + `npm run lint` limpios + Vitest verde donde haya helper. Trabajar en `dashboard/`.

**Estructura (2b.4):**
```
dashboard/lib/view.ts            # + fmtDuration (append)
dashboard/lib/__tests__/view.test.ts  # + test
dashboard/lib/types.ts           # + SessionDetail
dashboard/lib/api.ts             # tipar getSession -> SessionDetail
dashboard/app/sessions/page.tsx  # ruta Past Sessions
dashboard/components/GlobalStats.tsx, SessionsList.tsx, SessionDetail.tsx
dashboard/components/HeaderBar.tsx  # + nav LIVE/HISTORY
```

---

### Task 1: Nav + ruta /sessions + GlobalStats + fmtDuration

**Files:** Modify: `dashboard/lib/view.ts`, `dashboard/lib/__tests__/view.test.ts`, `dashboard/lib/types.ts`, `dashboard/lib/api.ts`, `dashboard/components/HeaderBar.tsx`. Create: `dashboard/app/sessions/page.tsx`, `dashboard/components/GlobalStats.tsx`.

**Interfaces:**
- Produces: `fmtDuration(sec: number | null): string` ("1h 02m" / "5m" / "—"); `SessionDetail` type; `<GlobalStats stats/>`; ruta `/sessions` que carga `getStatsGlobal()` + monta GlobalStats; HeaderBar con enlaces LIVE (`/`) y HISTORY (`/sessions`).

- [ ] **Step 1: Test que falla** (añadir a `dashboard/lib/__tests__/view.test.ts`)
```ts
import { fmtDuration } from "../view";
describe("fmtDuration", () => {
  it("formats", () => {
    expect(fmtDuration(null)).toBe("—");
    expect(fmtDuration(300)).toBe("5m");
    expect(fmtDuration(3725)).toBe("1h 02m");
  });
});
```

- [ ] **Step 2: Verificar fallo** — `cd dashboard && npm test -- view` → FAIL.

- [ ] **Step 3: Implementar `fmtDuration` en `view.ts`**
```ts
export function fmtDuration(sec: number | null): string {
  if (sec === null || sec === undefined || Number.isNaN(sec) || sec < 0) return "—";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return h > 0 ? `${h}h ${String(m).padStart(2, "0")}m` : `${m}m`;
}
```

- [ ] **Step 4: Verificar PASS** — `npm test -- view` → PASS.

- [ ] **Step 5: Tipar `SessionDetail`** — en `dashboard/lib/types.ts` añade:
```ts
export interface SessionDetail {
  summary: SessionSummary;
  trades: { coin: string; side: string; dir: string; price: number; size: number; fee: number; closed_pnl: number; ts: number }[];
  equity_curve: { ts: number; total_pnl: number }[];
  decisions: { ts: number; coin: string; action: string; reason: string }[];
}
```
Y en `dashboard/lib/api.ts` cambia `getSession` a `getSession: (id: number) => get<SessionDetail>(`/sessions/${id}`)` e importa `SessionDetail`.

- [ ] **Step 6: `dashboard/components/GlobalStats.tsx`**
```tsx
import type { GlobalStats as GS } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor } from "@/lib/view";

function ModeCol({ title, color, m }: { title: string; color: string; m: GS["testnet"] }) {
  const rows: [string, string, string?][] = [
    ["sesiones", String(m.n_sessions)],
    ["net PnL", fmtUsd(m.net_pnl), pnlColor(m.net_pnl)],
    ["realizado", fmtUsd(m.realized_pnl), pnlColor(m.realized_pnl)],
    ["fees", fmtUsd(m.fees, 3)],
    ["funding", fmtUsd(m.funding, 3)],
    ["win rate", fmtPct(m.win_rate)],
  ];
  return (
    <div className="panel" style={{ padding: 12, flex: 1 }}>
      <div className="glow" style={{ color, fontWeight: 700, marginBottom: 8 }}>{title}</div>
      {rows.map(([label, value, c]) => (
        <div key={label} style={{ display: "flex", justifyContent: "space-between", fontSize: 13, padding: "3px 0" }}>
          <span className="muted">{label}</span>
          <span style={{ color: c ?? "var(--text)" }}>{value}</span>
        </div>
      ))}
    </div>
  );
}
export function GlobalStats({ stats }: { stats: GS }) {
  return (
    <div style={{ display: "flex", gap: 12 }}>
      <ModeCol title="TESTNET" color="var(--neon-amber)" m={stats.testnet} />
      <ModeCol title="MAINNET" color="var(--neon-green)" m={stats.mainnet} />
    </div>
  );
}
```

- [ ] **Step 7: Nav en `HeaderBar.tsx`** — añade dos enlaces (usa `next/link` o `<a>`): `LIVE` → `/`, `HISTORY` → `/sessions`, con estilo muted/neón. Colócalos al inicio del header (tras el título).
```tsx
import Link from "next/link";
// dentro del header, tras el título:
<Link href="/" style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12 }}>LIVE</Link>
<Link href="/sessions" style={{ color: "var(--muted)", textDecoration: "none", fontSize: 12 }}>HISTORY</Link>
```

- [ ] **Step 8: Ruta `dashboard/app/sessions/page.tsx`** (carga global stats; lista y detalle vienen en Tasks 2-3)
```tsx
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
```

- [ ] **Step 9: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): ruta /sessions + GlobalStats por modo + fmtDuration + nav"
```

---

### Task 2: SessionsList (filtro por modo)

**Files:** Create: `dashboard/components/SessionsList.tsx`. Modify: `dashboard/app/sessions/page.tsx` (montar la lista + estado de filtro y de sesión seleccionada).

**Interfaces:**
- Produces: `<SessionsList sessions, onSelect, selectedId/>` (filas de resumen; clic → onSelect(id)).

- [ ] **Step 1: `dashboard/components/SessionsList.tsx`**
```tsx
import type { SessionSummary } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor, fmtDuration } from "@/lib/view";

export function SessionsList({ sessions, onSelect, selectedId }: {
  sessions: SessionSummary[]; onSelect: (id: number) => void; selectedId: number | null;
}) {
  return (
    <div className="panel" style={{ padding: 12 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 8 }}>SESIONES</div>
      {sessions.length === 0 && <div className="muted" style={{ fontSize: 12 }}>sin sesiones</div>}
      {sessions.map((s) => (
        <div key={s.id} onClick={() => onSelect(s.id)}
          style={{ display: "grid", gridTemplateColumns: "40px 80px 1fr 1fr 1fr 1fr", gap: 8, alignItems: "center",
            padding: "8px 4px", borderBottom: "1px solid #1c1f26", cursor: "pointer",
            background: s.id === selectedId ? "#14171c" : "transparent", fontSize: 12 }}>
          <span className="muted">#{s.id}</span>
          <span style={{ color: s.mode === "mainnet" ? "var(--neon-green)" : "var(--neon-amber)" }}>{s.mode}</span>
          <span style={{ color: pnlColor(s.net_pnl) }}>{fmtUsd(s.net_pnl)}</span>
          <span className="muted">{s.n_trades} trades</span>
          <span className="muted">{fmtPct(s.win_rate)}</span>
          <span className="muted">{fmtDuration(s.duration_s)}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Montar lista + filtro en `app/sessions/page.tsx`**
Añade estado `mode` ("all"|"testnet"|"mainnet"), `sessions`, `selectedId`. `useEffect` que recarga `api.getSessions(mode === "all" ? undefined : mode)` cuando cambia `mode`. Botones de filtro (all/testnet/mainnet). Render `<SessionsList sessions onSelect={setSelectedId} selectedId={selectedId} />`. Ej. del filtro:
```tsx
const [mode, setMode] = useState<"all" | "testnet" | "mainnet">("all");
const [sessions, setSessions] = useState<SessionSummary[]>([]);
const [selectedId, setSelectedId] = useState<number | null>(null);
useEffect(() => { api.getSessions(mode === "all" ? undefined : mode).then(setSessions).catch(() => {}); }, [mode]);
// ...filtro:
<div style={{ display: "flex", gap: 6 }}>
  {(["all","testnet","mainnet"] as const).map((m) => (
    <button key={m} onClick={() => setMode(m)}
      style={{ padding: "4px 10px", borderRadius: 6, border: "1px solid #1c1f26", cursor: "pointer", fontSize: 12,
        background: mode === m ? "var(--neon-green)" : "transparent", color: mode === m ? "#000" : "var(--text)" }}>{m}</button>
  ))}
</div>
```
(importa `SessionSummary` y `SessionsList`.)

- [ ] **Step 3: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): SessionsList con filtro por modo"
```

---

### Task 3: SessionDetail (resumen + curva + trades + decisiones)

**Files:** Create: `dashboard/components/SessionDetail.tsx`. Modify: `dashboard/app/sessions/page.tsx` (render del detalle al seleccionar).

**Interfaces:**
- Produces: `<SessionDetail sessionId/>` que hace `getSession(id)` y muestra resumen, `EquityCurve` (reuse, por sessionId), tabla de trades, lista de decisiones.

- [ ] **Step 1: `dashboard/components/SessionDetail.tsx`**
```tsx
"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SessionDetail as SD } from "@/lib/types";
import { fmtUsd, fmtPct } from "@/lib/format";
import { pnlColor, fmtDuration } from "@/lib/view";
import { EquityCurve } from "./EquityCurve";

export function SessionDetail({ sessionId }: { sessionId: number }) {
  const [d, setD] = useState<SD | null>(null);
  useEffect(() => {
    let cancelled = false;
    api.getSession(sessionId).then((r) => { if (!cancelled) setD(r); }).catch(() => {});
    return () => { cancelled = true; };
  }, [sessionId]);
  if (!d) return <div className="panel muted" style={{ padding: 12 }}>cargando…</div>;
  const s = d.summary;
  return (
    <div className="panel" style={{ padding: 12, display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 16, alignItems: "baseline" }}>
        <span style={{ fontWeight: 700 }}>Sesión #{s.id}</span>
        <span style={{ color: s.mode === "mainnet" ? "var(--neon-green)" : "var(--neon-amber)" }}>{s.mode}</span>
        <span style={{ color: pnlColor(s.net_pnl), fontWeight: 700 }}>{fmtUsd(s.net_pnl)}</span>
        <span className="muted">realizado {fmtUsd(s.realized_pnl)} · fees {fmtUsd(s.fees, 3)} · funding {fmtUsd(s.funding, 3)}</span>
        <span className="muted">{s.n_trades} trades · {fmtPct(s.win_rate)} · {fmtDuration(s.duration_s)}</span>
      </div>
      <EquityCurve sessionId={s.id} equity={0} />
      <div>
        <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>TRADES</div>
        {d.trades.length === 0 && <div className="muted" style={{ fontSize: 12 }}>sin trades</div>}
        {d.trades.map((t, i) => (
          <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, padding: "2px 0" }}>
            <span className="muted">{new Date(t.ts * 1000).toLocaleTimeString()}</span>
            <span style={{ width: 90 }}>{t.dir}</span>
            <span>{t.coin}</span>
            <span className="muted">@{t.price}</span>
            <span style={{ color: pnlColor(t.closed_pnl), marginLeft: "auto" }}>{fmtUsd(t.closed_pnl)}</span>
          </div>
        ))}
      </div>
      <div>
        <div className="muted" style={{ fontSize: 11, marginBottom: 4 }}>DECISIONES</div>
        {d.decisions.slice(-30).map((dec, i) => (
          <div key={i} style={{ display: "flex", gap: 10, fontSize: 12, padding: "2px 0" }}>
            <span className="muted">{new Date(dec.ts * 1000).toLocaleTimeString()}</span>
            <span style={{ width: 90 }}>{dec.action}</span>
            <span>{dec.coin}</span>
            <span className="muted" style={{ fontStyle: "italic", marginLeft: "auto" }}>{dec.reason}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
```
> NOTA: `EquityCurve` requiere la prop `equity` (de 2b.3). Aquí pasamos `equity={0}` para no añadir un punto vivo (el guard `equity>0` evita el append); la curva muestra sólo el histórico de la sesión.

- [ ] **Step 2: Render del detalle en `app/sessions/page.tsx`** — cuando `selectedId !== null`, render `<SessionDetail sessionId={selectedId} />` (p. ej. en una columna o debajo de la lista).

- [ ] **Step 3: Build + lint + commit**
```bash
cd dashboard && npm test && npm run build && npm run lint
git add dashboard
git commit -m "feat(web): SessionDetail (resumen + curva + trades + decisiones)"
```

---

## Notas para el ejecutor
- `EquityCurve` se reutiliza con `equity={0}` para que NO haga append vivo (sólo histórico de la sesión por `sessionId`). Si prefieres, pasa la última equity conocida; pero 0 es seguro (el guard la ignora).
- La curva de la sesión es EQUITY absoluta (no PnL) — el header del detalle muestra `net_pnl` como resultado, que es lo correcto.
- Verificación visual la hace el usuario; deja `npm run dev`. Con el bot en testnet y alguna sesión grabada, `/sessions` mostrará el track record y el detalle.
- Esta es la última slice de 2b: al mergear, el dashboard completo (terminal en vivo + control + past sessions) está en `master`.
