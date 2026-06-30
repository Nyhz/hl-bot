"use client";
import { useEffect, useRef } from "react";
import { createChart, AreaSeries, type IChartApi } from "lightweight-charts";
import { api } from "@/lib/api";
import { equitySeries } from "@/lib/view";

export function EquityCurve({ sessionId }: { sessionId: number | null }) {
  const ref = useRef<HTMLDivElement | null>(null);
  // La curva se recarga cuando cambia la sesión (sessionId). Mejora futura (2b.3): append en vivo del punto de equity con series.update().
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
    let cancelled = false;
    if (sessionId !== null) {
      api.getEquityCurve(sessionId).then((rows) => {
        if (!cancelled) series.setData(equitySeries(rows) as never);
      }).catch(() => {});
    }
    const onResize = () => ref.current && chart.applyOptions({ width: ref.current.clientWidth });
    onResize(); window.addEventListener("resize", onResize);
    return () => { cancelled = true; window.removeEventListener("resize", onResize); chart.remove(); };
  }, [sessionId]);
  return <div className="panel" ref={ref} style={{ width: "100%" }} />;
}
