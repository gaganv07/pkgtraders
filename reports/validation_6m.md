# Extended Historical Validation — 6 Months
**Opening Range Breakout (P4) Backtest Performance**

## Execution Metrics

| Metric | Value |
|:---|---:|
| **Total Trades** | 82 |
| **Win Rate** | 8.54% |
| **Profit Factor** | 0.51 |
| **Expectancy (R)** | -0.4417 R |
| **Net Profit** | $-1,810.98 |
| **Sharpe Ratio** | -3.766 |
| **Sortino Ratio** | -180.333 |
| **Recovery Factor** | -1.0 |
| **CAGR** | -33.33% |
| **Maximum Drawdown** | 18.11% |
| **Average Holding Time** | 25.1 mins |

---

## Technical Limitations & Data Disclaimers
1. **M5 History Capping**: The broker terminal enforces a limit of 90,000 bars for the M5 timeframe (approx. 10.4 months). In compliance with certification rules, no synthetic ATR values were generated. Consequently, backtests beyond 10.4 months are capped at the maximum available M5 history boundaries.
2. **Transaction Cost Modelling**: Slippage is set to baseline 0 ticks; commissions and spreads are modeled using actual raw broker specifications.
