"use client";
import { useEffect, useRef } from "react";
import { createChart, AreaSeries, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { api } from "@/lib/api";
import { equitySeries } from "@/lib/view";

export function EquityCurve({ sessionId, equity, seed }: { sessionId: number | null; equity: number; seed?: { ts: number; total_pnl: number }[] }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const lastTimeRef = useRef<number>(0);

  useEffect(() => {
    if (!ref.current) return;
    const chart: IChartApi = createChart(ref.current, {
      height: 160, layout: { background: { color: "transparent" }, textColor: "#8a8f98" },
      grid: { vertLines: { visible: false }, horzLines: { color: "#1c1f26" } },
      timeScale: { visible: false }, rightPriceScale: { borderVisible: false },
    });
    // v5: addSeries(AreaSeries, ...)
    const series = chart.addSeries(AreaSeries, {
      lineColor: "#00ff88", topColor: "rgba(0,255,136,0.25)", bottomColor: "rgba(0,255,136,0.02)",
    });
    seriesRef.current = series;
    let cancelled = false;
    if (seed && seed.length) {
      series.setData(equitySeries(seed) as never);
    } else if (sessionId !== null) {
      api.getEquityCurve(sessionId).then((rows) => {
        if (!cancelled) {
          series.setData(equitySeries(rows) as never);
          lastTimeRef.current = rows.length ? rows[rows.length - 1].ts : 0;
        }
      }).catch(() => {});
    }
    const el = ref.current;
    const fit = () => chart.applyOptions({ width: el.clientWidth });
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(el);
    return () => { cancelled = true; ro.disconnect(); chart.remove(); seriesRef.current = null; };
  }, [sessionId, seed]);

  useEffect(() => {
    const s = seriesRef.current;
    if (s && equity > 0) {
      const now = Math.floor(Date.now() / 1000);
      const t = Math.max(now, lastTimeRef.current);
      try {
        s.update({ time: t as never, value: equity });
      } catch (e) {
        console.warn("EquityCurve series.update skipped:", e);
      }
      lastTimeRef.current = t;
    }
  }, [equity]);

  return <div className="panel" ref={ref} style={{ width: "100%" }} />;
}
