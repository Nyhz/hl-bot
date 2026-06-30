"use client";
import { useEffect, useRef } from "react";
import { createChart, CandlestickSeries, type IChartApi, type ISeriesApi } from "lightweight-charts";
import type { CoinView } from "@/lib/types";
import { api } from "@/lib/api";
import { candleSeries } from "@/lib/view";

export function FocusChart({ coin, coinView }: { coin: string | null; coinView: CoinView | undefined }) {
  const ref = useRef<HTMLDivElement | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      height: 320, layout: { background: { color: "transparent" }, textColor: "#8a8f98" },
      grid: { vertLines: { color: "#14171c" }, horzLines: { color: "#14171c" } },
      rightPriceScale: { borderVisible: false }, timeScale: { borderVisible: false },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#00ff88", downColor: "#ff4466", wickUpColor: "#00ff88", wickDownColor: "#ff4466", borderVisible: false,
    });
    chartRef.current = chart; seriesRef.current = series;
    const onResize = () => ref.current && chart.applyOptions({ width: ref.current.clientWidth });
    onResize(); window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); chartRef.current = null; seriesRef.current = null; };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !coin) return;
    let cancelled = false;
    api.getCandles(coin).then((cs) => { if (!cancelled) series.setData(candleSeries(cs) as never); }).catch(() => {});
    return () => { cancelled = true; };
  }, [coin]);

  // Price lines de triggers (se recrean cuando cambian)
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    const lines = (coinView?.triggers ?? []).map((t) =>
      series.createPriceLine({ price: t.level, color: t.side === "buy" ? "#00ff88" : "#ff4466", lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: t.action }));
    return () => { lines.forEach((l) => series.removePriceLine(l)); };
  }, [coinView]);

  return (
    <div className="panel" style={{ padding: 8 }}>
      <div className="muted" style={{ fontSize: 11, marginBottom: 6 }}>{coin ?? "—"} · live</div>
      <div ref={ref} style={{ width: "100%" }} />
    </div>
  );
}
