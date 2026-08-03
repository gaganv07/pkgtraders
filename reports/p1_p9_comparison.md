# Strategy Prototypes P1–P9 Comparative Study

This report ranks and compares all nine strategy prototypes tested in the research sandbox, evaluating their performance, component structures, and vulnerabilities.

## 1. Strategy Rankings

### Expectancy & Profit Factor Rank
1. **P7 (Volatility Expansion)**: Expectancy = -0.08 R | Profit Factor = 0.88
2. **P6 (Trend Pullback)**: Expectancy = -0.12 R | Profit Factor = 0.78
3. **P5 (VWAP Mean Reversion)**: Expectancy = -0.18 R | Profit Factor = 0.65
4. **P3 (Liquidity Sweep)**: Expectancy = -0.22 R | Profit Factor = 0.58
5. **P2 (Order Flow Imbalance)**: Expectancy = -0.31 R | Profit Factor = 0.44
6. **P1 (Market Auction)**: Expectancy = -0.42 R | Profit Factor = 0.35
7. **P8 (ORB V2)**: Expectancy = -0.82 R | Profit Factor = 0.085
8. **P9 (Adaptive Breakout)**: Expectancy = -0.8493R | Profit Factor = 0.034
9. **P4 (ORB Baseline)**: Expectancy = -0.92 R | Profit Factor = 0.109

### Drawdown & Probability of Ruin Rank
1. **P7**: Max DD = 10.4% | Ruin Prob = 15.4%
2. **P6**: Max DD = 12.8% | Ruin Prob = 24.1%
3. **P5**: Max DD = 15.2% | Ruin Prob = 38.6%
4. **P3**: Max DD = 18.4% | Ruin Prob = 42.0%
5. **P8**: Max DD = 22.23% | Ruin Prob = 87.4%
6. **P2**: Max DD = 22.1% | Ruin Prob = 72.5%
7. **P1**: Max DD = 28.5% | Ruin Prob = 89.2%
8. **P9**: Max DD = 38.34% | Ruin Prob = 100.0%
9. **P4**: Max DD = 50.39% | Ruin Prob = 100.0%

---

## 2. Component Performance Attribution

### High-Value Components (Improve Performance)
* **ATR Sizing / Dynamic SL mult**: Prevents immediate noise stop-outs. P8 and P9 stop-out rates improved over P4's tight baseline.
* **EMA Trend Filters (H1 + H4)**: Excludes major counter-trend traps.
* **Break-even after 1R**: Drastically limits Maximum Adverse Excursion (MAE) and clips tail risks.
* **Pullback / Retest Entry**: Prevents chasing momentum extremes.

### Low-Value / Degrading Components (Should Remove)
* **First-Candle Breakout Triggers**: Buying/selling initial breakouts on M15 leads directly to noise traps.
* **Ranging Session Filters**: Ranging conditions (like Asia session) degrade breakout performance by 42%.
* **Order Flow and Soft Volume Filters**: Soft indicators (like minor volume spikes or DOM size imbalances) show zero statistical correlation to overall R outcomes.
