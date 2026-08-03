# Module 9 — Pattern Mining

Detects 12 recurring price patterns and measures their forward predictive power.
Avg Move = average directional forward return in R units from pattern perspective.
Win % = probability the pattern direction is correct over next 5 bars.

## Pattern Statistics

| Pattern | Detections | Win % | Avg Move (R) | Std Dev | Sharpe | Significance |
|:---|---:|---:|---:|---:|---:|:---|
| HH+HL (Uptrend) | 47,663 | 89.7% | +3.2932 | 2.8421 | +1.159 | ✅ p<0.05 |
| LL+LH (Downtrend) | 45,586 | 89.3% | +3.1842 | 2.8357 | +1.123 | ✅ p<0.05 |
| Compression (3-bar) | 26,731 | 50.0% | -0.0418 | 4.2020 | -0.010 | — n.s. |
| Inside Bar | 21,121 | 49.7% | -0.0351 | 3.3933 | -0.010 | — n.s. |
| Outside Bar | 20,254 | 50.0% | -0.0525 | 4.0274 | -0.013 | — n.s. |
| Pinbar (Bear) | 19,459 | 50.0% | +0.0034 | 4.4265 | +0.001 | — n.s. |
| Pinbar (Bull) | 19,326 | 49.5% | -0.0749 | 4.2874 | -0.017 | ✅ p<0.05 |
| Liq Sweep (Bull) | 18,712 | 47.2% | -0.1986 | 3.9143 | -0.051 | ✅ p<0.05 |
| Liq Sweep (Bear) | 18,685 | 47.8% | -0.1265 | 4.6640 | -0.027 | ✅ p<0.05 |
| Bearish Engulfing | 4,294 | 50.9% | +0.1238 | 3.4273 | +0.036 | ✅ p<0.05 |
| Bullish Engulfing | 4,246 | 50.6% | -0.0614 | 4.8586 | -0.013 | — n.s. |
| Expansion Bar | 3,603 | 49.9% | -0.2133 | 9.4009 | -0.023 | — n.s. |

## Key Findings

- **Highest Sharpe pattern**: `HH+HL (Uptrend)` — Sharpe +1.159
- **Lowest Sharpe pattern**: `Liq Sweep (Bull)` — Sharpe -0.051
- **Most frequent pattern**: `HH+HL (Uptrend)` — 47,663 detections
- Patterns marked ✅ are statistically significant (p < 0.05) and warrant further study.
