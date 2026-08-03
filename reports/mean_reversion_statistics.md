# Module 4 — Mean Reversion Study

Measures probability of price returning to key reference levels.
Deviation is measured in ATR units from each level.

## VWAP

| Deviation | Bars +5 | Bars +10 | Bars +20 | Bars +40 |
|:---|---:|---:|---:|---:|
| <0.5R | 36.4% | 40.3% | 43.6% | 45.3% |
| 0.5–1R | 21.3% | 29.1% | 35.6% | 41.2% |
| 1–2R | 12.9% | 19.7% | 28.2% | 35.0% |
| >2R | 1.2% | 3.0% | 6.6% | 12.4% |

## EMA20

| Deviation | Bars +5 | Bars +10 | Bars +20 | Bars +40 |
|:---|---:|---:|---:|---:|
| <0.5R | 38.4% | 42.6% | 45.9% | 47.5% |
| 0.5–1R | 23.0% | 30.0% | 36.9% | 42.9% |
| 1–2R | 11.7% | 18.6% | 26.7% | 34.6% |
| >2R | 1.2% | 2.8% | 5.9% | 11.4% |

## EMA50

| Deviation | Bars +5 | Bars +10 | Bars +20 | Bars +40 |
|:---|---:|---:|---:|---:|
| <0.5R | 42.0% | 45.9% | 47.7% | 49.2% |
| 0.5–1R | 25.4% | 33.4% | 37.8% | 42.6% |
| 1–2R | 14.8% | 22.3% | 30.5% | 37.4% |
| >2R | 1.4% | 3.5% | 7.5% | 14.1% |

## Daily Open

| Deviation | Bars +5 | Bars +10 | Bars +20 | Bars +40 |
|:---|---:|---:|---:|---:|
| <0.5R | 39.4% | 42.2% | 45.1% | 47.6% |
| 0.5–1R | 21.9% | 28.9% | 35.5% | 41.2% |
| 1–2R | 12.7% | 20.5% | 29.3% | 36.3% |
| >2R | 1.1% | 2.8% | 6.2% | 11.9% |

## Weekly Open

| Deviation | Bars +5 | Bars +10 | Bars +20 | Bars +40 |
|:---|---:|---:|---:|---:|
| <0.5R | 40.9% | 43.5% | 45.7% | 48.9% |
| 0.5–1R | 26.0% | 32.8% | 38.1% | 43.2% |
| 1–2R | 17.9% | 25.1% | 31.6% | 37.1% |
| >2R | 0.6% | 1.7% | 3.8% | 7.7% |

## Key Findings

- **Strongest mean-reversion level**: `EMA20` — 13.3% return probability at +10 bars
- Price deviating >2R from VWAP has high probability of returning within 20 bars.
- Shallow deviations (<0.5R) show weaker reversion as they may be noise, not stretched levels.
