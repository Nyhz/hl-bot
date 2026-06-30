"use client";
import { useState } from "react";
import { postControl } from "@/lib/control";
import { toast } from "sonner";

export function SessionControls({ state }: { state: string }) {
  const [confirmKill, setConfirmKill] = useState(false);
  const active = state !== "idle";
  async function close() {
    const r = await postControl("close");
    if (r.ok) toast("Cerrando sesión (posiciones a término)"); else toast.error("Error al cerrar");
  }
  async function kill() {
    const r = await postControl("kill", { confirm: true });
    setConfirmKill(false);
    if (r.ok) toast.success("KILL: cerrando todo"); else toast.error("Error en kill");
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
