# Forensic Root Cause Analysis Report
**Target System**: P8 ORB V2 Strategy & V3 Trade Quality Gate

## Executive Summary
This report analyzes why the Opening Range Breakout (ORB) models displays negative expectancy ($E = -0.8293R$) on this dataset despite drawdown reduction features.

## Excursion & Execution Efficiency (MAE/MFE)
- **Average MAE**: 11.235 R
- **Average MFE**: 0.758 R
- **Average Time to Stop-out**: 51.5 mins
- **Average Time to Take-Profit**: 91.3 mins

### Outcome Breakdown
- **Stop-Loss Fills**: 84.83%
- **Take-Profit Fills**: 15.00%
- **Time Stop Exits**: 0.17%

---

## Strategic Failures Identification

### 1. Stop Distance vs Intraday Noise
The MAE/MFE profile indicates that ORB breakouts are heavily impacted by local noise. Even though V2 expanded stops to $1.0 \times ATR$, the average adverse excursion reaches 11.235R, showing that price routinely pulls back deep into the range before confirming direction.

### 2. High Consolidation and Fakeout Density
Under range-bound and low-volatility regimes (representing 42.6% of total losses), breakouts fail to secure a $2:1$ Risk-Reward expansion before reversal.

---

## Independent Component Diagnostics
- **Entry Logic only**: Testing the breakout triggers with fixed $1:1$ Stop/TP targets yields a raw win rate of only $14.6\%$, indicating significant entry lag or trigger noise.
- **Exit Logic only**: The time stop at the NY market close prevents further drawdown but clips winning runs that pull back.
- **Sizing/Money Management**: Flat risk allocation prevents ruin but fails to capture trend compounding due to the lack of high-probability regime filtering.
