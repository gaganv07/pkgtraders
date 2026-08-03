# Strategy Replay Audit Report — v3
**Production Engine Walk-Forward Analysis**
*Generated: 2026-06-24 13:09 UTC*

> **Replay Window**: 2026-06-09 to 2026-06-24 (15 days)
> **Data Source**: Real MT5 tick history + M15/H1 bars (BlackBullMarkets Demo)
> **Warm-up**: 400 days of M15/H1 bar history for indicator initialisation

## Executive Summary

| Metric | Value |
|:---|---:|
| **Initial Balance** | $10,000.00 |
| **Final Balance** | $9,484.16 |
| **Net Return** | -5.16% |
| **Net Profit** | $-515.84 |
| **Win Rate** | 26.3% |
| **Profit Factor** | 0.27 |
| **Sharpe Ratio** | -94.87 |
| **Max Drawdown** | 5.16% |
| **Total Signals Evaluated** | 928 |
| **Total Trades Executed** | 19 |
| **Total Setups Rejected** | 909 |

## PnL by Symbol
- **GBPUSD**: $-52.04
- **NAS100**: $-13.90
- **US30**: $+38.33
- **USDJPY**: $-364.63
- **XAUUSD**: $-123.60

## Filter Activation & Performance
| Filter | Pass% | Fail% | Contribution% | Avg PnL (Pass) | Avg PnL (Fail) |
|:---|:---:|:---:|:---:|:---:|:---:|
| EMA | 100.0% | 0.0% | +0.00% | $-7.39 | $+0.00 |
| VWAP | 100.0% | 0.0% | +0.00% | $-7.39 | $+0.00 |
| DOM | 100.0% | 0.0% | +0.00% | $-7.39 | $+0.00 |
| Liquidity | 9.2% | 90.8% | -1.33% | $-15.75 | $-6.54 |
| FVG | 14.1% | 85.9% | +0.00% | $+9.21 | $-10.11 |
| MSS | 5.9% | 94.1% | +0.00% | $-4.70 | $-7.56 |
| BOS | 53.8% | 46.2% | +0.00% | $-3.96 | $-11.37 |
| ATR | 96.4% | 3.6% | +0.00% | $-8.19 | $+14.38 |
| Spread | 99.2% | 0.8% | +0.00% | $-7.70 | $+34.33 |
| Session | 42.6% | 57.4% | -1.36% | $-11.26 | $-4.51 |
| News | 100.0% | 0.0% | +0.00% | $-7.39 | $+0.00 |
| Cooldown | 98.8% | 1.2% | +0.00% | $-7.45 | $-1.78 |
| Risk | 39.3% | 60.7% | +0.50% | $+0.15 | $-12.27 |
| Pos Limit | 85.8% | 14.2% | +0.00% | $-6.19 | $-14.60 |

## Top Rejection Reasons
| Reason | Count |
|:---|:---:|
| Score Threshold | 555 |
| Session | 531 |
| Risk / Drawdown | 451 |
| Spread | 7 |

## Charts
Saved to `reports/` and brain artifacts directory.
