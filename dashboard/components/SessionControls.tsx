"use client";
import { useState } from "react";
import { postControl } from "@/lib/control";
import { toast } from "sonner";

export function SessionControls({ state }: { state: string }) {
  const [confirmKill, setConfirmKill] = useState(false);
  const [busy, setBusy] = useState(false);
  const active = state !== "idle";
  async function close() {
    setBusy(true);
    try {
      const r = await postControl("close");
      if (r.ok) toast("Cerrando sesión (posiciones a término)");
      else toast.error(`Error (${r.status}): ${(r.data as { detail?: string })?.detail ?? ""}`);
    } finally {
      setBusy(false);
    }
  }
  async function kill() {
    setBusy(true);
    try {
      const r = await postControl("kill", { confirm: true });
      setConfirmKill(false);
      if (r.ok) toast.success("KILL: cerrando todo");
      else toast.error(`Error (${r.status}): ${(r.data as { detail?: string })?.detail ?? ""}`);
    } finally {
      setBusy(false);
    }
  }
  if (!active) return null;
  return (
    <div style={{ display: "flex", gap: 8 }}>
      <button onClick={close} disabled={busy} style={btn("#ffaa00")}>Close</button>
      {!confirmKill
        ? <button onClick={() => setConfirmKill(true)} disabled={busy} style={btn("#ff4466")}>Kill</button>
        : <>
            <button onClick={kill} disabled={busy} style={{ ...btn("#ff4466"), fontWeight: 800 }}>¿Seguro? KILL TODO</button>
            <button onClick={() => setConfirmKill(false)} disabled={busy} style={btn("#8a8f98")}>Cancelar</button>
          </>}
    </div>
  );
}
function btn(color: string): React.CSSProperties {
  return { padding: "6px 12px", border: `1px solid ${color}`, color, background: "transparent", borderRadius: 6, cursor: "pointer", fontSize: 12 };
}
