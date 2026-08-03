# Module 11 — Market Edge Ranking

Unified ranking of all discovered market behaviours by composite edge score.
Edge Score = weighted combination of Sharpe, expected return, win rate, sample size, and statistical significance.

## Top 25 Market Edges

| Rank | Edge | Category | N | Avg Return (R) | Win % | Sharpe | p-value | Edge Score |
|:---|:---|:---|---:|---:|---:|---:|---:|---:|
| 1 | EMA Align=BULL | EMA | 88,233 | +1.4493 | 68.3% | +0.361 | 0.0000✅ | 31.372 |
| 2 | EURUSD | Session=NEW_YORK | Session | 4,160 | +0.4522 | 55.3% | +0.099 | 0.0000✅ | 6.836 |
| 3 | USDJPY | Session=LONDON | Session | 5,200 | +0.4228 | 53.3% | +0.093 | 0.0000✅ | 6.274 |
| 4 | EURUSD | Session=OVERLAP | Session | 4,160 | +0.3567 | 52.9% | +0.096 | 0.0000✅ | 5.486 |
| 5 | EURUSD | Session=OFF | Session | 4,160 | +0.3362 | 54.7% | +0.079 | 0.0000✅ | 5.331 |
| 6 | ATR Pct 80–100% | ATR | 36,606 | +0.2562 | 52.2% | +0.069 | 0.0000✅ | 5.000 |
| 7 | EMA Align=BEAR | EMA | 84,921 | -1.4008 | 32.0% | -0.352 | 0.0000✅ | 4.165 |
| 8 | EURUSD | Overall | Symbol | 24,960 | +0.2295 | 53.3% | +0.041 | 0.0000✅ | 4.151 |
| 9 | Session=OVERLAP & Regime=TRENDING | Combo | 1,396 | +0.3396 | 53.7% | +0.074 | 0.0061✅ | 4.146 |
| 10 | GBPUSD | Session=OVERLAP | Session | 4,160 | +0.2073 | 52.4% | +0.062 | 0.0001✅ | 3.425 |
| 11 | Session=OVERLAP & Regime=EXPANSION | Combo | 4,061 | +0.1904 | 52.9% | +0.055 | 0.0005✅ | 3.205 |
| 12 | USDJPY | Session=OFF | Session | 4,160 | +0.2139 | 51.4% | +0.056 | 0.0003✅ | 3.191 |
| 13 | USDJPY | Overall | Symbol | 24,960 | +0.1587 | 51.5% | +0.037 | 0.0000✅ | 2.892 |
| 14 | EURUSD | Session=ASIA | Session | 7,280 | +0.2120 | 52.6% | +0.031 | 0.0092✅ | 2.853 |
| 15 | US30 | Session=OVERLAP | Session | 4,160 | +0.1911 | 50.7% | +0.051 | 0.0011✅ | 2.746 |
| 16 | All Symbols | Regime=RANGE | Regime | 5,390 | +0.1696 | 52.2% | +0.042 | 0.0022✅ | 2.715 |
| 17 | GBPUSD | Session=LONDON | Session | 5,200 | +0.1581 | 50.8% | +0.044 | 0.0015✅ | 2.403 |
| 18 | Session=LONDON & Regime=STRONG_TREND | Combo | 10,216 | +0.1239 | 50.3% | +0.032 | 0.0013✅ | 1.924 |
| 19 | USDJPY | Session=OVERLAP | Session | 4,160 | +0.1444 | 52.8% | +0.035 | 0.0245✅ | 1.843 |
| 20 | BTCUSD | Session=ASIA | Session | 7,280 | +0.1820 | 51.0% | +0.026 | 0.0260✅ | 1.817 |
| 21 | US30 | Overall | Symbol | 24,960 | +0.0665 | 50.6% | +0.017 | 0.0073✅ | 1.142 |
| 22 | US30 | Session=ASIA | Session | 7,280 | +0.1057 | 51.0% | +0.024 | 0.0367✅ | 1.069 |
| 23 | All Symbols | Regime=COMPRESSION | Regime | 43,767 | -0.0777 | 50.1% | -0.015 | 0.0021✅ | 0.569 |
| 24 | EURUSD | Session=LONDON | Session | 5,200 | -0.1112 | 51.9% | -0.018 | 0.2065— | 0.529 |
| 25 | EMA Align=FLAT | EMA | 1,566 | -0.0551 | 54.6% | -0.008 | 0.7554— | 0.524 |

## Edges to Avoid (Lowest Scores)

| Edge | Sharpe | Win % | p-value |
|:---|---:|---:|---:|
| XAUUSD | Overall | -0.012 | 49.8% | 0.0643 |
| NAS100 | Session=LONDON | -0.030 | 49.1% | 0.0329 |
| ATR Pct 40–60% | -0.009 | 49.5% | 0.1339 |
| NAS100 | Overall | -0.035 | 48.5% | 0.0000 |
| ATR Pct 60–80% | -0.013 | 48.9% | 0.0398 |
| USDJPY | Session=NEW_YORK | -0.012 | 49.2% | 0.4483 |
| All Symbols | Regime=EXPANSION | -0.007 | 49.3% | 0.2804 |
| US30 | Session=NEW_YORK | -0.006 | 49.1% | 0.6962 |
| NAS100 | Session=ASIA | -0.030 | 47.5% | 0.0097 |
| NAS100 | Session=NEW_YORK | -0.099 | 46.8% | 0.0000 |