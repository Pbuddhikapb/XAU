import React, { useEffect, useState } from "react";
import { Activity, Clock, Wifi, WifiOff } from "lucide-react";
import type { LiveMarketState } from "../types";
import type { ConnectionStatus } from "../services/websocket";

interface TopBarProps {
  marketState: LiveMarketState | null;
  connectionStatus: ConnectionStatus;
  activeTab: string;
  onTabChange: (tab: string) => void;
}

export const TopBar: React.FC<TopBarProps> = ({
  marketState,
  connectionStatus,
  activeTab,
  onTabChange,
}) => {
  const [fundingCountdown, setFundingCountdown] = useState<string>("--:--:--");
  const [prevLastPrice, setPrevLastPrice] = useState<number | null>(null);
  const [priceFlash, setPriceFlash] = useState<"up" | "down" | null>(null);

  // Tick flash detection
  useEffect(() => {
    if (marketState?.last_price) {
      if (prevLastPrice !== null) {
        if (marketState.last_price > prevLastPrice) {
          setPriceFlash("up");
        } else if (marketState.last_price < prevLastPrice) {
          setPriceFlash("down");
        }
        const timer = setTimeout(() => setPriceFlash(null), 800);
        return () => clearTimeout(timer);
      }
      setPrevLastPrice(marketState.last_price);
    }
  }, [marketState?.last_price]);

  // Funding countdown timer
  useEffect(() => {
    if (!marketState?.next_funding_time) return;

    const interval = setInterval(() => {
      const now = Date.now();
      const target = new Date(marketState.next_funding_time).getTime();
      const diff = Math.max(0, target - now);

      const hours = Math.floor(diff / (1000 * 60 * 60));
      const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
      const seconds = Math.floor((diff % (1000 * 60)) / 1000);

      setFundingCountdown(
        `${hours.toString().padStart(2, "0")}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`
      );
    }, 1000);

    return () => clearInterval(interval);
  }, [marketState?.next_funding_time]);

  const lastPrice = Number(marketState?.last_price) || 0;
  const markPrice = Number(marketState?.mark_price) || 0;
  const indexPrice = Number(marketState?.index_price) || 0;
  const basis = Number(marketState?.basis) || 0;
  const spread = Number(marketState?.spread) || 0;
  const fundingRate = Number(marketState?.funding_rate) || 0;
  const tradfiSession = String(marketState?.tradfi_session_state || "REGULAR");

  return (
    <header className="bg-surface border-b border-border sticky top-0 z-50 select-none">
      <div className="flex flex-col lg:flex-row items-center justify-between px-4 py-2 gap-3">
        {/* Left: Branding & Instrument */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded bg-gradient-to-br from-gold-500 to-amber-600 flex items-center justify-center font-bold text-black text-sm shadow-md shadow-gold-500/20">
              Au
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-100 tracking-wide text-sm">XAUUSDT</span>
                <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-card border border-border text-gold-400">
                  Perpetual
                </span>
              </div>
              <div className="text-[11px] text-slate-400 font-mono">Binance Futures</div>
            </div>
          </div>

          <div className="h-6 w-px bg-border mx-1 hidden sm:block" />

          {/* Core Telemetry Strip */}
          <div className="flex items-center gap-4 text-xs font-mono">
            <div>
              <span className="text-slate-400 block text-[10px]">LAST</span>
              <span
                className={`text-sm font-bold transition-colors ${
                  priceFlash === "up" ? "text-bull-400" : priceFlash === "down" ? "text-bear-400" : "text-slate-100"
                }`}
              >
                ${(lastPrice ?? 0).toFixed(2)}
              </span>
            </div>

            <div>
              <span className="text-slate-400 block text-[10px]">MARK</span>
              <span className="text-slate-200">${(markPrice ?? 0).toFixed(2)}</span>
            </div>

            <div>
              <span className="text-slate-400 block text-[10px]">INDEX</span>
              <span className="text-slate-300">${(indexPrice ?? 0).toFixed(2)}</span>
            </div>

            <div className="hidden md:block">
              <span className="text-slate-400 block text-[10px]">BASIS</span>
              <span className={(basis ?? 0) >= 0 ? "text-bull-400" : "text-bear-400"}>
                {(basis ?? 0) >= 0 ? "+" : ""}
                {(basis ?? 0).toFixed(2)}
              </span>
            </div>

            <div className="hidden md:block">
              <span className="text-slate-400 block text-[10px]">SPREAD</span>
              <span className="text-slate-200">${(spread ?? 0).toFixed(2)}</span>
            </div>
          </div>
        </div>

        {/* Center: Session Status & Funding Clock */}
        <div className="flex items-center gap-4 text-xs font-mono">
          <div className="flex items-center gap-1.5 bg-card px-2.5 py-1 rounded border border-border">
            <Clock className="w-3.5 h-3.5 text-gold-400" />
            <span className="text-slate-400 text-[10px]">FUNDING (8H):</span>
            <span className={(fundingRate ?? 0) >= 0 ? "text-bull-400 font-medium" : "text-bear-400 font-medium"}>
              {((fundingRate ?? 0) * 100).toFixed(4)}%
            </span>
            <span className="text-slate-500 text-[11px] ml-1">in {fundingCountdown}</span>
          </div>

          <div className="flex items-center gap-1.5 bg-card px-2.5 py-1 rounded border border-border">
            <Activity className="w-3.5 h-3.5 text-blue-400" />
            <span className="text-slate-400 text-[10px]">CME SESSION:</span>
            <span
              className={`font-semibold text-[11px] ${
                tradfiSession === "REGULAR" ? "text-bull-400" : "text-gold-400"
              }`}
            >
              {tradfiSession}
            </span>
          </div>
        </div>

        {/* Right: Workspace Tabs & Connection Status */}
        <div className="flex items-center gap-3">
          <nav className="flex items-center bg-card rounded p-0.5 border border-border">
            <button
              onClick={() => onTabChange("terminal")}
              className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                activeTab === "terminal"
                  ? "bg-gold-500 text-black shadow font-semibold"
                  : "text-slate-300 hover:text-white hover:bg-slate-800"
              }`}
            >
              Terminal
            </button>
            <button
              onClick={() => onTabChange("signals")}
              className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                activeTab === "signals"
                  ? "bg-gold-500 text-black shadow font-semibold"
                  : "text-slate-300 hover:text-white hover:bg-slate-800"
              }`}
            >
              Signals
            </button>
            <button
              onClick={() => onTabChange("backtest")}
              className={`px-3 py-1 rounded text-xs font-medium transition-all ${
                activeTab === "backtest"
                  ? "bg-gold-500 text-black shadow font-semibold"
                  : "text-slate-300 hover:text-white hover:bg-slate-800"
              }`}
            >
              Backtesting
            </button>
          </nav>

          <div className="flex items-center gap-1 text-[11px] font-mono pl-1">
            {connectionStatus === "OPEN" ? (
              <span className="flex items-center gap-1 text-bull-400 bg-bull-500/10 border border-bull-500/20 px-2 py-0.5 rounded">
                <Wifi className="w-3 h-3 animate-pulse" /> LIVE
              </span>
            ) : connectionStatus === "CONNECTING" ? (
              <span className="flex items-center gap-1 text-gold-400 bg-gold-500/10 border border-gold-500/20 px-2 py-0.5 rounded">
                <Activity className="w-3 h-3 animate-spin" /> CONNECTING
              </span>
            ) : (
              <span className="flex items-center gap-1 text-bear-400 bg-bear-500/10 border border-bear-500/20 px-2 py-0.5 rounded">
                <WifiOff className="w-3 h-3" /> REST FALLBACK
              </span>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
