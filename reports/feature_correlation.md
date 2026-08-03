# Module 10 — Feature Correlation Analysis

Measures predictive power of each feature against forward 5-bar return (normalised to ATR).
Pearson r = linear correlation. p < 0.05 = statistically significant.

## Feature Correlation Table

| Feature | Pearson r | p-value | IC (Rank Corr) | Significance | Verdict |
|:---|---:|---:|---:|:---|:---|
| ATR Percentile | +0.0341 | 0.0001 | +0.0371 | ✅ Significant | Weak |
| ATR Value | +0.0168 | 0.0001 | -0.0135 | ✅ Significant | No edge |
| EMA20 Slope | +0.1998 | 0.0001 | +0.4188 | ✅ Significant | Useful |
| EMA Alignment | +0.3316 | 0.0001 | +0.3887 | ✅ Significant | Useful |
| RSI(14) | +0.5610 | 0.0001 | +0.7493 | ✅ Significant | Useful |
| ADX(14) | +0.0199 | 0.0001 | +0.0192 | ✅ Significant | No edge |
| +DI | +0.5219 | 0.0001 | +0.7192 | ✅ Significant | Useful |
| -DI | -0.5125 | 0.0001 | -0.7166 | ✅ Significant | Useful |
| Volume Percentile | +0.0008 | 0.7336 | +0.0016 | — Not sig. | No edge |
| VWAP Deviation | +0.3724 | 0.0001 | +0.6131 | ✅ Significant | Useful |
| Spread/ATR | -0.0244 | 0.0001 | -0.0331 | ✅ Significant | Weak |
| Session | +0.0029 | 0.2279 | +0.0008 | — Not sig. | No edge |
| Regime | -0.0021 | 0.3699 | -0.0154 | — Not sig. | No edge |
| RSI Overbought | +0.4623 | 0.0001 | +0.5060 | ✅ Significant | Useful |
| RSI Oversold | -0.4536 | 0.0001 | -0.4969 | ✅ Significant | Useful |

## Feature Ranking (by |Pearson r|)

| Rank | Feature | |r| | p-value |
|:---|:---|---:|---:|
| 1 | RSI(14) | 0.5610 | 0.0001 |
| 2 | +DI | 0.5219 | 0.0001 |
| 3 | -DI | 0.5125 | 0.0001 |
| 4 | RSI Overbought | 0.4623 | 0.0001 |
| 5 | RSI Oversold | 0.4536 | 0.0001 |
| 6 | VWAP Deviation | 0.3724 | 0.0001 |
| 7 | EMA Alignment | 0.3316 | 0.0001 |
| 8 | EMA20 Slope | 0.1998 | 0.0001 |
| 9 | ATR Percentile | 0.0341 | 0.0001 |
| 10 | Spread/ATR | 0.0244 | 0.0001 |
| 11 | ADX(14) | 0.0199 | 0.0001 |
| 12 | ATR Value | 0.0168 | 0.0001 |
| 13 | Session | 0.0029 | 0.2279 |
| 14 | Regime | 0.0021 | 0.3699 |
| 15 | Volume Percentile | 0.0008 | 0.7336 |

## Key Findings

- **Strongest predictor**: `RSI(14)` (r=+0.5610, p=0.0001)
- **Significant features** (p<0.05): 12 of 15
- Features with |r| < 0.02 provide no measurable edge and should be removed from scoring.
- Significant features should anchor the next generation of strategy filters.
