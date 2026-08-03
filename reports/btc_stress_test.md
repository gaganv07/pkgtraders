# BTCUSD Stress Testing Report
**Performance Under Extreme Spreads, Slippage, and Missing Trades**

## Stress Test Performance

| Scenario | Total Trades | Win Rate | Expectancy | Profit Factor | Max Drawdown | Net Profit |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| Baseline (Normal) | 2392 | 35.2% | +0.056R | 1.07 | 30.16% | $+673.96 |
| Double Spread (2.0x) | 2392 | 35.2% | +0.056R | 1.07 | 30.16% | $+673.96 |
| 5-tick Slippage | 2392 | 35.16% | +0.055R | 1.06 | 30.19% | $+611.88 |
| 20% Missed Trades | 2076 | 35.26% | +0.058R | 1.06 | 34.0% | $+716.49 |
| Latency Delay (Execution delay) | 2392 | 35.16% | +0.055R | 1.06 | 30.16% | $+613.65 |
