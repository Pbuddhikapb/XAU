import type {
  BacktestRun,
  BacktestRunDetail,
  Candle,
  CurrentSetupsResponse,
  DirectionAnalysis,
  HorizonSignalRecord,
  IndicatorSnapshot,
  MarketOverview,
  StructureEvent,
  StructureZone,
  TradeSetup,
} from "../types";

const API_BASE = "";

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const errorText = await res.text();
    throw new Error(`API error ${res.status}: ${errorText || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  async getMarketOverview(): Promise<MarketOverview> {
    const res = await fetch(`${API_BASE}/api/v1/market/overview`);
    return handleResponse<MarketOverview>(res);
  },

  async getCandles(timeframe: string = "1h", limit: number = 250): Promise<Candle[]> {
    const res = await fetch(`${API_BASE}/api/v1/market/candles?timeframe=${timeframe}&limit=${limit}`);
    return handleResponse<Candle[]>(res);
  },

  async getIndicators(timeframe: string = "1h", limit: number = 100): Promise<IndicatorSnapshot[]> {
    const res = await fetch(`${API_BASE}/api/v1/analytics/indicators?timeframe=${timeframe}&limit=${limit}`);
    return handleResponse<IndicatorSnapshot[]>(res);
  },

  async getStructureLevels(timeframe: string = "1h"): Promise<StructureZone[]> {
    const res = await fetch(`${API_BASE}/api/v1/structure/levels?timeframe=${timeframe}`);
    return handleResponse<StructureZone[]>(res);
  },

  async getStructureEvents(timeframe: string = "1h", limit: number = 50): Promise<StructureEvent[]> {
    const res = await fetch(`${API_BASE}/api/v1/structure/events?timeframe=${timeframe}&limit=${limit}`);
    return handleResponse<StructureEvent[]>(res);
  },

  async getCurrentAnalysis(): Promise<DirectionAnalysis> {
    const res = await fetch(`${API_BASE}/api/v1/analysis/current`);
    return handleResponse<DirectionAnalysis>(res);
  },

  async getCurrentSetups(): Promise<CurrentSetupsResponse> {
    const res = await fetch(`${API_BASE}/api/v1/setups/current`);
    return handleResponse<CurrentSetupsResponse>(res);
  },

  async getSetupsHistory(params?: { status?: string; direction?: string; limit?: number }): Promise<TradeSetup[]> {
    const query = new URLSearchParams();
    if (params?.status) query.append("status", params.status);
    if (params?.direction) query.append("direction", params.direction);
    if (params?.limit) query.append("limit", params.limit.toString());
    const res = await fetch(`${API_BASE}/api/v1/setups/history?${query.toString()}`);
    return handleResponse<TradeSetup[]>(res);
  },

  async getSignalsHistory(params?: { horizon?: number; outcome?: string; limit?: number }): Promise<HorizonSignalRecord[]> {
    const query = new URLSearchParams();
    if (params?.horizon) query.append("horizon", params.horizon.toString());
    if (params?.outcome) query.append("outcome", params.outcome);
    if (params?.limit) query.append("limit", params.limit.toString());
    const res = await fetch(`${API_BASE}/api/v1/signals/history?${query.toString()}`);
    return handleResponse<HorizonSignalRecord[]>(res);
  },

  async getBacktestRuns(limit: number = 20): Promise<BacktestRun[]> {
    const res = await fetch(`${API_BASE}/api/v1/backtests?limit=${limit}`);
    return handleResponse<BacktestRun[]>(res);
  },

  async getBacktestDetail(runId: string): Promise<BacktestRunDetail> {
    const res = await fetch(`${API_BASE}/api/v1/backtests/${runId}`);
    return handleResponse<BacktestRunDetail>(res);
  },

  async runBacktest(payload: {
    start_time: string;
    end_time: string;
    initial_balance?: number;
    friction_pct?: number;
    slippage_pct?: number;
  }): Promise<BacktestRunDetail> {
    const res = await fetch(`${API_BASE}/api/v1/backtests/run`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return handleResponse<BacktestRunDetail>(res);
  },

  async getHealth(): Promise<Record<string, unknown>> {
    const res = await fetch(`${API_BASE}/api/v1/system/health`);
    return handleResponse<Record<string, unknown>>(res);
  },
};
