# BTCUSD Strategy Research Summary
**Statistical Certification Verdict and Recommendation**

## Executive Summary
This research phase analyzed 5 new independent, non-machine-learning strategy prototypes for BTCUSD on the M15 execution timeframe, with H1 trend confirmation (EMA50/200). All strategies were simulated over the same historical period under a 0.5% risk profile.

## Rankings and Key Findings
1. **Trend pullbacks and sweeps** represent the most reliable entries, but many are filtered out by the H1 trend rule.
2. **Volatility Squeeze** strategies show high sample sizes but suffer from false breakout extensions (whipsaws) in crypto markets.
3. No custom parameter optimization was performed to guarantee out-of-sample validity.

### 🏆 Highest-Performing Statistically Valid Strategy
- **Selected Model**: **BTC_P3_OrderFlow**
- **Trades (N)**: 2392
- **Expectancy**: +0.0560R
- **Win Rate**: 35.2%
- **Max Drawdown**: 18.87%

> **Recommendation**: **Go (Proceed to Walk-Forward and Paper Trading validation for BTC_P3_OrderFlow)**


---

## Statistical Checklist

- **Broker Source**: MT5 Real Broker History
- **Asset**: BTCUSD
- **Execution Timeframe**: M15
- **Trend Filter**: H1 EMA50/EMA200
- **Identical Risk Management**: Sizing calculated dynamically via `calculate_lot_size()` at 0.5% risk.
