"use client";
import React, { useEffect, useLayoutEffect, useRef } from "react";
import { createChart, CandlestickSeries, TickMarkType, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import type { CoinView, Trigger } from "@/lib/types";
import { api } from "@/lib/api";
import { candleSeries, fmtFunding, fundingColor } from "@/lib/view";

export function FocusChart({ coin, coinView, mid, fill }: { coin: string | null; coinView: CoinView | undefined; mid: number | null; fill?: boolean }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const triggersRef = useRef<Trigger[]>([]);
  const lastRef = useRef<{ time: number; open: number; high: number; low: number; close: number } | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const chart = createChart(el, {
      height: fill ? (el.clientHeight || 240) : 320,
      layout: { background: { color: "transparent" }, textColor: "#8a8f98" },
      grid: { vertLines: { color: "#14171c" }, horzLines: { color: "#14171c" } },
      rightPriceScale: { borderVisible: false },
      // Velas intradía: eje con HH:MM en hora LOCAL (por defecto la librería
      // pinta el día del mes en UTC — "22 22 22" con zoom de horas).
      timeScale: {
        borderVisible: false, timeVisible: true, secondsVisible: false,
        tickMarkFormatter: (t: UTCTimestamp, type: TickMarkType) =>
          type < TickMarkType.Time
            ? new Date(t * 1000).toLocaleDateString([], { day: "2-digit", month: "short" })
            : new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      },
      localization: {
        timeFormatter: (t: UTCTimestamp) =>
          new Date(t * 1000).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }),
      },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#00ff88", downColor: "#ff4466", wickUpColor: "#00ff88", wickDownColor: "#ff4466", borderVisible: false,
    });
    chartRef.current = chart; seriesRef.current = series;
    const fit = () => chart.applyOptions(fill
      ? { width: el.clientWidth, height: el.clientHeight || 240 }
      : { width: el.clientWidth });
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; seriesRef.current = null; };
    // `fill` se espera estático por instancia; cambiarlo en runtime recrearía el chart sin recargar velas.
  }, [fill]);

  // Las velas se recargan al cambiar de par (coin).
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !coin) return;
    let cancelled = false;
    api.getCandles(coin).then((cs) => {
      if (!cancelled) {
        const sorted = candleSeries(cs);
        series.setData(sorted as never);
        lastRef.current = sorted.length > 0 ? (sorted[sorted.length - 1] as { time: number; open: number; high: number; low: number; close: number }) : null;
      }
    }).catch((e) => console.error("getCandles", e));
    return () => { cancelled = true; };
  }, [coin]);

  useEffect(() => {
    const s = seriesRef.current;
    if (!s || mid == null) return;
    const bucket = Math.floor(Date.now() / 60000) * 60; // bucket de 1 min en segundos
    const t = Math.max(bucket, lastRef.current?.time ?? bucket);
    const last = lastRef.current;
    const c = (last && last.time === t)
      ? { time: t, open: last.open, high: Math.max(last.high, mid), low: Math.min(last.low, mid), close: mid }
      : { time: t, open: mid, high: mid, low: mid, close: mid };
    lastRef.current = c;
    s.update(c as never);
  }, [mid]);

  const triggers = coinView?.triggers ?? [];
  const triggerKey = triggers.map((t) => `${t.level}:${t.side}:${t.action}`).join("|");

  // Keep triggersRef current before effects read it (layout effects run before effects)
  useLayoutEffect(() => { triggersRef.current = triggers; });

  // Price lines de triggers — se recrean SOLO cuando cambia el contenido (no en cada tick del snapshot)
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const lines = triggersRef.current.map((t) =>
      series.createPriceLine({
        price: t.level,
        color: t.side === "buy" ? "#00ff88" : "#ff4466",
        lineWidth: 1,
        lineStyle: 2,
        axisLabelVisible: true,
        title: t.action,
      }),
    );
    return () => { lines.forEach((l) => series.removePriceLine(l)); };
  }, [triggerKey]);

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
}
