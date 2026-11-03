# PROJECT SPECIFICATION

## Binance XAUUSDT Market Intelligence System

**Version:** 1.0
**Status:** Fixed architectural target
**Development environment:** Google Cloud VM + Antigravity CLI
**Market:** Binance USDⓈ-M Futures
**Instrument:** XAUUSDT TradFi Perpetual
**Purpose:** Market research, directional analysis and trade setup identification

---

## 1. PROJECT MISSION

Build a reliable, explainable and historically validated financial market intelligence application dedicated exclusively to Binance XAUUSDT.

The application must continuously analyze the gold perpetual futures market, identify bullish and bearish conditions, recognize potential trading opportunities and present the analysis through a professional web dashboard.

The application must prioritize analytical accuracy, data integrity, transparency and validation over the number of indicators or features.

This is a research and decision-support system, NOT an automated trading bot.

Automated order placement must never be implemented.

## 2. FIXED ARCHITECTURAL PRINCIPLES

The following principles are mandatory.

1. Binance is the exclusive exchange and market data provider.
2. XAUUSDT is the only instrument analyzed.
3. Use Binance USDⓈ-M Futures TradFi perpetual, not Spot.
4. Verify the exact instrument and availability before implementation and at runtime.
5. Never silently substitute another symbol or market.
6. Use a modular monolith architecture.
7. Maintain one authoritative implementation of each analytical calculation.
8. Separate data collection, validation, analysis, decisions, backtesting and presentation.
9. The live engine and historical simulation engine must share the same analytical definitions.
10. Every signal must be explainable and reproducible.
11. Historical signals must never repaint.
12. No lookahead bias, future leakage or fabricated historical data.
13. Never confuse a directional score with a statistical probability.
14. Never generate confirmed signals using incomplete candles.
15. When evidence is insufficient, report NEUTRAL or DATA UNAVAILABLE.

## 3. FIXED TECHNOLOGY STACK

Backend:

* Python
* FastAPI
* pandas
* NumPy
* PostgreSQL

Market data:

* Binance USDⓈ-M Futures REST API
* Binance Futures WebSocket streams

Frontend:

* React
* TypeScript
* Vite
* Lightweight Charts

Infrastructure:

* Existing Google Cloud VM
* Linux
* Docker Compose where appropriate
* Nginx or Caddy
* HTTPS

Avoid unnecessary technologies and dependencies.

Do not introduce microservices, Kafka, Kubernetes or additional databases without a demonstrated technical requirement.

## 4. BINANCE DATA INFRASTRUCTURE

Use Binance USDⓈ-M Futures endpoints.

Instrument verification:

* `/fapi/v1/exchangeInfo`

Market data:

* `/fapi/v1/klines`
* `/fapi/v1/ticker/price`
* `/fapi/v1/premiumIndex`
* `/fapi/v1/markPriceKlines`
* `/fapi/v1/indexPriceKlines`
* `/fapi/v1/depth`
* `/fapi/v1/fundingRate`
* `/fapi/v1/constituents`
* `/fapi/v1/time`

Implement WebSocket market streams for live data.

Verify the currently documented endpoint availability, request limits and applicable contract specifications before implementation.

Distinguish:

* Contract price.
* Mark price.
* Index price.

Monitor contract/index divergence.

Account for regular market hours, pre-market, after-hours, daily maintenance and inactive underlying-market periods.

Do not interpret frozen index prices or smoothed mark prices as normal underlying gold price discovery.

Contract volume must be identified as Binance-specific activity, not global gold-market volume.

Implement:

* Historical data download.
* Incremental synchronization.
* Candle validation.
* Duplicate detection.
* Missing-candle recovery.
* WebSocket reconnection.
* Server-time synchronization.
* Data freshness monitoring.

Use one-minute historical candles as the initial foundation, subject to actual availability.

Generate higher timeframes from validated lower-timeframe data where appropriate and reconcile against native exchange candles.

Store all timestamps in UTC.

## 5. ANALYTICAL INFRASTRUCTURE

Implement independently testable modules.

### A. Trend analysis

* EMA 20
* EMA 50
* EMA 100
* EMA 200
* ADX
* Trend strength
* Trend direction

### B. Momentum analysis

* RSI
* MACD
* Rate of Change
* Momentum divergence

### C. Volatility analysis

* ATR
* Bollinger Bands
* Volatility expansion
* Volatility contraction
* Historical volatility percentile

### D. Volume analysis

* Relative volume
* Volume expansion
* Taker buy/sell ratio
* Buying and selling pressure proxies

### E. Market structure

* Higher High
* Higher Low
* Lower High
* Lower Low
* Break of Structure
* Change of Character
* Swing highs and lows
* Trend continuation and reversal

### F. Liquidity analysis

* Order-book imbalance
* Bid/ask spread
* Liquidity concentration
* Large visible order clusters
* Liquidity sweep detection

Order-book observations must be timestamped. Never assume displayed liquidity will remain available.

### G. Price action

* Rejection candles
* Engulfing patterns
* Breakouts
* Retests
* Reversal patterns
* Continuation patterns

### H. Support and resistance

* Swing-based levels
* Repeated reaction zones
* Volume-based levels where data supports them
* VWAP
* Dynamic support and resistance

Every indicator must have:

* Documented formula.
* Defined input data.
* Defined calculation convention.
* Automated tests.
* Historical/live consistency.

Avoid double-counting correlated indicators.

## 6. MULTI-TIMEFRAME ANALYSIS

Primary timeframes:

1D, 4H, 1H, 15M and 5M.

Responsibilities:

* 1D: Major market direction.
* 4H: Primary trend.
* 1H: Setup identification.
* 15M: Confirmation.
* 5M: Entry refinement.

Secondary analytical intervals may include 1M, 30M and 2H.

All timeframe calculations must use correctly aligned candle boundaries.

No unfinished higher-timeframe candle may be treated as completed confirmation.

Clearly distinguish countertrend setups from trend-aligned setups.

## 7. DECISION ENGINE

Implement two separate engines.

### Engine A: Market Direction

Possible outputs:

* BULLISH
* POTENTIAL BULLISH
* NEUTRAL
* POTENTIAL BEARISH
* BEARISH

Initial scoring weights:

* Market structure: 25%
* Multi-timeframe trend: 20%
* Momentum: 15%
* Volume: 15%
* Liquidity: 10%
* Volatility and price action: 15%

Treat these as initial configurable engineering parameters.

Calculate bullish and bearish evidence independently.

Do not force bullish and bearish scores to total 100.

Missing data must not be interpreted as neutral evidence.

Apply data-quality and confirmation requirements before publishing confirmed direction.

Every assessment must explain:

* Supporting evidence.
* Contradicting evidence.
* Timeframe alignment.
* Relevant market conditions.
* Important price levels.
* Invalidating conditions.
* Data quality.
* Calculation methodology version.

Directional scores must not be represented as probabilities.

### Engine B: Trade Setup Identification

Possible outputs:

* NO SETUP
* POTENTIAL LONG
* CONFIRMED LONG
* POTENTIAL SHORT
* CONFIRMED SHORT
* INVALIDATED
* EXPIRED

A directional bias does not automatically create a valid trade setup.

Every setup must include:

* Direction.
* Setup type.
* Entry zone.
* Confirmation requirements.
* Stop-loss.
* Target 1.
* Target 2.
* Target 3.
* Risk/reward.
* Expiration.
* Invalidation conditions.
* Supporting evidence.
* Timestamp.

Use market structure and ATR to determine appropriate levels.

Account for estimated fees, spread, slippage and funding when evaluating trade scenarios.

Do not generate setups when risk/reward or data-quality requirements are not satisfied.

## 8. HISTORICAL VALIDATION

Build a trustworthy backtesting engine.

Mandatory requirements:

* No lookahead bias.
* No future leakage.
* No repainting.
* No retrospective signal generation.
* No unrealistic execution assumptions.
* Realistic trading costs.
* Chronological data processing.
* Independent out-of-sample evaluation.
* Walk-forward validation.

The backtester and live engine must share the same calculation and decision modules.

Record the methodology version for every historical simulation.

Measure:

* Precision.
* Recall.
* Win rate.
* Profit factor.
* Expectancy.
* Maximum drawdown.
* Maximum adverse excursion.
* Maximum favorable excursion.
* Long performance.
* Short performance.
* Performance by timeframe.
* Performance by market regime.

Build a separate directional signal evaluator.

Evaluate signal outcomes over predefined future horizons such as 5, 10, 20 and 50 candles.

Evaluate whether favorable movement occurred before adverse movement.

Keep directional prediction accuracy separate from simulated trade profitability.

Do not claim statistically meaningful accuracy without sufficient out-of-sample evidence.

Never fabricate pre-listing XAUUSDT contract history.

## 9. DATABASE

Use PostgreSQL.

Initial tables:

* `market_metadata`
* `ohlcv_candles`
* `live_market_state`
* `mark_index_prices`
* `orderbook_snapshots`
* `funding_history`
* `indicator_snapshots`
* `structure_events`
* `market_analysis`
* `trade_setups`
* `signal_outcomes`
* `backtest_runs`
* `backtest_metrics`
* `system_health`

Use appropriate indexes and unique constraints.

Maintain immutable historical signal records.

Separate raw data, calculated data and analytical decisions.

Use database migrations for schema changes.

## 10. BACKEND API

Implement versioned REST endpoints.

* `GET /api/v1/market/overview`
* `GET /api/v1/market/candles`
* `GET /api/v1/market/prices`
* `GET /api/v1/analysis/current`
* `GET /api/v1/analysis/timeframes`
* `GET /api/v1/analysis/evidence`
* `GET /api/v1/setups/current`
* `GET /api/v1/setups/history`
* `GET /api/v1/signals/history`
* `GET /api/v1/backtests`
* `GET /api/v1/system/health`

Implement WebSocket updates for:

* Market prices.
* Current candles.
* Analysis.
* Trade setups.
* System health.

The backend must remain the single source of analytical truth.

## 11. WEB APPLICATION

Build six principal sections.

1. Market Overview
2. Technical Analysis
3. Market Intelligence
4. Trade Setups
5. Signal History
6. Backtesting and Performance

The interface must provide:

* Live price information.
* Candlestick charts.
* Timeframe selection.
* Bullish and bearish evidence.
* Directional scoring.
* Key price levels.
* Entry and invalidation zones.
* Signal history.
* Historical performance.
* Data connection status.
* Market-hour status.

Use a professional dark-first financial trading interface.

Prioritize desktop usability while maintaining mobile responsiveness.

Do not hardcode market prices, signals or analysis into the frontend.

## 12. INFRASTRUCTURE AND SECURITY

Run the system on the existing Google Cloud VM.

Optimize:

* CPU usage.
* Memory consumption.
* Network traffic.
* Historical data caching.
* Database queries.
* WebSocket subscriptions.

Use HTTPS and authentication.

Never expose database credentials or secret values to the browser.

Use public Binance market data without trading permissions.

The application must have no order execution functionality.

Implement logging, backups, health checks and automatic service recovery.

## 13. DEVELOPMENT PROCESS

Implement in controlled phases.

* **Phase 1:** Instrument verification and data infrastructure.
* **Phase 2:** Analytical calculation modules.
* **Phase 3:** Market structure and multi-timeframe analysis.
* **Phase 4:** Decision and trade setup engines.
* **Phase 5:** Backtesting and validation.
* **Phase 6:** Web dashboard.
* **Phase 7:** Production deployment and hardening.

Each phase must be independently testable.

Do not proceed to the next phase until the current phase passes its acceptance tests.

## 14. ANTIGRAVITY ENGINEERING RULES

Before modifying any project files:

* Inspect the existing repository.
* Understand the current architecture.
* Identify existing functionality.
* Identify technical debt and dependencies.
* Compare the current implementation against this specification.
* Present a proposed implementation plan.

Never rewrite functioning modules without a technical justification.

Do not introduce unnecessary abstraction or dependencies.

Do not create duplicated calculations.

Do not hide errors through broad exception handling.

Do not silently ignore missing data.

Do not claim tests passed without actually running them.

Do not claim a feature is complete if only its interface has been implemented.

Every implementation phase must include:

* Changed files.
* Technical explanation.
* Tests executed.
* Test results.
* Known limitations.
* Remaining work.

Prioritize correctness over implementation speed.

## 15. FINAL ACCEPTANCE STANDARD

The project is complete only when:

1. Binance XAUUSDT instrument verification works.
2. Historical and live market data are reliable.
3. Data-integrity checks are operational.
4. Analytical modules pass automated tests.
5. Multi-timeframe analysis works correctly.
6. Bullish and bearish decisions are explainable.
7. Trade setups have traceable evidence and invalidation.
8. Historical simulation is free from known lookahead bias.
9. Out-of-sample performance is reported honestly.
10. The web dashboard receives live backend updates.
11. The application recovers from data connection failures.
12. No automated trading functionality exists.

---

This specification is the permanent architectural target.

Any proposed deviation must be explained and approved before implementation.
