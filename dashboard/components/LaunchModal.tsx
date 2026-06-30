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
