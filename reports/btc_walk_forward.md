# BTCUSD Walk-Forward Validation Report
**Sequential Out-of-Sample Performance Stability (6-Month Train / 3-Month Validate)**

## Rolling Validation Results

| Window | Train Window | Validation Window | Train Exp | Val Exp | Train PF | Val PF | Val DD | Val Trades |
|:---|:---|:---|:---:|:---:|:---:|:---:|:---:|:---:|
| Window 1 | 2024/01-2024/07 | 2024/07-2024/10 | +0.024R | -0.019R | 0.99 | 0.99 | 24.95% | 263 |
| Window 2 | 2024/04-2024/10 | 2024/10-2025/01 | +0.046R | +0.181R | 1.11 | 1.22 | 13.74% | 254 |
| Window 3 | 2024/07-2025/01 | 2025/01-2025/04 | +0.079R | -0.174R | 1.12 | 0.65 | 85.6% | 253 |
| Window 4 | 2024/10-2025/04 | 2025/04-2025/07 | +0.004R | -0.370R | 0.90 | 0.63 | 104.25% | 269 |
| Window 5 | 2025/01-2025/07 | 2025/07-2025/10 | -0.212R | +0.209R | 0.70 | 1.55 | 23.38% | 276 |
| Window 6 | 2025/04-2025/10 | 2025/10-2026/01 | +0.127R | +0.072R | 1.28 | 1.07 | 15.63% | 235 |
| Window 7 | 2025/07-2026/01 | 2026/01-2026/04 | +0.028R | +0.106R | 1.03 | 1.19 | 9.74% | 236 |

---

## Stability Verdict
- **Out-of-Sample Consistency**: Evaluates if the strategy maintains positive expectancy across sequential validation segments.
