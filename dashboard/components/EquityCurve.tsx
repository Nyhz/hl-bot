"use client";
import { useEffect, useRef } from "react";
import { createChart, AreaSeries, type IChartApi, type ISeriesApi } from "lightweight-charts";
import { api } from "@/lib/api";
import { equitySeries } from "@/lib/view";

export function EquityCurve({ sessionId, equity }: { sessionId: number | null; equity: number }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const seriesRef = useRef<ISeriesApi<"Area"> | null>(null);

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
    if (sessionId !== null) {
      api.getEquityCurve(sessionId).then((rows) => {
        if (!cancelled) series.setData(equitySeries(rows) as never);
      }).catch(() => {});
    }
    const onResize = () => ref.current && chart.applyOptions({ width: ref.current.clientWidth });
    onResize(); window.addEventListener("resize", onResize);
    return () => { cancelled = true; window.removeEventListener("resize", onResize); chart.remove(); seriesRef.current = null; };
  }, [sessionId]);

  useEffect(() => {
    const s = seriesRef.current;
    if (s && equity > 0) s.update({ time: Math.floor(Date.now() / 1000) as never, value: equity });
  }, [equity]);

  return <div className="panel" ref={ref} style={{ width: "100%" }} />;
}
