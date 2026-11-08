# XAUUSDT Market Intelligence System: Institutional Invariants & Architecture Guidelines

This project implements an institutional-grade, zero-lookahead market intelligence and backtesting system for Binance Futures XAUUSDT. All code, engines, and UI layers must adhere strictly to these invariants:

## 1. Zero Lookahead & Temporal Boundary
* All analytical indicators, market structure evaluations, and regime filters must operate strictly on past bars (`shift(1)` / `close_time <= t_eval`).
* Pre-computed indicator tables for walk-forward backtests are permitted only when every underlying calculation is strictly retrospective and mathematically identical to tick-by-tick evaluation.

## 2. Conservative Intra-Bar Collision Resolution
* In multi-resolution or event-driven trade execution (e.g. 5M sub-bars), if the high and low of a single candle simultaneously intersect both the Stop Loss and Target Price (or Entry and Stop Loss), **Stop Loss always takes precedence**.
* Never assume favorable execution order within an ambiguous single candle.

## 3. Decoupled Horizon Evaluation vs. Setup Execution
* Directional forecasting quality (Engine A) must be evaluated across fixed horizons (5, 10, 20, 50 bars) independently of trade setup triggers or profitability (Engine B).
* `signal_outcomes` stores raw predictive accuracy (MFE, MAE, favorable-before-adverse) even when no setup was triggered or entered.

## 4. State Machine Terminal Immutability
* Trade setup lifecycle states `TARGET_3_HIT`, `EXPIRED_UNTRIGGERED`, and `INVALIDATED` are strictly terminal.
* Once terminal, subsequent candle evaluations must short-circuit immediately so that pullbacks to breakeven or stop levels cannot mutate the final outcome or override historical metrics.

## 5. Opposing Setup Auto-Invalidation on Directional Flip
* Whenever Engine A's primary direction flips (e.g., BULLISH to BEARISH or vice-versa), any active opposing setups (POTENTIAL or CONFIRMED) must be auto-invalidated immediately, regardless of whether a new opposing trade setup was produced on that candle.

## 6. Code Quality & Test Verification
* 100% test pass rate must be maintained across all suites before any commit.
* Strict typing (`mypy`) and linting (`ruff`) must produce zero errors and zero warnings.
