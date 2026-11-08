import React, { useEffect, useState } from "react";
import { TopBar } from "./components/TopBar";
import { TradingChart } from "./components/terminal/TradingChart";
import { EngineAPanel } from "./components/terminal/EngineAPanel";
import { EngineBPanel } from "./components/terminal/EngineBPanel";
import { SignalHistoryView } from "./components/signals/SignalHistoryView";
import { BacktestStudioView } from "./components/backtest/BacktestStudioView";
import { api } from "./services/api";
import { wsClient, type ConnectionStatus } from "./services/websocket";
import type {
  Candle,
  CurrentSetupsResponse,
  DirectionAnalysis,
  LiveMarketState,
  StructureEvent,
  StructureZone,
} from "./types";

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<string>("terminal");
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>("CONNECTING");

  // Terminal State
  const [marketState, setMarketState] = useState<LiveMarketState | null>(null);
  const [timeframe, setTimeframe] = useState<string>("1h");
  const [candles, setCandles] = useState<Candle[]>([]);
  const [structureLevels, setStructureLevels] = useState<StructureZone[]>([]);
  const [structureEvents, setStructureEvents] = useState<StructureEvent[]>([]);
  const [analysis, setAnalysis] = useState<DirectionAnalysis | null>(null);
  const [setupsResponse, setSetupsResponse] = useState<CurrentSetupsResponse | null>(null);
  const [isLoadingChart, setIsLoadingChart] = useState<boolean>(false);
  const [isLoadingAnalysis, setIsLoadingAnalysis] = useState<boolean>(false);

  // Subscribe to WebSocket status
  useEffect(() => {
    const unsubStatus = wsClient.onStatusChange((status) => {
      setConnectionStatus(status);
    });

    // Subscribe to real-time telemetry frames
    const unsubTicks = wsClient.subscribe("market_tick", (data: any) => {
      if (data) {
        setMarketState((prev) => ({
          ...(prev || {
            last_price: 0,
            mark_price: 0,
            index_price: 0,
            basis: 0,
            funding_rate: 0,
            next_funding_time: new Date().toISOString(),
            best_bid: 0,
            best_ask: 0,
            spread: 0,
            tradfi_session_state: "REGULAR",
            last_update: new Date().toISOString(),
          }),
          ...data,
        }));
      }
    });

    const unsubAnalysis = wsClient.subscribe("analysis_update", (data: any) => {
      if (data) setAnalysis(data);
    });

    const unsubSetups = wsClient.subscribe("setup_update", (data: any) => {
      if (data) setSetupsResponse(data);
    });

    return () => {
      unsubStatus();
      unsubTicks();
      unsubAnalysis();
      unsubSetups();
    };
  }, []);

  // Polling fallback & initial state load
  const loadMarketOverview = async () => {
    try {
      const overview = await api.getMarketOverview();
      if (overview.live_state) {
        setMarketState(overview.live_state);
      }
    } catch (err) {
      console.warn("Market overview fetch:", err);
    }
  };

  const loadCandlesAndStructure = async (tf: string) => {
    setIsLoadingChart(true);
    try {
      const [candleData, levelsData, eventsData] = await Promise.all([
        api.getCandles(tf, 250),
        api.getStructureLevels(tf).catch(() => []),
        api.getStructureEvents(tf, 40).catch(() => []),
      ]);
      setCandles(candleData);
      setStructureLevels(levelsData);
      setStructureEvents(eventsData);
    } catch (err) {
      console.error("Failed to load candles:", err);
    } finally {
      setIsLoadingChart(false);
    }
  };

  const loadDecisions = async () => {
    setIsLoadingAnalysis(true);
    try {
      const [analysisData, setupsData] = await Promise.all([
        api.getCurrentAnalysis().catch(() => null),
        api.getCurrentSetups().catch(() => null),
      ]);
      if (analysisData) setAnalysis(analysisData);
      if (setupsData) setSetupsResponse(setupsData);
    } catch (err) {
      console.error("Failed to load decisions:", err);
    } finally {
      setIsLoadingAnalysis(false);
    }
  };

  // Initial load
  useEffect(() => {
    loadMarketOverview();
    loadCandlesAndStructure(timeframe);
    loadDecisions();

    // 5-second polling loop for overview and analysis
    const interval = setInterval(() => {
      loadMarketOverview();
      loadDecisions();
    }, 5000);

    return () => clearInterval(interval);
  }, []);

  // On timeframe change
  const handleTimeframeChange = (newTf: string) => {
    setTimeframe(newTf);
    loadCandlesAndStructure(newTf);
  };

  const activeSetup = setupsResponse?.setups?.[0] ?? null;

  return (
    <div className="min-h-screen flex flex-col bg-background text-slate-100">
      {/* Persistent Top Bar */}
      <TopBar
        marketState={marketState}
        connectionStatus={connectionStatus}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />

      {/* Main Workspace Body */}
      <main className="flex-1 overflow-x-hidden">
        {activeTab === "terminal" && (
          <div className="p-3 lg:p-4 grid grid-cols-1 lg:grid-cols-12 gap-3 lg:gap-4 max-w-[1920px] mx-auto">
            {/* Chart Canvas Area */}
            <div className="lg:col-span-8 flex flex-col min-h-[560px]">
              <TradingChart
                candles={candles}
                timeframe={timeframe}
                onTimeframeChange={handleTimeframeChange}
                structureLevels={structureLevels}
                structureEvents={structureEvents}
                activeSetup={activeSetup}
                onRefresh={() => loadCandlesAndStructure(timeframe)}
                isLoading={isLoadingChart}
              />
            </div>

            {/* Engines Side Panel */}
            <div className="lg:col-span-4 space-y-3 lg:space-y-4 flex flex-col">
              <EngineAPanel analysis={analysis} isLoading={isLoadingAnalysis} />
              <EngineBPanel setupsResponse={setupsResponse} isLoading={isLoadingAnalysis} />
            </div>
          </div>
        )}

        {activeTab === "signals" && (
          <div className="max-w-[1920px] mx-auto">
            <SignalHistoryView />
          </div>
        )}

        {activeTab === "backtest" && (
          <div className="max-w-[1920px] mx-auto">
            <BacktestStudioView />
          </div>
        )}
      </main>
    </div>
  );
};
