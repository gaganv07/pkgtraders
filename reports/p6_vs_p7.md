# Comparative Certification: P6 vs P7

This document evaluates the statistical robustness of P6 and P7 strategy prototypes.

## Performance Comparison
| Metric | P6 (Trend Pullback) | P7 (Volatility Expansion) |
|:---|:---:|:---:|
| **Expectancy** | -0.6450R | +0.0000R |
| **Profit Factor** | 0.311 | 0.000 |
| **Win Rate** | 9.1% | 0.0% |
| **Max Drawdown** | 472.66% | 0.00% |
| **Prob. of Ruin** | 100.0% | 100.0% |

## Decision & Verdict
Both P6 and P7 fail to meet the production certification criteria:
* **Win Rate**: Both failed the $\ge 40\%$ win rate hurdle.
* **Expectancy**: Both expectancies are negative.

### Conclusion
None of the current strategy prototypes (P1–P9) are production-ready. We recommend **rejecting** both strategies and proceeding to design a fundamentally different **P10 concept** (mean-reversion under low ATR, swing pullbacks without breakout constraints) rather than another incremental ORB breakout variation.
