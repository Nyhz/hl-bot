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
