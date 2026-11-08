import React, { useEffect, useState } from "react";
import { Filter, RefreshCw, TrendingDown, TrendingUp } from "lucide-react";
import { api } from "../../services/api";
import type { HorizonSignalRecord } from "../../types";

export const SignalHistoryView: React.FC = () => {
  const [signals, setSignals] = useState<HorizonSignalRecord[]>([]);
  const [horizonFilter, setHorizonFilter] = useState<number | undefined>(undefined);
  const [outcomeFilter, setOutcomeFilter] = useState<string | undefined>(undefined);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const loadSignals = async () => {
    setIsLoading(true);
    try {
      const data = await api.getSignalsHistory({
        horizon: horizonFilter,
        outcome: outcomeFilter,
        limit: 150,
      });
      setSignals(data);
    } catch (err) {
      console.error("Failed to load signals:", err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    loadSignals();
  }, [horizonFilter, outcomeFilter]);

  // Aggregate horizon performance metrics
  const total = signals.length;
  const favorableCount = signals.filter((s) => s.favorable_first).length;
  const favorablePct = total > 0 ? (favorableCount / total) * 100 : 0;
  const avgMfe = total > 0 ? signals.reduce((acc, s) => acc + s.mfe_points, 0) / total : 0;
  const avgMae = total > 0 ? signals.reduce((acc, s) => acc + s.mae_points, 0) / total : 0;

  return (
    <div className="p-4 space-y-4 font-mono text-xs">
      {/* Top Horizon KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-surface border border-border p-3 rounded-lg shadow">
          <div className="text-slate-400 text-[10px] uppercase">TOTAL SIGNALS EVALUATED</div>
          <div className="text-xl font-bold text-slate-100">{total}</div>
        </div>
        <div className="bg-surface border border-border p-3 rounded-lg shadow">
          <div className="text-slate-400 text-[10px] uppercase">FAVORABLE-FIRST ACCURACY</div>
          <div className={`text-xl font-bold ${favorablePct >= 50 ? "text-bull-400" : "text-bear-400"}`}>
            {favorablePct.toFixed(1)}%
          </div>
        </div>
        <div className="bg-surface border border-border p-3 rounded-lg shadow">
          <div className="text-slate-400 text-[10px] uppercase">AVG MFE (FAVORABLE EXCURSION)</div>
          <div className="text-xl font-bold text-bull-400">+{avgMfe.toFixed(2)} pts</div>
        </div>
        <div className="bg-surface border border-border p-3 rounded-lg shadow">
          <div className="text-slate-400 text-[10px] uppercase">AVG MAE (ADVERSE EXCURSION)</div>
          <div className="text-xl font-bold text-bear-400">-{avgMae.toFixed(2)} pts</div>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="flex flex-wrap items-center justify-between bg-surface border border-border p-3 rounded-lg gap-3">
        <div className="flex items-center gap-2">
          <Filter className="w-3.5 h-3.5 text-gold-400" />
          <span className="text-slate-300 font-semibold text-[11px]">FILTERS:</span>

          {/* Horizon Filter */}
          <div className="flex items-center gap-1 ml-2">
            {[undefined, 5, 10, 20, 50].map((h) => (
              <button
                key={h ?? "all"}
                onClick={() => setHorizonFilter(h)}
                className={`px-2 py-0.5 rounded text-[10px] border transition-colors ${
                  horizonFilter === h
                    ? "bg-gold-500 text-black border-gold-500 font-bold"
                    : "border-border text-slate-400 hover:bg-slate-800"
                }`}
              >
                {h ? `${h} Bars` : "All Horizons"}
              </button>
            ))}
          </div>

          {/* Outcome Filter */}
          <div className="flex items-center gap-1 ml-2">
            {[undefined, "FAVORABLE_FIRST", "ADVERSE_FIRST"].map((o) => (
              <button
                key={o ?? "all"}
                onClick={() => setOutcomeFilter(o)}
                className={`px-2 py-0.5 rounded text-[10px] border transition-colors ${
                  outcomeFilter === o
                    ? "bg-gold-500 text-black border-gold-500 font-bold"
                    : "border-border text-slate-400 hover:bg-slate-800"
                }`}
              >
                {o ? o.replace("_", " ") : "All Outcomes"}
              </button>
            ))}
          </div>
        </div>

        <button
          onClick={loadSignals}
          disabled={isLoading}
          className="flex items-center gap-1.5 px-3 py-1 bg-card hover:bg-slate-800 border border-border text-slate-300 rounded transition-colors disabled:opacity-50"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isLoading ? "animate-spin" : ""}`} /> Refresh
        </button>
      </div>

      {/* Signals Table */}
      <div className="bg-surface border border-border rounded-lg overflow-hidden shadow">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-card border-b border-border text-slate-400 text-[10px] uppercase tracking-wider">
                <th className="p-2.5">Signal Time</th>
                <th className="p-2.5">Direction</th>
                <th className="p-2.5">Score</th>
                <th className="p-2.5">Horizon</th>
                <th className="p-2.5">Initial Price</th>
                <th className="p-2.5">MFE (Peak Fav)</th>
                <th className="p-2.5">MAE (Peak Adv)</th>
                <th className="p-2.5">Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {signals.length === 0 ? (
                <tr>
                  <td colSpan={8} className="p-6 text-center text-slate-500">
                    {isLoading ? "Loading signal outcomes..." : "No historical signal outcomes match filter."}
                  </td>
                </tr>
              ) : (
                signals.map((s) => (
                  <tr key={s.id} className="hover:bg-card/50 transition-colors">
                    <td className="p-2.5 text-slate-300">
                      {new Date(s.signal_time).toLocaleString()}
                    </td>
                    <td className="p-2.5">
                      <span
                        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          s.direction === "BULLISH"
                            ? "bg-bull-500/10 text-bull-400 border border-bull-500/30"
                            : "bg-bear-500/10 text-bear-400 border border-bear-500/30"
                        }`}
                      >
                        {s.direction === "BULLISH" ? (
                          <TrendingUp className="w-3 h-3" />
                        ) : (
                          <TrendingDown className="w-3 h-3" />
                        )}
                        {s.direction}
                      </span>
                    </td>
                    <td className="p-2.5 font-bold text-slate-200">
                      {s.direction_score.toFixed(0)}
                    </td>
                    <td className="p-2.5 text-gold-400 font-semibold">{s.horizon_candles} bars</td>
                    <td className="p-2.5 text-slate-300">${s.initial_price.toFixed(2)}</td>
                    <td className="p-2.5 text-bull-400 font-bold">+{s.mfe_points.toFixed(2)}</td>
                    <td className="p-2.5 text-bear-400 font-bold">-{s.mae_points.toFixed(2)}</td>
                    <td className="p-2.5">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          s.favorable_first
                            ? "bg-bull-500/10 text-bull-400 border border-bull-500/30"
                            : "bg-bear-500/10 text-bear-400 border border-bear-500/30"
                        }`}
                      >
                        {s.outcome}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};
