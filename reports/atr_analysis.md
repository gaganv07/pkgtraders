# Module 3 — ATR Analysis

Measures expected forward movement at each ATR percentile decile.
- **1R Prob**: probability of ≥1R move in forward 5 bars (abs value)
- **2R Prob**: probability of ≥2R move in forward 10 bars
- **Reversal Prob**: probability fwd_5 has opposite sign to expected trend

## ATR Percentile Decile Analysis

| Decile | Range | Bars | Avg Fwd-5 (R) | Win% | 1R Prob | 2R Prob | Reversal % | Sharpe |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|
| D1 | 0–10% | 37,505 | -0.0992 | 49.8% | 39.7% | 38.3% | 50.1% | -0.019 |
| D2 | 10–20% | 11,744 | +0.0562 | 51.1% | 55.7% | 52.9% | 48.8% | +0.013 |
| D3 | 20–30% | 11,610 | -0.0479 | 49.9% | 60.1% | 57.0% | 50.1% | -0.012 |
| D4 | 30–40% | 13,324 | -0.0645 | 49.4% | 62.0% | 58.6% | 50.6% | -0.016 |
| D5 | 40–50% | 13,612 | -0.0405 | 49.5% | 66.5% | 64.0% | 50.5% | -0.010 |
| D6 | 50–60% | 13,612 | -0.0286 | 49.6% | 69.8% | 65.9% | 50.3% | -0.008 |
| D7 | 60–70% | 13,278 | -0.0446 | 48.7% | 72.6% | 69.3% | 51.2% | -0.012 |
| D8 | 70–80% | 12,639 | -0.0500 | 49.2% | 75.3% | 72.9% | 50.8% | -0.013 |
| D9 | 80–90% | 13,232 | +0.1118 | 50.7% | 79.8% | 77.6% | 49.2% | +0.030 |
| D10 | 90–100% | 34,164 | +0.4097 | 53.8% | 84.5% | 82.3% | 46.1% | +0.102 |

## Key Findings

- **Best ATR decile**: `D10 (90-100%)` — Sharpe +0.102, 1R probability 84.5%
- **Worst ATR decile**: `D1 (0-10%)` — Sharpe -0.019
- Higher ATR percentiles generally produce larger moves but also higher reversal risk.
- Low ATR deciles (D1–D2) consistently produce the smallest moves relative to spread cost.
