# Strategy V2 Research Report
**Controlled Multi-Model Evaluation**
*Generated: 2026-06-27 11:12 UTC*

---

## Research Parameters

| Parameter | Value |
|:---|:---|
| Replay Window | 15 trading days |
| Symbols | XAUUSD, EURUSD, GBPUSD, USDJPY |
| Starting Balance | $10,000.00 |
| Risk Per Trade | 0.5% |
| Threshold | Strategy-specific confidence scores |
| Hard Guards | News blackout, max spread, drawdown limits |

---

## Executive Summary

| Metric | Value |
|:---|:---|
| Strategies tested | 7 |
| Strategies with positive expectancy | 1 |
| Best strategy | P4_OpeningRangeBreakout |
| Best expectancy | +0.3219 R |
| Best net PnL | $+180.53 |

---

## Ranked Results

| Rank | Strategy | Trades | Win Rate | Expectancy | PF | Sharpe | Sortino | Max DD | Net PnL | Rec |
|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1 | **P4_OpeningRangeBreakout** | 11 | 27.3% | +0.322R | 1.56 | 2.67 | 27.65 | 1.6% | $+180.53 | ✅ |
| 2 | **P6_TrendPullback** | 66 | 25.8% | -0.045R | 0.92 | -0.59 | -5.45 | 4.8% | $-173.62 | ❌ |
| 3 | **P3_LiquiditySweepReversal** | 109 | 22.9% | -0.108R | 0.92 | -0.59 | -4.94 | 8.2% | $-298.11 | ❌ |
| 4 | **P2_OrderFlowImbalance** | 298 | 34.2% | -0.061R | 0.85 | -1.12 | -4.07 | 21.3% | $-1,480.85 | ❌ |
| 5 | **P5_VWAPMeanReversion** | 0 | 0.0% | +0.000R | 0.00 | 0.00 | 0.00 | 0.0% | $+0.00 | ❌ |
| 6 | **P7_VolatilityExpansion** | 0 | 0.0% | +0.000R | 0.00 | 0.00 | 0.00 | 0.0% | $+0.00 | ❌ |
| 7 | **P1_MarketAuction** | 186 | 26.9% | -0.204R | 0.71 | -2.38 | -15.67 | 16.6% | $-1,649.32 | ❌ |

---

## Per-Strategy Analysis

### #1 — P4_OpeningRangeBreakout
**✅ POSITIVE EXPECTANCY — Recommended**

London session opening range (07:00–07:59 UTC). Trades the breakout above/below the OR with volume + EMA50/200 trend confirmation.

| Metric | Value |
|:---|---:|
| Trades | 11 |
| Win Rate | 27.3% |
| Expectancy | +0.3219 R |
| Profit Factor | 1.563 |
| Sharpe | 2.671 |
| Sortino | 27.652 |
| Max Drawdown | 1.60% |
| Net PnL | $+180.53 |
| Avg Holding | 53 min |
| Avg Confidence | 83.7 |
| Rank Score | 0.9620 |

### #2 — P6_TrendPullback
**❌ Negative Expectancy**

EMA50/200 golden/death cross trend + M15 pullback to EMA50 with above-average entry volume. High R:R (3:1) trend-following model.

| Metric | Value |
|:---|---:|
| Trades | 66 |
| Win Rate | 25.8% |
| Expectancy | -0.0446 R |
| Profit Factor | 0.916 |
| Sharpe | -0.592 |
| Sortino | -5.454 |
| Max Drawdown | 4.85% |
| Net PnL | $-173.62 |
| Avg Holding | 36 min |
| Avg Confidence | 73.6 |
| Rank Score | 0.4983 |

### #3 — P3_LiquiditySweepReversal
**❌ Negative Expectancy**

Stop-hunt detection. Enters against the sweep direction after price extends beyond a swing high/low and reverses with a commitment bar.

| Metric | Value |
|:---|---:|
| Trades | 109 |
| Win Rate | 22.9% |
| Expectancy | -0.1085 R |
| Profit Factor | 0.916 |
| Sharpe | -0.587 |
| Sortino | -4.937 |
| Max Drawdown | 8.24% |
| Net PnL | $-298.11 |
| Avg Holding | 73 min |
| Avg Confidence | 80.6 |
| Rank Score | 0.4337 |

### #4 — P2_OrderFlowImbalance
**❌ Negative Expectancy**

CVD trend direction + volume absorption. Enters in the direction of sustained cumulative delta with absorption confirmation.

| Metric | Value |
|:---|---:|
| Trades | 298 |
| Win Rate | 34.2% |
| Expectancy | -0.0614 R |
| Profit Factor | 0.855 |
| Sharpe | -1.121 |
| Sortino | -4.067 |
| Max Drawdown | 21.25% |
| Net PnL | $-1,480.85 |
| Avg Holding | 259 min |
| Avg Confidence | 72.5 |
| Rank Score | 0.4179 |

### #5 — P5_VWAPMeanReversion
**❌ Negative Expectancy**

Mean-reversion to session VWAP. Enters when price deviates ≥0.12% from VWAP with momentum turning back. Requires non-explosive regime.

| Metric | Value |
|:---|---:|
| Trades | 0 |
| Win Rate | 0.0% |
| Expectancy | +0.0000 R |
| Profit Factor | 0.000 |
| Sharpe | 0.000 |
| Sortino | 0.000 |
| Max Drawdown | 0.00% |
| Net PnL | $+0.00 |
| Avg Holding | 0 min |
| Avg Confidence | 0.0 |
| Rank Score | 0.3106 |

### #6 — P7_VolatilityExpansion
**❌ Negative Expectancy**

Enters at the leading edge of a volatility expansion (COMPRESSED→NORMAL or NORMAL→EXPANDING). 10-bar breakout with commitment body filter.

| Metric | Value |
|:---|---:|
| Trades | 0 |
| Win Rate | 0.0% |
| Expectancy | +0.0000 R |
| Profit Factor | 0.000 |
| Sharpe | 0.000 |
| Sortino | 0.000 |
| Max Drawdown | 0.00% |
| Net PnL | $+0.00 |
| Avg Holding | 0 min |
| Avg Confidence | 0.0 |
| Rank Score | 0.3106 |

### #7 — P1_MarketAuction
**❌ Negative Expectancy**

Value Area rejection from rolling 12-hour Volume Profile (POC/VAH/VAL). Trades price back inside the Value Area after rejection at edges.

| Metric | Value |
|:---|---:|
| Trades | 186 |
| Win Rate | 26.9% |
| Expectancy | -0.2042 R |
| Profit Factor | 0.709 |
| Sharpe | -2.376 |
| Sortino | -15.666 |
| Max Drawdown | 16.55% |
| Net PnL | $-1,649.32 |
| Avg Holding | 47 min |
| Avg Confidence | 65.0 |
| Rank Score | 0.2533 |


---

## Final Recommendation

> **Replace V1 with P4_OpeningRangeBreakout (strong positive expectancy)**

### Implementation Notes
The recommended strategy has demonstrated positive expectancy on the test dataset.
Before proceeding to paper trading, conduct walk-forward validation on a fresh dataset.
Do NOT implement the winning strategy until this report is reviewed and approved.

---

## Deliverable Files

| File | Description |
|:---|:---|
| `reports/prototype_comparison.csv` | Full per-strategy metrics |
| `reports/strategy_rankings.json` | Machine-readable rankings + recommendation |
| `reports/strategy_research_report.md` | This report |
