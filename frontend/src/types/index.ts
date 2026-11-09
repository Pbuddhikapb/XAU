/**
 * TypeScript Data Models matching FastAPI REST and WebSocket contracts.
 */

export interface MarketMetadata {
  pair: string;
  contract_type: string;
  tick_size: number;
  step_size: number;
  min_notional: number;
  is_active: boolean;
}

export interface LiveMarketState {
  last_price: number;
  mark_price: number;
  index_price: number;
  basis: number;
  funding_rate: number;
  next_funding_time: string;
  best_bid: number;
  best_ask: number;
  spread: number;
  tradfi_session_state: string;
  last_update: string;
}

export interface MarketOverview {
  symbol: string;
  metadata: MarketMetadata | null;
  live_state: LiveMarketState | null;
}

export interface Candle {
  open_time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  close_time: number;
  is_confirmed: boolean;
}

export interface IndicatorSnapshot {
  candle_time: string;
  timeframe: string;
  ema_20?: number | null;
  ema_50?: number | null;
  ema_100?: number | null;
  ema_200?: number | null;
  adx?: number | null;
  trend_strength?: number | null;
  rsi_14?: number | null;
  macd_val?: number | null;
  macd_signal?: number | null;
  macd_hist?: number | null;
  atr_14?: number | null;
  bb_upper?: number | null;
  bb_middle?: number | null;
  bb_lower?: number | null;
  volatility_percentile?: number | null;
  relative_volume?: number | null;
}

export interface StructureZone {
  zone_type?: "SUPPORT" | "RESISTANCE";
  level_type?: "SUPPORT" | "RESISTANCE";
  level_center?: number;
  level_min?: number;
  level_max?: number;
  price_min?: number;
  price_max?: number;
  touches_count?: number;
  touch_count?: number;
  strength?: number;
  is_active?: boolean;
}

export interface StructureEvent {
  event_type: string;
  price: number;
  invalidated_level?: number | null;
  event_time: string;
  confirmed_candle_time: string;
  timeframe: string;
  metadata?: Record<string, unknown> | null;
}

export interface EvidenceItem {
  category?: string;
  factor?: string;
  indicator?: string;
  description: string;
  weight?: number;
  score_contribution?: number;
}

export interface InvalidationConditions {
  soft_invalidation: string;
  hard_invalidation: string;
  soft_level?: number | null;
  hard_level?: number | null;
}

export interface DirectionAnalysis {
  symbol: string;
  direction: "BULLISH" | "BEARISH" | "NEUTRAL";
  bullish_score: number;
  bearish_score: number;
  score_label: string;
  data_quality_score: number;
  cme_session_active: boolean;
  staleness_gate_passed: boolean;
  timeframe_alignment: Record<string, string>;
  supporting_evidence: EvidenceItem[];
  contradicting_evidence: EvidenceItem[];
  key_levels: Record<string, number | null>;
  invalidation_conditions: InvalidationConditions;
  assessment_time: string;
  methodology_version: string;
}

export interface TradeSetup {
  id: string;
  symbol: string;
  setup_type: string;
  direction: "LONG" | "SHORT";
  status: "POTENTIAL" | "CONFIRMED" | "TRIGGERED" | "TARGET_1_HIT" | "TARGET_2_HIT" | "TARGET_3_HIT" | "STOPPED_OUT" | "STOPPED_OUT_BREAKEVEN" | "INVALIDATED" | "EXPIRED_UNTRIGGERED";
  timeframe: string;
  entry_price_min: number;
  entry_price_max: number;
  stop_loss: number;
  active_stop_loss: number;
  breakeven_locked: boolean;
  target_1: number;
  target_2: number;
  target_3: number;
  risk_reward_ratio: number;
  created_at: string;
  triggered_at?: string | null;
  resolved_at?: string | null;
  outcome?: string | null;
  realized_pnl_pct?: number | null;
  invalidation_reason?: string | null;
}

export interface NoSetupResponse {
  symbol: string;
  status: "NO_SETUP";
  reason: string;
  data_quality_score: number;
  cme_session_active: boolean;
  timestamp: string;
  active_setups: TradeSetup[];
}

export interface CurrentSetupsResponse {
  symbol: string;
  status: string;
  active_count: number;
  setups: TradeSetup[];
  reason?: string;
  data_quality_score?: number;
  cme_session_active?: boolean;
}

export interface HorizonSignalRecord {
  id: string;
  signal_time: string;
  symbol: string;
  direction: "BULLISH" | "BEARISH";
  primary_timeframe: string;
  direction_score: number;
  horizon_candles: number;
  target_evaluation_time: string;
  initial_price: number;
  max_favorable_price: number;
  max_adverse_price: number;
  final_price: number;
  mfe_points: number;
  mae_points: number;
  favorable_first: boolean;
  outcome: string;
}

export interface BacktestRun {
  run_id: string;
  symbol: string;
  start_time: string;
  end_time: string;
  initial_balance: number;
  execution_mode: string;
  status: string;
  created_at: string;
  notes?: string | null;
}

export interface SimulatedTrade {
  trade_id: string;
  setup_id: string;
  direction: "LONG" | "SHORT";
  setup_type: string;
  entry_time: string;
  entry_price: number;
  exit_time: string;
  exit_price: number;
  exit_reason: string;
  pnl_points: number;
  pnl_pct: number;
  pnl_dollars: number;
  r_multiple: number;
  commission_paid: number;
  slippage_paid: number;
}

export interface BacktestRunDetail {
  run: BacktestRun;
  metrics: {
    win_rate_pct: number;
    profit_factor: number;
    expectancy_dollars: number;
    expectancy_r: number;
    max_drawdown_pct: number;
    max_drawdown_dollars: number;
    sharpe_ratio: number;
    total_trades: number;
    winning_trades: number;
    losing_trades: number;
    breakeven_trades: number;
    net_pnl_dollars: number;
    net_pnl_pct: number;
    gross_profit_dollars: number;
    gross_loss_dollars: number;
    average_trade_duration_bars: number;
    long_performance: Record<string, number>;
    short_performance: Record<string, number>;
    regime_performance: Record<string, Record<string, number>>;
    timeframe_performance: Record<string, Record<string, number>>;
    in_sample_metrics: Record<string, number>;
    out_of_sample_metrics: Record<string, number>;
    performance_degradation_pct: number;
  } | null;
  trades: SimulatedTrade[];
  horizon_evaluations: Record<string, Record<string, number>>;
}
