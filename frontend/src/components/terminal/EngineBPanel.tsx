import React from "react";
import { AlertCircle, CheckCircle, Crosshair, Lock, ShieldCheck, Target, Zap } from "lucide-react";
import type { CurrentSetupsResponse, TradeSetup } from "../../types";

interface EngineBPanelProps {
  setupsResponse: CurrentSetupsResponse | null;
  isLoading: boolean;
}

export const EngineBPanel: React.FC<EngineBPanelProps> = ({ setupsResponse, isLoading }) => {
  if (isLoading && !setupsResponse) {
    return (
      <div className="bg-surface border border-border rounded-lg p-4 flex items-center justify-center min-h-[300px]">
        <div className="flex items-center gap-2 text-slate-400 font-mono text-sm animate-pulse">
          <Crosshair className="w-5 h-5 animate-spin text-gold-400" /> Scanning Trade Setups...
        </div>
      </div>
    );
  }

  const setups = setupsResponse?.setups || [];
  const activeSetup: TradeSetup | undefined = setups[0];

  return (
    <div className="flex flex-col bg-surface border border-border rounded-lg overflow-hidden shadow-lg text-xs font-mono">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-card border-b border-border">
        <div className="flex items-center gap-2 font-bold text-slate-200">
          <Target className="w-4 h-4 text-emerald-400" />
          <span>ENGINE B: TRADE SETUP LIFECYCLE</span>
        </div>
        <div>
          {activeSetup ? (
            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              ACTIVE SETUP
            </span>
          ) : (
            <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-slate-800 text-slate-400 border border-border">
              NO SETUP
            </span>
          )}
        </div>
      </div>

      <div className="p-3 space-y-3">
        {activeSetup ? (
          <>
            {/* Setup Header Strip */}
            <div className="flex items-center justify-between p-2.5 rounded bg-card border border-border">
              <div className="flex items-center gap-2">
                <span
                  className={`px-2 py-0.5 rounded text-[11px] font-bold uppercase ${
                    activeSetup.direction === "LONG"
                      ? "bg-bull-500/10 text-bull-400 border border-bull-500/30"
                      : "bg-bear-500/10 text-bear-400 border border-bear-500/30"
                  }`}
                >
                  {activeSetup.direction}
                </span>
                <div>
                  <div className="font-bold text-slate-200">{activeSetup.setup_type}</div>
                  <div className="text-[10px] text-slate-400">TF: {activeSetup.timeframe.toUpperCase()}</div>
                </div>
              </div>

              <div className="text-right">
                <span
                  className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                    activeSetup.status === "CONFIRMED"
                      ? "bg-blue-500/10 text-blue-400 border border-blue-500/30"
                      : activeSetup.status === "TRIGGERED"
                      ? "bg-purple-500/10 text-purple-400 border border-purple-500/30"
                      : activeSetup.status.includes("TARGET")
                      ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/30"
                      : "bg-amber-500/10 text-amber-400 border border-amber-500/30"
                  }`}
                >
                  {activeSetup.status.replace("_", " ")}
                </span>
              </div>
            </div>

            {/* Price Levels Grid */}
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-card p-2 rounded border border-border">
                <span className="text-[10px] text-slate-400 block">ENTRY ZONE</span>
                <span className="text-slate-100 font-bold">
                  ${activeSetup.entry_price_min.toFixed(2)} – ${activeSetup.entry_price_max.toFixed(2)}
                </span>
              </div>

              <div className="bg-card p-2 rounded border border-border">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-slate-400">ACTIVE STOP LOSS</span>
                  {activeSetup.breakeven_locked && (
                    <span className="flex items-center gap-0.5 text-[9px] text-gold-400 font-bold">
                      <Lock className="w-2.5 h-2.5" /> BE LOCKED
                    </span>
                  )}
                </div>
                <span
                  className={`font-bold ${
                    activeSetup.breakeven_locked ? "text-gold-400" : "text-bear-400"
                  }`}
                >
                  ${(activeSetup.active_stop_loss || activeSetup.stop_loss).toFixed(2)}
                </span>
              </div>
            </div>

            {/* Targets Grid */}
            <div className="space-y-1 bg-card/60 p-2.5 rounded border border-border">
              <div className="flex justify-between items-center text-[11px]">
                <span className="text-slate-400">Target 1 (Breakeven Trigger):</span>
                <span className="font-bold text-bull-400">${activeSetup.target_1.toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center text-[11px]">
                <span className="text-slate-400">Target 2 (Partial Scaling):</span>
                <span className="font-bold text-bull-400">${activeSetup.target_2.toFixed(2)}</span>
              </div>
              <div className="flex justify-between items-center text-[11px]">
                <span className="text-slate-400">Target 3 (Terminal Exit):</span>
                <span className="font-bold text-emerald-400">${activeSetup.target_3.toFixed(2)}</span>
              </div>
            </div>

            {/* Risk:Reward & Friction Metric */}
            <div className="flex items-center justify-between bg-card p-2 rounded border border-border">
              <div>
                <span className="text-[10px] text-slate-400 block">NET RISK:REWARD</span>
                <span
                  className={`text-sm font-bold ${
                    activeSetup.risk_reward_ratio >= 1.5 ? "text-bull-400" : "text-bear-400"
                  }`}
                >
                  1 : {activeSetup.risk_reward_ratio.toFixed(2)}
                </span>
              </div>
              <div className="text-right text-[10px] text-slate-400">
                <span>Total Friction: 0.14%</span>
                <div className="text-slate-500">(Taker 0.10% + Slip 0.02% + Spd 0.01% + Fund 0.01%)</div>
              </div>
            </div>

            {/* Invalidation Rules */}
            <div className="bg-card p-2 rounded border border-border text-[10px] text-slate-400">
              <span className="text-slate-200 font-medium">Auto-Invalidation: </span>
              {activeSetup.invalidation_reason || "Invalidates if opposing directional bias confirmed or bar limit reached."}
            </div>
          </>
        ) : (
          /* Structured NoSetupResponse Rationale */
          <div className="space-y-3 py-2">
            <div className="bg-card p-3 rounded border border-border space-y-2">
              <div className="flex items-center gap-2 text-slate-300 font-semibold">
                <AlertCircle className="w-4 h-4 text-gold-400" />
                <span>No Trade Setup Active</span>
              </div>
              <p className="text-slate-400 leading-relaxed text-[11px]">
                {setupsResponse?.reason || "Current market conditions do not meet the strict institutional entry threshold (R:R >= 1.5 after 0.14% friction, momentum alignment, or session validity)."}
              </p>
            </div>

            <div className="space-y-1.5 text-[11px]">
              <div className="text-slate-400 text-[10px] uppercase tracking-wider">Required Invariants for Qualification:</div>
              <div className="flex items-center gap-1.5 text-slate-300">
                <ShieldCheck className="w-3.5 h-3.5 text-gold-400" />
                <span>Net Risk:Reward &ge; 1.50 after 0.14% total friction</span>
              </div>
              <div className="flex items-center gap-1.5 text-slate-300">
                <Zap className="w-3.5 h-3.5 text-gold-400" />
                <span>Alignment with Engine A primary direction bias</span>
              </div>
              <div className="flex items-center gap-1.5 text-slate-300">
                <CheckCircle className="w-3.5 h-3.5 text-gold-400" />
                <span>Data quality score &gt; 70 and active CME trading window</span>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
