"use client";
import { useEffect, useRef, useState } from "react";
import type { Snapshot } from "./types";
import { normalizeSnapshot } from "./snapshot";

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
      ws.onopen = () => { if (!closed) setConnected(true); };
      ws.onmessage = (e) => {
        try { if (!closed) setSnapshot(normalizeSnapshot(JSON.parse(e.data))); } catch {}
      };
      ws.onclose = () => {
        if (!closed) setConnected(false);
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
