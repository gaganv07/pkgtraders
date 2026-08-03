# Module 1 — Regime Detection

Classifies every M15 bar into one of 8 market regimes based on ATR percentile, ADX, and EMA alignment.
Forward return = normalised return over next 5 bars (in ATR units).

## Regime Statistics

| Regime | Count | % of Data | Avg Fwd Return (R) | Win % | Std Dev | Sharpe | Avg Body/ATR | Avg Wick Ratio |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| COMPRESSION | 43,767 | 25.0% | -0.0777 | 50.1% | 5.2919 | -0.015 | 0.306 | 0.601 |
| RANGE | 5,390 | 3.1% | +0.1696 | 52.2% | 4.0652 | +0.042 | 0.433 | 0.614 |
| WEAK_TREND | 3,758 | 2.2% | -0.0762 | 52.0% | 4.1412 | -0.018 | 0.455 | 0.609 |
| TRENDING | 7,214 | 4.1% | +0.0664 | 50.5% | 4.3564 | +0.015 | 0.460 | 0.603 |
| STRONG_TREND | 47,836 | 27.4% | -0.0746 | 48.8% | 3.7495 | -0.020 | 0.504 | 0.461 |
| EXPANSION | 25,418 | 14.5% | -0.0250 | 49.3% | 3.6871 | -0.007 | 0.554 | 0.433 |
| LOW_VOL | 0 | 0.0% | +0.0000 | 0.0% | 0.0000 | +0.000 | 0.000 | 0.000 |
| HIGH_VOL | 41,337 | 23.7% | +0.3709 | 53.4% | 3.9858 | +0.093 | 0.651 | 0.383 |

## Regime Ranking (by Sharpe ratio of forward return)

| Rank | Regime | Sharpe | Avg Return (R) | Win % |
|:---|:---|---:|---:|---:|
| 1 | HIGH_VOL | +0.093 | +0.3709 | 53.4% |
| 2 | RANGE | +0.042 | +0.1696 | 52.2% |
| 3 | TRENDING | +0.015 | +0.0664 | 50.5% |
| 4 | LOW_VOL | +0.000 | +0.0000 | 0.0% |
| 5 | EXPANSION | -0.007 | -0.0250 | 49.3% |
| 6 | COMPRESSION | -0.015 | -0.0777 | 50.1% |
| 7 | WEAK_TREND | -0.018 | -0.0762 | 52.0% |
| 8 | STRONG_TREND | -0.020 | -0.0746 | 48.8% |

## Key Findings

- **Best regime for forward returns**: `HIGH_VOL` (Sharpe +0.093)
- **Worst regime (avoid)**:            `STRONG_TREND` (Sharpe -0.020)
- **Most frequent regime**:            `STRONG_TREND`
