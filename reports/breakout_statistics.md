# Module 5 — Breakout Study

Detects breakouts (close beyond 10-bar prior high/low) and measures outcome.
Success = continuation ≥1 ATR in breakout direction within next 5 bars.

## Breakout Statistics by Session × Volatility Regime

| Session | Vol Regime | Events | Success % | Fail % | Avg Cont (R) | Avg Fail (R) | Avg Bars to Reversal |
|:---|:---|---:|---:|---:|---:|---:|---:|
| ASIA | COMPRESSED | 6078 | 84.4% | 15.6% | 3.90 | 1.70 | 3.9 |
| ASIA | EXPANSION | 4136 | 97.0% | 3.0% | 4.56 | 1.28 | 3.9 |
| ASIA | HIGH_VOL | 5970 | 98.2% | 1.8% | 5.05 | 1.71 | 4.0 |
| ASIA | LOW_VOL | 2865 | 91.3% | 8.7% | 4.86 | 1.35 | 3.8 |
| ASIA | NORMAL | 8779 | 94.1% | 5.9% | 4.48 | 1.62 | 3.7 |
| LONDON | COMPRESSED | 1374 | 82.5% | 17.5% | 3.67 | 3.60 | 3.1 |
| LONDON | EXPANSION | 2798 | 93.6% | 6.4% | 4.24 | 1.89 | 3.4 |
| LONDON | HIGH_VOL | 7330 | 95.5% | 4.5% | 4.32 | 1.38 | 3.8 |
| LONDON | LOW_VOL | 1517 | 88.9% | 11.1% | 3.98 | 2.20 | 3.1 |
| LONDON | NORMAL | 4361 | 92.2% | 7.8% | 4.38 | 2.00 | 3.4 |
| NEW_YORK | COMPRESSED | 963 | 74.6% | 25.4% | 3.54 | 0.83 | 4.5 |
| NEW_YORK | EXPANSION | 3004 | 91.0% | 9.0% | 3.79 | 1.10 | 4.1 |
| NEW_YORK | HIGH_VOL | 6103 | 94.6% | 5.4% | 3.99 | 1.26 | 3.9 |
| NEW_YORK | LOW_VOL | 731 | 85.0% | 15.0% | 3.79 | 0.97 | 4.3 |
| NEW_YORK | NORMAL | 2832 | 88.4% | 11.6% | 3.90 | 1.22 | 3.9 |
| OFF | COMPRESSED | 2677 | 83.0% | 17.0% | 3.68 | 1.24 | 4.4 |
| OFF | EXPANSION | 3691 | 94.8% | 5.2% | 4.10 | 0.89 | 4.5 |
| OFF | HIGH_VOL | 3283 | 97.9% | 2.1% | 4.65 | 1.04 | 4.2 |
| OFF | LOW_VOL | 1132 | 89.9% | 10.1% | 4.15 | 1.14 | 4.2 |
| OFF | NORMAL | 4720 | 92.3% | 7.7% | 3.89 | 1.10 | 4.3 |
| OVERLAP | COMPRESSED | 755 | 75.5% | 24.5% | 3.52 | 1.81 | 3.5 |
| OVERLAP | EXPANSION | 1961 | 91.5% | 8.5% | 4.06 | 1.79 | 3.0 |
| OVERLAP | HIGH_VOL | 6494 | 93.7% | 6.3% | 4.11 | 1.79 | 3.1 |
| OVERLAP | LOW_VOL | 744 | 85.2% | 14.8% | 3.52 | 2.28 | 3.0 |
| OVERLAP | NORMAL | 3059 | 87.9% | 12.1% | 4.10 | 2.02 | 2.9 |

## Key Findings

- **Overall breakout success rate**: 89.7%
- **Best breakout condition**: `ASIA/HIGH_VOL` — 98.2% success
- **Worst breakout condition**: `NEW_YORK/COMPRESSED` — 74.6% success
- Failed breakouts (false breaks) often reverse quickly — potential mean-reversion entry signal.
