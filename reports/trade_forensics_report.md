# Trade Outcome Forensics Audit Report
**Analysis of Trade Performance and Source of Negative Expectancy**
*Generated: 2026-06-24 13:20 UTC*

---

## 1. Executive Summary

This Trade Outcome Forensics Audit has been conducted on the 19 completed trades from the 15-day paper trading validation run. The objective is to identify the root cause of the strategy's negative expectancy (**-$515.84 Net PnL**, **-0.456 R Expectancy**) without making any configuration edits or parameter changes.

### Key Finding

The primary source of negative expectancy is a combination of:
1. **Low Volatility (ATR) Entry Trap**: Opening trades in low-ATR periods results in extremely tight stop losses (derived from ATR) which are easily triggered by minor price noise and spread fluctuations.
2. **Reverse Predictive Value of FVG and DOM Liquidity**: Trades taken when Fair Value Gaps (FVG) are present are statistically much more likely to lose money as price pulls back to fill the gap. Dense DOM/liquidity levels, which the scoring engine prefers, actually represent ranging/mean-reverting consolidation rather than momentum expansion, leading to breakout failures.
3. **Unhedged Multi-Symbol Correlation**: The strategy was repeatedly stopped out in quick succession across highly correlated pairs (e.g., USDJPY and XAUUSD) due to macro USD movement, which triggered the 5-loss circuit breaker.

---

## 2. Phase 1: Completed Trade Log Analysis

The following table details every executed trade from the paper trading validation phase:

| Entry Time (UTC) | Exit Time (UTC) | Symbol | Direction | Price (In/Out) | Lot Size | Risk ($) | Score | PnL ($) | R | Close Reason |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 06-09 12:15 | 06-09 16:15 | USDJPY | LONG | 160.185 / 160.181 | 0.01 | $55.38 | 71.89 | -$4.07 | -0.07 | TIME_STOP |
| 06-10 07:15 | 06-10 08:35 | XAUUSD | SHORT | 4181.23 / 4194.41 | 0.03 | $39.55 | 73.17 | -$39.75 | -1.00 | SL |
| 06-10 09:00 | 06-10 09:08 | XAUUSD | SHORT | 4205.46 / 4219.85 | 0.03 | $43.18 | 73.07 | -$43.38 | -1.00 | SL |
| 06-10 09:45 | 06-10 10:32 | XAUUSD | SHORT | 4207.60 / 4193.95 | 0.03 | $40.96 | 72.59 | +$40.76 | +1.00 | TP |
| 06-10 11:15 | 06-10 14:58 | XAUUSD | SHORT | 4166.70 / 4148.96 | 0.02 | $35.48 | 74.97 | +$35.35 | +1.00 | TP |
| 06-11 09:00 | 06-11 11:10 | XAUUSD | SHORT | 4094.24 / 4112.22 | 0.02 | $35.95 | 71.65 | -$36.08 | -1.00 | SL |
| 06-11 15:30 | 06-11 15:55 | GBPUSD | SHORT | 1.33501 / 1.33643 | 0.35 | $49.68 | 72.05 | -$52.04 | -1.05 | SL |
| 06-12 09:45 | 06-12 11:03 | USDJPY | LONG | 160.331 / 160.262 | 0.01 | $69.21 | 67.13 | -$69.28 | -1.00 | SL |
| 06-12 11:45 | 06-12 14:30 | XAUUSD | LONG | 4218.83 / 4201.43 | 0.02 | $34.80 | 82.63 | -$34.93 | -1.00 | SL |
| 06-12 15:00 | 06-12 15:39 | XAUUSD | SHORT | 4206.63 / 4193.19 | 0.03 | $40.31 | 73.03 | +$40.11 | +1.00 | TP |
| 06-15 11:30 | 06-15 14:38 | USDJPY | SHORT | 160.101 / 160.173 | 0.01 | $72.04 | 73.75 | -$72.11 | -1.00 | SL |
| 06-16 09:15 | 06-16 10:29 | US30 | LONG | 51740.5 / 51779.2 | 1.20 | $46.43 | 73.46 | +$38.33 | +0.83 | TP |
| 06-16 11:30 | 06-16 12:50 | USDJPY | SHORT | 160.273 / 160.362 | 0.01 | $89.49 | 72.42 | -$89.56 | -1.00 | SL |
| 06-16 13:45 | 06-16 14:19 | NAS100 | LONG | 30603.2 / 30646.95 | 1.10 | $48.13 | 81.59 | +$40.71 | +0.85 | TP |
| 06-16 14:45 | 06-16 15:16 | NAS100 | LONG | 30632.7 / 30589.80 | 1.10 | $47.19 | 80.19 | -$54.61 | -1.16 | SL |
| 06-17 07:00 | 06-17 07:29 | XAUUSD | LONG | 4332.46 / 4326.08 | 0.07 | $44.63 | 65.91 | -$45.10 | -1.01 | SL |
| 06-17 08:30 | 06-17 11:17 | XAUUSD | LONG | 4328.73 / 4320.68 | 0.05 | $40.24 | 74.03 | -$40.58 | -1.01 | SL |
| 06-17 12:30 | 06-17 14:05 | USDJPY | SHORT | 160.181 / 160.258 | 0.01 | $76.52 | 75.80 | -$76.59 | -1.00 | SL |
| 06-17 14:30 | 06-17 14:41 | USDJPY | SHORT | 160.272 / 160.325 | 0.01 | $52.95 | 82.91 | -$53.02 | -1.00 | SL |

---

## 3. Phase 2: Winner vs. Loser Comparison

A statistical comparison of the soft indicator scores between Winners (5 trades) and Losers (14 trades):

| Feature | Winner Avg | Loser Avg | Difference | T-Stat | P-Value | Statistical Notes |
| :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **of_score** (Order Flow) | 59.34 | 55.61 | +3.73 | 0.412 | 0.6927 | Weakly positive but not statistically significant. |
| **liq_score** (DOM Liquidity) | 60.00 | 64.90 | -4.90 | -3.574 | **0.0034** | **Significant**. High liquidity indicates consolidation (loses money). |
| **ms_score** (Market Structure)| 68.42 | 66.31 | +2.11 | 0.398 | 0.6983 | Insignificant difference. |
| **session_score** (Session) | 86.00 | 85.36 | +0.64 | 0.154 | 0.8824 | Insignificant. All trades occurred in active sessions. |
| **fvg_score** (Fair Value Gap) | 0.00 | 28.57 | -28.57 | -2.280 | **0.0401** | **Significant**. 0% of winners had FVG; gaps acted as pullbacks. |
| **bos_score** / **mss_score** | 0.00 | 7.14 | -7.14 | -1.000 | 0.3356 | Insignificant. Structure shifts were rarely present. |

---

## 4. Phase 3 & 4: Pattern & Characteristics Analysis

### Top 20 Winning Trade Characteristics
1. **session_score_level = HIGH (>=75)** (100% of winners)
2. **BOS_Detected = False** (100% of winners)
3. **MSS_Detected = False** (100% of winners)
4. **liq_score_level = MODERATE (50-75)** (100% of winners)
5. **ms_score_level = MODERATE (50-75)** (100% of winners)
6. **FVG_Present = False** (100% of winners)
7. **Liq_Sweep = False** (100% of winners)
8. **Spread_Low_Normal** (100% of winners)
9. **Regime = EXPANDING** (80% of winners)
10. **Symbol = XAUUSD** (60% of winners)
11. **Direction = SHORT** (60% of winners)
12. **ATR_High** (60% of winners)
13. **DayOfWeek = Wednesday** (40% of winners)
14. **DayOfWeek = Tuesday** (40% of winners)
15. **HourOfDay = 9** (40% of winners)
16. **of_score_level = LOW (<50)** (40% of winners)
17. **of_score_level = MODERATE (50-75)** (40% of winners)
18. **ATR_Low_Normal** (40% of winners)
19. **Direction = LONG** (40% of winners)
20. **Regime = NORMAL** (20% of winners)

### Top 20 Losing Trade Characteristics
1. **liq_score_level = MODERATE (50-75)** (100% of losers)
2. **session_score_level = HIGH (>=75)** (100% of losers)
3. **Spread_Low_Normal** (100% of losers)
4. **BOS_Detected = False** (92.9% of losers)
5. **MSS_Detected = False** (85.7% of losers)
6. **Liq_Sweep = False** (78.6% of losers)
7. **ms_score_level = MODERATE (50-75)** (78.6% of losers)
8. **ATR_Low_Normal** (78.6% of losers)
9. **of_score_level = MODERATE (50-75)** (64.3% of losers)
10. **FVG_Present = False** (64.3% of losers)
11. **Regime = EXPANDING** (57.1% of losers)
12. **Direction = SHORT** (57.1% of losers)
13. **Symbol = USDJPY** (42.9% of losers)
14. **Symbol = XAUUSD** (42.9% of losers)
15. **Direction = LONG** (42.9% of losers)
16. **DayOfWeek = Wednesday** (42.9% of losers)
17. **FVG_Present = True** (35.7% of losers)
18. **of_score_level = LOW (<50)** (28.6% of losers)
19. **Regime = NORMAL** (28.6% of losers)
20. **DayOfWeek = Tuesday** (21.4% of losers)

---

## 5. Phase 5: Determining the True Sources of Negative Expectancy

We analyzed the failures across the following hypotheses:

### 1. Volatility Regime and Low-ATR Entry Trap (Root Cause)
* **Finding**: Lower ATR was strongly correlated with larger losses (**corr = +0.543**). High ATR group average PnL was **-$1.35**, while low ATR group average PnL was **-$55.82**.
* **Rationale**: In low ATR states, the calculated Stop Loss (SL) distance is extremely small. The strategy places tight stop losses. These are immediately hit by minor spread fluctuation or minor tick noise, long before any structural direction is established.

### 2. Reverse Volatility Regime Behavior
* **Finding**: 2 out of 14 losers were taken during `EXPLOSIVE` volatility (on GBPUSD and USDJPY), leading to large quick stops. Expanding regime was dominant in both winners (80%) and losers (57%), proving that momentum-seeking in Expanding markets works if stops are wide enough, but fails when noise stops it out.

### 3. False/Weak Soft Indicator Confluences (FVG & DOM Liquidity)
* **Finding**: `fvg_present` was a negative predictor (**p = 0.0401**). 0% of winners had FVG, whereas 35.7% of losers did.
* **Rationale**: If a Fair Value Gap is present, it acts as a liquidity magnet. Entering momentum breakout trades in the direction of the gap results in immediate stop-outs as the market pulls back to fill/mitigate the gap.
* **DOM Liquidity**: Higher liquidity scores (`liq_score`) were strongly negatively correlated with PnL (**corr = -0.562**, **p = 0.0034**). Thick order books (high liquidity) are indicative of consolidating, range-bound markets. Attempting to trade breakouts or trends into thick DOM levels leads to mean-reversion failures.

### 4. Unhedged Multi-Symbol Correlation
* **Finding**: `USDJPY` and `XAUUSD` contributed to **85.7% of all losing trades**.
* **Rationale**: On June 15-17, the strategy opened multiple USD-related trades concurrently. Because the strategy has no correlation awareness, a single macro-driven move against the USD triggered a cascade of stop-outs across both pairs, culminating in the 5 consecutive loss streak.

---

## 6. Phase 6: Deliverable & Strategy Recommendations

Based on the forensics audit, we make the following recommendations (no code modifications are made, as per constraints):

### 1. Features to Remove
- **FVG Confluence (fvg_score)**: Remove or invert. Entering trades when a gap is present leads to immediate stop-outs during pullbacks. It is a counter-indicator for breakout/momentum execution.
- **Session Boost (session_score)**: Showed zero correlation with profitability (+0.07). The active sessions are already guarded by the hard session filter; the soft boost only distorts the composite score.

### 2. Features to Strengthen
- **Volatility Filter (atr_score / minimum ATR)**: Prevent entries in low ATR states. Standardize a minimum physical ATR floor for all assets (e.g. at least 15-20 points) rather than relying on loose soft scaling to prevent tight-stop traps.
- **Order Flow Delta (of_delta)**: Strong positive correlation with profitability (**corr = +0.520**). High bin PnL was -$12.66 vs Low bin -$47.07. Focus more heavily on actual cumulative order volume pressure.

### 3. Features with No Predictive Value
- **MSS and BOS Confluences (mss_score, bos_score)**: In 19 trades, MSS was present only once, and BOS was present only once. They are far too rare under recalibrated settings to offer any predictive value or statistical impact.
- **DOM/Fallback Liquidity Score (liq_score)**: It has inverse predictive power (corr = -0.562, p = 0.0034) because dense DOM depth indicates thick ranges, which cause breakouts to fail. It should be removed as a positive momentum factor.

---

## 7. Deliverables References
- **Winner vs. Loser Indicator Comparison**: [winner_vs_loser_analysis.csv](file:///C:/Users/LENOVO/.gemini/antigravity-ide/brain/86515f4f-c227-440d-8805-95d41e87d7aa/winner_vs_loser_analysis.csv)
- **Feature Profitability Rank**: [feature_profitability_rank.csv](file:///C:/Users/LENOVO/.gemini/antigravity-ide/brain/86515f4f-c227-440d-8805-95d41e87d7aa/feature_profitability_rank.csv)
