import React from "react";
import { AlertCircle, AlertTriangle, CheckCircle2, Gauge, Shield, TrendingDown, TrendingUp } from "lucide-react";
import type { DirectionAnalysis } from "../../types";

interface EngineAPanelProps {
  analysis: DirectionAnalysis | null;
  isLoading: boolean;
}

export const EngineAPanel: React.FC<EngineAPanelProps> = ({ analysis, isLoading }) => {
  if (isLoading && !analysis) {
    return (
      <div className="bg-surface border border-border rounded-lg p-4 flex items-center justify-center min-h-[300px]">
        <div className="flex items-center gap-2 text-slate-400 font-mono text-sm animate-pulse">
          <Gauge className="w-5 h-5 animate-spin text-gold-400" /> Computing Engine A Directional Scoring...
        </div>
      </div>
    );
  }

  if (!analysis) {
    return (
      <div className="bg-surface border border-border rounded-lg p-4 text-center text-slate-500 font-mono text-sm">
        No directional analysis available.
      </div>
    );
  }

  const isBullish = analysis.direction === "BULLISH";
  const isBearish = analysis.direction === "BEARISH";
  const isNeutral = analysis.direction === "NEUTRAL";

  return (
    <div className="flex flex-col bg-surface border border-border rounded-lg overflow-hidden shadow-lg text-xs font-mono">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-card border-b border-border">
        <div className="flex items-center gap-2 font-bold text-slate-200">
          <Gauge className="w-4 h-4 text-gold-400" />
          <span>ENGINE A: DIRECTIONAL BIAS</span>
        </div>
        <div className="flex items-center gap-2 text-[10px]">
          <span className="text-slate-400">DATA QUALITY:</span>
          <span
            className={`font-bold ${
              (Number(analysis.data_quality_score) || 0) >= 70 ? "text-bull-400" : "text-bear-400"
            }`}
          >
            {(Number(analysis.data_quality_score) || 0).toFixed(0)}/100
          </span>
        </div>
      </div>

      <div className="p-3 space-y-3">
        {/* Direction & Conviction Strip */}
        <div className="flex items-center justify-between p-2.5 rounded bg-card border border-border">
          <div className="flex items-center gap-2">
            {isBullish && <TrendingUp className="w-6 h-6 text-bull-400" />}
            {isBearish && <TrendingDown className="w-6 h-6 text-bear-400" />}
            {isNeutral && <Shield className="w-6 h-6 text-slate-400" />}
            <div>
              <div
                className={`text-base font-bold tracking-wider ${
                  isBullish ? "text-bull-400" : isBearish ? "text-bear-400" : "text-slate-300"
                }`}
              >
                {analysis.direction}
              </div>
              <div className="text-[10px] text-slate-400">
                Conviction: <span className="text-gold-400 uppercase font-semibold">{analysis.score_label}</span>
              </div>
            </div>
          </div>

          <div className="text-right">
            <div className="text-[10px] text-slate-400">SESSION GATE</div>
            <span
              className={`text-[11px] font-bold ${
                analysis.cme_session_active ? "text-bull-400" : "text-gold-400"
              }`}
            >
              {analysis.cme_session_active ? "CME ACTIVE" : "CME GATED"}
            </span>
          </div>
        </div>

        {/* Heuristic Scores (0-100) */}
        <div className="space-y-1.5 bg-card/60 p-2.5 rounded border border-border">
          <div className="flex justify-between text-[11px]">
            <span className="text-slate-400">Bullish Score:</span>
            <span className="font-bold text-bull-400">{(Number(analysis.bullish_score) || 0).toFixed(1)} / 100</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
            <div
              className="bg-bull-500 h-1.5 rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, Math.max(0, Number(analysis.bullish_score) || 0))}%` }}
            />
          </div>

          <div className="flex justify-between text-[11px] pt-1">
            <span className="text-slate-400">Bearish Score:</span>
            <span className="font-bold text-bear-400">{(Number(analysis.bearish_score) || 0).toFixed(1)} / 100</span>
          </div>
          <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
            <div
              className="bg-bear-500 h-1.5 rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, Math.max(0, Number(analysis.bearish_score) || 0))}%` }}
            />
          </div>
        </div>

        {/* Multi-Timeframe Alignment */}
        <div>
          <div className="text-slate-400 text-[10px] uppercase tracking-wider mb-1.5">Multi-Timeframe Alignment</div>
          <div className="grid grid-cols-5 gap-1 text-center">
            {Object.entries(analysis.timeframe_alignment || {}).map(([tf, dir]) => (
              <div
                key={tf}
                className={`p-1 rounded border text-[10px] font-bold uppercase ${
                  dir === "BULLISH"
                    ? "bg-bull-500/10 border-bull-500/30 text-bull-400"
                    : dir === "BEARISH"
                    ? "bg-bear-500/10 border-bear-500/30 text-bear-400"
                    : "bg-slate-800/50 border-border text-slate-400"
                }`}
              >
                <div>{tf}</div>
                <div className="text-[9px] font-normal">{dir.substring(0, 4)}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Supporting Evidence */}
        <div>
          <div className="flex items-center gap-1 text-bull-400 text-[10px] uppercase tracking-wider mb-1">
            <CheckCircle2 className="w-3 h-3" /> Supporting Evidence ({analysis.supporting_evidence?.length ?? 0})
          </div>
          <div className="space-y-1 max-h-28 overflow-y-auto pr-1">
            {analysis.supporting_evidence?.length ? (
              analysis.supporting_evidence.map((ev, idx) => (
                <div key={idx} className="bg-card p-1.5 rounded border border-border text-[11px] flex justify-between gap-1">
                  <span className="text-slate-300">{ev.description}</span>
                  <span className="text-bull-400 font-bold shrink-0">
                    +{ev.score_contribution !== undefined ? ev.score_contribution : (ev.weight ?? 0)}
                  </span>
                </div>
              ))
            ) : (
              <div className="text-slate-500 italic p-1">No strong supporting factors</div>
            )}
          </div>
        </div>

        {/* Contradicting Evidence */}
        <div>
          <div className="flex items-center gap-1 text-bear-400 text-[10px] uppercase tracking-wider mb-1">
            <AlertCircle className="w-3 h-3" /> Contradicting Evidence ({analysis.contradicting_evidence?.length ?? 0})
          </div>
          <div className="space-y-1 max-h-28 overflow-y-auto pr-1">
            {analysis.contradicting_evidence?.length ? (
              analysis.contradicting_evidence.map((ev, idx) => (
                <div key={idx} className="bg-card p-1.5 rounded border border-border text-[11px] flex justify-between gap-1">
                  <span className="text-slate-300">{ev.description}</span>
                  <span className="text-bear-400 font-bold shrink-0">
                    -{ev.score_contribution !== undefined ? ev.score_contribution : (ev.weight ?? 0)}
                  </span>
                </div>
              ))
            ) : (
              <div className="text-slate-500 italic p-1">No contradicting factors</div>
            )}
          </div>
        </div>

        {/* Two-Tier Invalidation Triggers */}
        <div className="bg-card p-2 rounded border border-border space-y-1 text-[10px]">
          <div className="flex items-center gap-1 text-gold-400 font-semibold uppercase">
            <AlertTriangle className="w-3 h-3" /> Invalidation Rules
          </div>
          <div className="text-slate-400">
            <span className="text-slate-200 font-medium">Soft Warning: </span>
            {analysis.invalidation_conditions?.soft_invalidation || "Loss of intraday VWAP anchor"}
          </div>
          <div className="text-slate-400">
            <span className="text-bear-400 font-medium">Hard Direction Flip: </span>
            {analysis.invalidation_conditions?.hard_invalidation || "Break of structural swing low/high"}
          </div>
        </div>
      </div>
    </div>
  );
};
