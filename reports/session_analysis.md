# Module 2 — Session Analysis

Measures return characteristics, volatility, and spread cost for each trading session.
Forward return normalised to ATR. Spread expressed as fraction of ATR.

## Aggregate Session Statistics (All Symbols)

| Session | Bars | Avg Return (R) | Win % | Avg Volatility % | Avg Spread/ATR | Sharpe |
|:---|---:|---:|---:|---:|---:|---:|
| ASIA | 50,960 | +0.0518 | 50.2% | 0.0702% | 0.1977 | +0.010 |
| LONDON | 36,400 | +0.0306 | 50.5% | 0.0869% | 0.1562 | +0.007 |
| OVERLAP | 29,120 | +0.1145 | 51.1% | 0.0972% | 0.1337 | +0.032 |
| NEW_YORK | 29,120 | +0.0092 | 50.1% | 0.0993% | 0.1255 | +0.003 |
| OFF | 29,120 | +0.0509 | 51.1% | 0.0819% | 0.1593 | +0.013 |

## Per-Symbol Session Breakdown

### BTCUSD

| Session | Bars | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|---:|
| ASIA | 7,280 | +0.1820 | 51.0% | +0.026 |
| LONDON | 5,200 | -0.0877 | 49.1% | -0.015 |
| OVERLAP | 4,160 | +0.0169 | 49.6% | +0.004 |
| NEW_YORK | 4,160 | -0.0447 | 50.3% | -0.011 |
| OFF | 4,160 | -0.0734 | 48.7% | -0.014 |

### XAUUSD

| Session | Bars | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|---:|
| ASIA | 7,280 | +0.0345 | 49.7% | +0.010 |
| LONDON | 5,200 | -0.1400 | 48.2% | -0.047 |
| OVERLAP | 4,160 | -0.0389 | 49.9% | -0.013 |
| NEW_YORK | 4,160 | -0.0762 | 50.6% | -0.030 |
| OFF | 4,160 | +0.0133 | 51.2% | +0.004 |

### EURUSD

| Session | Bars | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|---:|
| ASIA | 7,280 | +0.2120 | 52.6% | +0.031 |
| LONDON | 5,200 | -0.1112 | 51.9% | -0.018 |
| OVERLAP | 4,160 | +0.3567 | 52.9% | +0.096 |
| NEW_YORK | 4,160 | +0.4522 | 55.3% | +0.099 |
| OFF | 4,160 | +0.3362 | 54.7% | +0.079 |

### GBPUSD

| Session | Bars | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|---:|
| ASIA | 7,280 | -0.1308 | 48.8% | -0.031 |
| LONDON | 5,200 | +0.1581 | 50.8% | +0.044 |
| OVERLAP | 4,160 | +0.2073 | 52.4% | +0.062 |
| NEW_YORK | 4,160 | +0.0193 | 49.5% | +0.006 |
| OFF | 4,160 | -0.0749 | 50.7% | -0.019 |

### USDJPY

| Session | Bars | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|---:|
| ASIA | 7,280 | +0.0590 | 50.9% | +0.012 |
| LONDON | 5,200 | +0.4228 | 53.3% | +0.093 |
| OVERLAP | 4,160 | +0.1444 | 52.8% | +0.035 |
| NEW_YORK | 4,160 | -0.0379 | 49.2% | -0.012 |
| OFF | 4,160 | +0.2139 | 51.4% | +0.056 |

### NAS100

| Session | Bars | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|---:|
| ASIA | 7,280 | -0.1001 | 47.5% | -0.030 |
| LONDON | 5,200 | -0.0833 | 49.1% | -0.030 |
| OVERLAP | 4,160 | -0.0760 | 49.8% | -0.029 |
| NEW_YORK | 4,160 | -0.2242 | 46.8% | -0.099 |
| OFF | 4,160 | -0.0370 | 50.0% | -0.011 |

### US30

| Session | Bars | Avg Return (R) | Win % | Sharpe |
|:---|---:|---:|---:|---:|
| ASIA | 7,280 | +0.1057 | 51.0% | +0.024 |
| LONDON | 5,200 | +0.0551 | 50.9% | +0.014 |
| OVERLAP | 4,160 | +0.1911 | 50.7% | +0.051 |
| NEW_YORK | 4,160 | -0.0240 | 49.1% | -0.006 |
| OFF | 4,160 | -0.0218 | 50.8% | -0.007 |

## Key Findings

- **Best session**: `OVERLAP` — Sharpe +0.032, Win Rate 51.1%
- **Worst session**: `NEW_YORK` — Sharpe +0.003, Win Rate 50.1%
- Sessions with higher spread/ATR ratios represent worse cost-adjusted opportunity.
