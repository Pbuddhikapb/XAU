import React, { useEffect, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  IChartApi,
  ISeriesApi,
  CandlestickData,
  HistogramData,
  LineData,
  Time,
  SeriesMarker,
} from "lightweight-charts";
import { Eye, EyeOff, RefreshCw } from "lucide-react";
import type { Candle, StructureEvent, StructureZone, TradeSetup } from "../../types";

interface TradingChartProps {
  candles: Candle[];
  timeframe: string;
  onTimeframeChange: (tf: string) => void;
  structureLevels: StructureZone[];
  structureEvents: StructureEvent[];
  activeSetup: TradeSetup | null;
  onRefresh: () => void;
  isLoading: boolean;
}

export const TradingChart: React.FC<TradingChartProps> = ({
  candles,
  timeframe,
  onTimeframeChange,
  structureLevels,
  structureEvents,
  activeSetup,
  onRefresh,
  isLoading,
}) => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const vwapSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapUpperSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const vwapLowerSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  // Overlay visibility toggles
  const [showVwap, setShowVwap] = useState<boolean>(true);
  const [showLevels, setShowLevels] = useState<boolean>(true);
  const [showSweeps, setShowSweeps] = useState<boolean>(true);
  const [showSetup, setShowSetup] = useState<boolean>(true);

  // Price lines references for cleanup
  const priceLinesRef = useRef<any[]>([]);

  const timeframes = ["1d", "4h", "1h", "15m", "5m"];

  // Initialize Lightweight Chart
  useEffect(() => {
    if (!chartContainerRef.current) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#080c14" },
        textColor: "#94a3b8",
        fontSize: 11,
        fontFamily: "JetBrains Mono, monospace",
      },
      grid: {
        vertLines: { color: "#131c2e" },
        horzLines: { color: "#131c2e" },
      },
      crosshair: {
        mode: 1, // Magnet crosshair
        vertLine: { color: "#475569", width: 1, style: 2 },
        horzLine: { color: "#475569", width: 1, style: 2 },
      },
      rightPriceScale: {
        borderColor: "#1e293b",
        scaleMargins: { top: 0.1, bottom: 0.2 },
      },
      timeScale: {
        borderColor: "#1e293b",
        timeVisible: true,
        secondsVisible: false,
      },
      handleScale: { axisPressedMouseMove: true },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: "#10b981",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#10b981",
      wickDownColor: "#ef4444",
    });

    const volumeSeries = chart.addHistogramSeries({
      color: "#1e293b",
      priceFormat: { type: "volume" },
      priceScaleId: "", // Overlay volume on separate internal scale
    });

    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    const vwapSeries = chart.addLineSeries({
      color: "#f59e0b",
      lineWidth: 2,
      title: "NY VWAP",
    });

    const vwapUpperSeries = chart.addLineSeries({
      color: "#eab308",
      lineWidth: 1,
      lineStyle: 2, // Dashed
      title: "VWAP +2σ",
    });

    const vwapLowerSeries = chart.addLineSeries({
      color: "#eab308",
      lineWidth: 1,
      lineStyle: 2, // Dashed
      title: "VWAP -2σ",
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    vwapSeriesRef.current = vwapSeries;
    vwapUpperSeriesRef.current = vwapUpperSeries;
    vwapLowerSeriesRef.current = vwapLowerSeries;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({
          width: chartContainerRef.current.clientWidth,
          height: chartContainerRef.current.clientHeight,
        });
      }
    };

    window.addEventListener("resize", handleResize);
    handleResize();

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, []);

  // Update candlestick data and volume
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || candles.length === 0) return;

    const candleData: CandlestickData<Time>[] = [];
    const volumeData: HistogramData<Time>[] = [];
    const vwapData: LineData<Time>[] = [];
    const vwapUpperData: LineData<Time>[] = [];
    const vwapLowerData: LineData<Time>[] = [];

    // Calculate approximate running VWAP for chart display
    let cumulativeVol = 0;
    let cumulativeTypicalVol = 0;

    candles.forEach((c) => {
      const time = (c.open_time / 1000) as Time;
      const typical = (c.high + c.low + c.close) / 3;
      cumulativeVol += c.volume;
      cumulativeTypicalVol += typical * c.volume;
      const vwap = cumulativeVol > 0 ? cumulativeTypicalVol / cumulativeVol : typical;

      candleData.push({
        time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      });

      volumeData.push({
        time,
        value: c.volume,
        color: c.close >= c.open ? "rgba(16, 185, 129, 0.25)" : "rgba(239, 68, 68, 0.25)",
      });

      // Approximate bands using 0.5% buffer for visualization
      vwapData.push({ time, value: vwap });
      vwapUpperData.push({ time, value: vwap * 1.004 });
      vwapLowerData.push({ time, value: vwap * 0.996 });
    });

    candleSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);

    if (showVwap) {
      vwapSeriesRef.current?.setData(vwapData);
      vwapUpperSeriesRef.current?.setData(vwapUpperData);
      vwapLowerSeriesRef.current?.setData(vwapLowerData);
    } else {
      vwapSeriesRef.current?.setData([]);
      vwapUpperSeriesRef.current?.setData([]);
      vwapLowerSeriesRef.current?.setData([]);
    }

    // Set Sweep Markers
    if (showSweeps && structureEvents.length > 0) {
      const markers: SeriesMarker<Time>[] = [];
      structureEvents.forEach((ev) => {
        try {
          if (ev.event_type && ev.event_type.includes("SWEEP")) {
            const time = (new Date(ev.event_time).getTime() / 1000) as Time;
            const isHigh = ev.event_type.includes("HIGH") || ev.price >= (candles[candles.length - 1]?.close ?? 0);
            markers.push({
              time,
              position: isHigh ? "aboveBar" : "belowBar",
              color: isHigh ? "#f59e0b" : "#3b82f6",
              shape: isHigh ? "arrowDown" : "arrowUp",
              text: `Sweep $${ev.price.toFixed(1)}`,
            });
          }
        } catch {}
      });
      markers.sort((a, b) => Number(a.time) - Number(b.time));
      try {
        candleSeriesRef.current?.setMarkers(markers);
      } catch (err) {
        console.warn("Could not set markers:", err);
      }
    } else {
      try {
        candleSeriesRef.current?.setMarkers([]);
      } catch {}
    }

    // Cleanup and draw price lines
    priceLinesRef.current.forEach((line) => {
      try {
        candleSeriesRef.current?.removePriceLine(line);
      } catch {}
    });
    priceLinesRef.current = [];

    // Support and Resistance Lines
    if (showLevels && structureLevels.length > 0) {
      structureLevels.forEach((lvl) => {
        try {
          const type = lvl.zone_type || lvl.level_type || "LEVEL";
          const isSupport = type === "SUPPORT";
          const minP = lvl.level_min ?? lvl.price_min ?? 0;
          const maxP = lvl.level_max ?? lvl.price_max ?? 0;
          const midPrice = lvl.level_center ?? ((minP + maxP) / 2 || minP || maxP);
          const count = lvl.touches_count ?? lvl.touch_count ?? 1;

          if (!isNaN(midPrice) && midPrice > 0) {
            const line = candleSeriesRef.current?.createPriceLine({
              price: midPrice,
              color: isSupport ? "rgba(16, 185, 129, 0.6)" : "rgba(239, 68, 68, 0.6)",
              lineWidth: 1,
              lineStyle: 1, // Dotted
              axisLabelVisible: true,
              title: `${type.substring(0, 3)} (${count}x)`,
            });
            if (line) priceLinesRef.current.push(line);
          }
        } catch (err) {
          console.warn("Failed to plot S/R level:", err);
        }
      });
    }

    // Active Setup Lines
    if (showSetup && activeSetup) {
      // Entry Line
      const entryLine = candleSeriesRef.current?.createPriceLine({
        price: (activeSetup.entry_price_min + activeSetup.entry_price_max) / 2,
        color: "#38bdf8",
        lineWidth: 2,
        lineStyle: 0, // Solid
        axisLabelVisible: true,
        title: `ENTRY (${activeSetup.direction})`,
      });
      if (entryLine) priceLinesRef.current.push(entryLine);

      // Stop Loss Line
      const slLine = candleSeriesRef.current?.createPriceLine({
        price: activeSetup.active_stop_loss || activeSetup.stop_loss,
        color: "#ef4444",
        lineWidth: 2,
        lineStyle: 0,
        axisLabelVisible: true,
        title: activeSetup.breakeven_locked ? "SL (BREAKEVEN LOCKED)" : "STOP LOSS",
      });
      if (slLine) priceLinesRef.current.push(slLine);

      // Target Lines
      [
        { p: activeSetup.target_1, label: "T1 (Lock BE)" },
        { p: activeSetup.target_2, label: "T2" },
        { p: activeSetup.target_3, label: "T3 (Terminal)" },
      ].forEach(({ p, label }) => {
        const tLine = candleSeriesRef.current?.createPriceLine({
          price: p,
          color: "#10b981",
          lineWidth: 1,
          lineStyle: 2,
          axisLabelVisible: true,
          title: label,
        });
        if (tLine) priceLinesRef.current.push(tLine);
      });
    }

    chartRef.current?.timeScale().fitContent();
  }, [candles, showVwap, showLevels, showSweeps, showSetup, structureLevels, structureEvents, activeSetup]);

  return (
    <div className="flex flex-col h-full bg-surface border border-border rounded-lg overflow-hidden shadow-lg">
      {/* Chart Control Toolbar */}
      <div className="flex flex-wrap items-center justify-between px-3 py-2 bg-card border-b border-border gap-2">
        {/* Timeframe Buttons */}
        <div className="flex items-center gap-1">
          {timeframes.map((tf) => (
            <button
              key={tf}
              onClick={() => onTimeframeChange(tf)}
              className={`px-2.5 py-1 text-xs font-mono rounded transition-colors ${
                timeframe.toLowerCase() === tf
                  ? "bg-gold-500 text-black font-bold shadow"
                  : "text-slate-400 hover:text-white hover:bg-slate-800"
              }`}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>

        {/* Overlay Toggles */}
        <div className="flex items-center gap-2 text-xs font-mono">
          <button
            onClick={() => setShowVwap(!showVwap)}
            className={`flex items-center gap-1 px-2 py-0.5 rounded border transition-colors ${
              showVwap
                ? "bg-amber-500/10 border-amber-500/30 text-amber-400"
                : "border-border text-slate-500 hover:text-slate-300"
            }`}
          >
            {showVwap ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
            VWAP
          </button>

          <button
            onClick={() => setShowLevels(!showLevels)}
            className={`flex items-center gap-1 px-2 py-0.5 rounded border transition-colors ${
              showLevels
                ? "bg-blue-500/10 border-blue-500/30 text-blue-400"
                : "border-border text-slate-500 hover:text-slate-300"
            }`}
          >
            {showLevels ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
            S/R
          </button>

          <button
            onClick={() => setShowSweeps(!showSweeps)}
            className={`flex items-center gap-1 px-2 py-0.5 rounded border transition-colors ${
              showSweeps
                ? "bg-purple-500/10 border-purple-500/30 text-purple-400"
                : "border-border text-slate-500 hover:text-slate-300"
            }`}
          >
            {showSweeps ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
            Sweeps
          </button>

          <button
            onClick={() => setShowSetup(!showSetup)}
            className={`flex items-center gap-1 px-2 py-0.5 rounded border transition-colors ${
              showSetup
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                : "border-border text-slate-500 hover:text-slate-300"
            }`}
          >
            {showSetup ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
            Setup
          </button>

          <button
            onClick={onRefresh}
            disabled={isLoading}
            className="p-1 rounded text-slate-400 hover:text-gold-400 hover:bg-slate-800 transition-colors disabled:opacity-50"
            title="Refresh Candles"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Chart Canvas */}
      <div className="relative flex-1 w-full min-h-[480px]">
        <div ref={chartContainerRef} className="absolute inset-0 w-full h-full" />
      </div>
    </div>
  );
};
