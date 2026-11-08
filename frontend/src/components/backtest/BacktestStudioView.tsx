import React, { useEffect, useRef, useState } from "react";
import {
  BarChart2,
  Play,
  Plus,
  X,
} from "lucide-react";
import { createChart, ColorType, IChartApi, ISeriesApi, LineData, Time } from "lightweight-charts";
import { api } from "../../services/api";
import type { BacktestRun, BacktestRunDetail } from "../../types";

export const BacktestStudioView: React.FC = () => {
  const [runs, setRuns] = useState<BacktestRun[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [runDetail, setRunDetail] = useState<BacktestRunDetail | null>(null);
  const [showLauncher, setShowLauncher] = useState<boolean>(false);
  const [isExecuting, setIsExecuting] = useState<boolean>(false);

  // Form states for launching a new backtest
  const [startDate, setStartDate] = useState<string>("2026-01-01T00:00:00Z");
  const [endDate, setEndDate] = useState<string>("2026-03-01T00:00:00Z");
  const [initialBalance, setInitialBalance] = useState<number>(10000);

  // Equity Chart refs
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const equitySeriesRef = useRef<ISeriesApi<"Area"> | null>(null);

  const loadRuns = async () => {
    try {
      const data = await api.getBacktestRuns(20);
      setRuns(data);
      if (data.length > 0 && !selectedRunId) {
        setSelectedRunId(data[0].run_id);
      }
    } catch (err) {
      console.error("Failed to load backtest runs:", err);
    }
  };

  const loadRunDetail = async (runId: string) => {
    try {
      const detail = await api.getBacktestDetail(runId);
      setRunDetail(detail);
    } catch (err) {
      console.error("Failed to load backtest detail:", err);
    }
  };

  useEffect(() => {
    loadRuns();
  }, []);

  useEffect(() => {
    if (selectedRunId) {
      loadRunDetail(selectedRunId);
    }
  }, [selectedRunId]);

  // Initialize and update Lightweight Charts for Equity Curve
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
      rightPriceScale: {
        borderColor: "#1e293b",
      },
      timeScale: {
        borderColor: "#1e293b",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    const equitySeries = chart.addAreaSeries({
      topColor: "rgba(245, 158, 11, 0.4)",
      bottomColor: "rgba(245, 158, 11, 0.0)",
      lineColor: "#f59e0b",
      lineWidth: 2,
    });

    chartRef.current = chart;
    equitySeriesRef.current = equitySeries;

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

  // Update Equity Curve data
  useEffect(() => {
    if (!equitySeriesRef.current || !runDetail?.trades || runDetail.trades.length === 0) {
      equitySeriesRef.current?.setData([]);
      return;
    }

    let runningEquity = runDetail.run.initial_balance || 10000;
    const curve: LineData<Time>[] = [];

    // Initial point
    const startTime = (new Date(runDetail.run.start_time).getTime() / 1000) as Time;
    curve.push({ time: startTime, value: runningEquity });

    runDetail.trades.forEach((t) => {
      runningEquity += t.pnl_dollars;
      const tTime = (new Date(t.exit_time).getTime() / 1000) as Time;
      curve.push({ time: tTime, value: runningEquity });
    });

    equitySeriesRef.current.setData(curve);
    chartRef.current?.timeScale().fitContent();
  }, [runDetail]);

  const handleRunBacktest = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsExecuting(true);
    try {
      const res = await api.runBacktest({
        start_time: startDate,
        end_time: endDate,
        initial_balance: initialBalance,
      });
      setShowLauncher(false);
      await loadRuns();
      setSelectedRunId(res.run.run_id);
    } catch (err: any) {
      alert(`Backtest execution error: ${err.message}`);
    } finally {
      setIsExecuting(false);
    }
  };

  const metrics = runDetail?.metrics;

  return (
    <div className="p-4 space-y-4 font-mono text-xs">
      {/* Top Action Bar */}
      <div className="flex flex-wrap items-center justify-between bg-surface border border-border p-3 rounded-lg gap-3">
        <div className="flex items-center gap-3">
          <BarChart2 className="w-5 h-5 text-gold-400" />
          <div>
            <span className="font-bold text-slate-100 text-sm">BACKTESTING & VALIDATION STUDIO</span>
            <span className="text-[10px] text-slate-400 block">
              Event-driven walk-forward simulations with zero-lookahead & 0.14% institutional friction
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Select Run Dropdown */}
          <select
            value={selectedRunId || ""}
            onChange={(e) => setSelectedRunId(e.target.value)}
            className="bg-card border border-border text-slate-200 px-3 py-1.5 rounded text-xs font-mono focus:outline-none focus:border-gold-500"
          >
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {new Date(r.created_at).toLocaleDateString()} — {r.symbol} ({r.execution_mode})
              </option>
            ))}
          </select>

          <button
            onClick={() => setShowLauncher(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-gold-500 text-black font-bold rounded shadow hover:bg-gold-400 transition-colors"
          >
            <Plus className="w-3.5 h-3.5" /> Launch Simulation
          </button>
        </div>
      </div>

      {/* KPI Cards Grid */}
      {metrics && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
          <div className="bg-surface border border-border p-3 rounded-lg shadow">
            <span className="text-slate-400 text-[10px] uppercase block">WIN RATE</span>
            <span
              className={`text-xl font-bold ${
                metrics.win_rate_pct >= 50 ? "text-bull-400" : "text-bear-400"
              }`}
            >
              {metrics.win_rate_pct.toFixed(1)}%
            </span>
            <span className="text-slate-500 text-[10px] block">
              {metrics.winning_trades}W / {metrics.losing_trades}L / {metrics.breakeven_trades}BE
            </span>
          </div>

          <div className="bg-surface border border-border p-3 rounded-lg shadow">
            <span className="text-slate-400 text-[10px] uppercase block">PROFIT FACTOR</span>
            <span
              className={`text-xl font-bold ${
                metrics.profit_factor >= 1.5 ? "text-bull-400" : "text-slate-200"
              }`}
            >
              {metrics.profit_factor >= 999 ? "∞" : metrics.profit_factor.toFixed(2)}
            </span>
            <span className="text-slate-500 text-[10px] block">Gross P/L Ratio</span>
          </div>

          <div className="bg-surface border border-border p-3 rounded-lg shadow">
            <span className="text-slate-400 text-[10px] uppercase block">SHARPE RATIO</span>
            <span
              className={`text-xl font-bold ${
                metrics.sharpe_ratio >= 1.5 ? "text-bull-400" : "text-slate-200"
              }`}
            >
              {metrics.sharpe_ratio.toFixed(2)}
            </span>
            <span className="text-slate-500 text-[10px] block">Risk-Adjusted</span>
          </div>

          <div className="bg-surface border border-border p-3 rounded-lg shadow">
            <span className="text-slate-400 text-[10px] uppercase block">MAX DRAWDOWN</span>
            <span className="text-xl font-bold text-bear-400">
              {metrics.max_drawdown_pct.toFixed(2)}%
            </span>
            <span className="text-slate-500 text-[10px] block">
              -${metrics.max_drawdown_dollars.toFixed(0)}
            </span>
          </div>

          <div className="bg-surface border border-border p-3 rounded-lg shadow">
            <span className="text-slate-400 text-[10px] uppercase block">NET REALIZED PNL</span>
            <span
              className={`text-xl font-bold ${
                metrics.net_pnl_dollars >= 0 ? "text-bull-400" : "text-bear-400"
              }`}
            >
              {metrics.net_pnl_dollars >= 0 ? "+" : ""}${metrics.net_pnl_dollars.toFixed(2)}
            </span>
            <span className="text-slate-500 text-[10px] block">
              ({metrics.net_pnl_pct.toFixed(2)}%)
            </span>
          </div>

          <div className="bg-surface border border-border p-3 rounded-lg shadow">
            <span className="text-slate-400 text-[10px] uppercase block">EXPECTANCY</span>
            <span className="text-xl font-bold text-gold-400">
              {metrics.expectancy_r >= 0 ? "+" : ""}
              {metrics.expectancy_r.toFixed(2)} R
            </span>
            <span className="text-slate-500 text-[10px] block">
              ${metrics.expectancy_dollars.toFixed(1)} / trade
            </span>
          </div>
        </div>
      )}

      {/* Main Grid: Equity Chart + Segmentations */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Equity Canvas */}
        <div className="lg:col-span-2 bg-surface border border-border rounded-lg p-3 flex flex-col shadow">
          <div className="flex items-center justify-between pb-2 mb-2 border-b border-border">
            <span className="font-bold text-slate-200">PORTFOLIO EQUITY CURVE ($)</span>
            <span className="text-slate-400 text-[10px]">
              Initial: ${runDetail?.run.initial_balance?.toLocaleString() || "10,000"}
            </span>
          </div>
          <div className="relative flex-1 min-h-[300px]">
            <div ref={chartContainerRef} className="absolute inset-0 w-full h-full" />
          </div>
        </div>

        {/* Segmentation & Degradation Analysis */}
        <div className="bg-surface border border-border rounded-lg p-3 space-y-3 shadow">
          <span className="font-bold text-slate-200 block border-b border-border pb-2">
            VALIDATION & SEGMENTATION
          </span>

          {/* In-Sample vs Out-of-Sample */}
          <div className="bg-card p-2.5 rounded border border-border space-y-2">
            <span className="text-gold-400 font-semibold block text-[11px]">Walk-Forward Robustness</span>
            <div className="flex justify-between text-slate-300">
              <span>In-Sample Win Rate:</span>
              <span className="font-bold">
                {((metrics?.in_sample_metrics?.win_rate ?? 0) * 100).toFixed(1)}%
              </span>
            </div>
            <div className="flex justify-between text-slate-300">
              <span>Out-of-Sample Win Rate:</span>
              <span className="font-bold">
                {((metrics?.out_of_sample_metrics?.win_rate ?? 0) * 100).toFixed(1)}%
              </span>
            </div>
            <div className="flex justify-between text-slate-300 border-t border-border pt-1">
              <span>Performance Degradation:</span>
              <span
                className={`font-bold ${
                  (metrics?.performance_degradation_pct ?? 0) <= 20
                    ? "text-bull-400"
                    : "text-bear-400"
                }`}
              >
                {(metrics?.performance_degradation_pct ?? 0).toFixed(1)}%
              </span>
            </div>
          </div>

          {/* Long vs Short Performance */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-card p-2 rounded border border-border">
              <span className="text-bull-400 font-semibold block text-[10px]">LONG TRADES</span>
              <div className="text-sm font-bold text-slate-100">
                {metrics?.long_performance?.trades ?? 0} trades
              </div>
              <div className="text-[10px] text-slate-400">
                WR: {((metrics?.long_performance?.win_rate ?? 0) * 100).toFixed(1)}%
              </div>
            </div>

            <div className="bg-card p-2 rounded border border-border">
              <span className="text-bear-400 font-semibold block text-[10px]">SHORT TRADES</span>
              <div className="text-sm font-bold text-slate-100">
                {metrics?.short_performance?.trades ?? 0} trades
              </div>
              <div className="text-[10px] text-slate-400">
                WR: {((metrics?.short_performance?.win_rate ?? 0) * 100).toFixed(1)}%
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Executed Trades Log */}
      <div className="bg-surface border border-border rounded-lg overflow-hidden shadow">
        <div className="p-3 bg-card border-b border-border font-bold text-slate-200">
          EXECUTED TRADES LOG ({runDetail?.trades?.length ?? 0})
        </div>
        <div className="overflow-x-auto max-h-72">
          <table className="w-full text-left border-collapse">
            <thead className="sticky top-0 bg-card border-b border-border text-slate-400 text-[10px] uppercase">
              <tr>
                <th className="p-2.5">Entry Time</th>
                <th className="p-2.5">Side</th>
                <th className="p-2.5">Type</th>
                <th className="p-2.5">Entry Price</th>
                <th className="p-2.5">Exit Time</th>
                <th className="p-2.5">Exit Price</th>
                <th className="p-2.5">Exit Reason</th>
                <th className="p-2.5">PnL ($)</th>
                <th className="p-2.5">R-Multiple</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {!runDetail?.trades || runDetail.trades.length === 0 ? (
                <tr>
                  <td colSpan={9} className="p-6 text-center text-slate-500">
                    No executed trades recorded in this run.
                  </td>
                </tr>
              ) : (
                runDetail.trades.map((t) => (
                  <tr key={t.trade_id} className="hover:bg-card/50 transition-colors">
                    <td className="p-2.5 text-slate-300">
                      {new Date(t.entry_time).toLocaleDateString()}{" "}
                      {new Date(t.entry_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td className="p-2.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          t.direction === "LONG"
                            ? "bg-bull-500/10 text-bull-400 border border-bull-500/30"
                            : "bg-bear-500/10 text-bear-400 border border-bear-500/30"
                        }`}
                      >
                        {t.direction}
                      </span>
                    </td>
                    <td className="p-2.5 text-slate-300">{t.setup_type}</td>
                    <td className="p-2.5 text-slate-200">${t.entry_price.toFixed(2)}</td>
                    <td className="p-2.5 text-slate-300">
                      {new Date(t.exit_time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </td>
                    <td className="p-2.5 text-slate-200">${t.exit_price.toFixed(2)}</td>
                    <td className="p-2.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          t.exit_reason.includes("TARGET")
                            ? "bg-bull-500/10 text-bull-400"
                            : t.exit_reason.includes("BREAKEVEN")
                            ? "bg-gold-500/10 text-gold-400"
                            : "bg-bear-500/10 text-bear-400"
                        }`}
                      >
                        {t.exit_reason}
                      </span>
                    </td>
                    <td
                      className={`p-2.5 font-bold ${
                        t.pnl_dollars >= 0 ? "text-bull-400" : "text-bear-400"
                      }`}
                    >
                      {t.pnl_dollars >= 0 ? "+" : ""}${t.pnl_dollars.toFixed(2)}
                    </td>
                    <td
                      className={`p-2.5 font-bold ${
                        t.r_multiple >= 0 ? "text-gold-400" : "text-bear-400"
                      }`}
                    >
                      {t.r_multiple >= 0 ? "+" : ""}
                      {t.r_multiple.toFixed(2)}R
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Launcher Modal */}
      {showLauncher && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center p-4">
          <div className="bg-surface border border-border rounded-lg max-w-md w-full p-4 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-border pb-2">
              <span className="font-bold text-slate-100 text-sm">LAUNCH BACKTEST SIMULATION</span>
              <button
                onClick={() => setShowLauncher(false)}
                className="text-slate-400 hover:text-white"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleRunBacktest} className="space-y-3">
              <div>
                <label className="text-slate-400 text-[10px] block mb-1">START DATE (ISO UTC)</label>
                <input
                  type="text"
                  value={startDate}
                  onChange={(e) => setStartDate(e.target.value)}
                  className="w-full bg-card border border-border text-slate-200 px-3 py-1.5 rounded focus:border-gold-500 outline-none"
                />
              </div>

              <div>
                <label className="text-slate-400 text-[10px] block mb-1">END DATE (ISO UTC)</label>
                <input
                  type="text"
                  value={endDate}
                  onChange={(e) => setEndDate(e.target.value)}
                  className="w-full bg-card border border-border text-slate-200 px-3 py-1.5 rounded focus:border-gold-500 outline-none"
                />
              </div>

              <div>
                <label className="text-slate-400 text-[10px] block mb-1">INITIAL CAPITAL ($)</label>
                <input
                  type="number"
                  value={initialBalance}
                  onChange={(e) => setInitialBalance(Number(e.target.value))}
                  className="w-full bg-card border border-border text-slate-200 px-3 py-1.5 rounded focus:border-gold-500 outline-none"
                />
              </div>

              <div className="bg-card p-2 rounded border border-border text-[10px] text-slate-400 space-y-1">
                <span className="text-gold-400 font-semibold block">Institutional Friction Rules:</span>
                <div>• Total cost: 0.14% per trade (Taker + Slippage + Spread + Funding)</div>
                <div>• Conservative resolution: Stop loss wins intra-bar collision</div>
                <div>• 1H setup identification with 5M multi-resolution execution</div>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowLauncher(false)}
                  className="px-3 py-1.5 bg-card hover:bg-slate-800 text-slate-300 rounded border border-border"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isExecuting}
                  className="flex items-center gap-1.5 px-4 py-1.5 bg-gold-500 hover:bg-gold-400 text-black font-bold rounded shadow disabled:opacity-50"
                >
                  <Play className={`w-3.5 h-3.5 ${isExecuting ? "animate-spin" : ""}`} />
                  {isExecuting ? "Simulating..." : "Execute Simulation"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
