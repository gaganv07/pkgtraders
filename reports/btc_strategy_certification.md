# BTCUSD Strategy Certification Report
**BTC_P3_OrderFlow Production Readiness Scorecard**

## Certification scorecard

| Requirement | Threshold | Value | Status |
|:---|:---|:---:|:---:|
| **Expectancy** | Expectancy $\ge$ 0.10 R | +0.0560 R | ❌ Fail |
| **Profit Factor** | PF $\ge$ 1.20 | 1.07 | ❌ Fail |
| **Drawdown Control** | Max DD < 12% | 30.16% | ❌ Fail |
| **Minimum Sample Size** | N $\ge$ 1000 | 2392 | ✅ Pass |
| **Monte Carlo Risk** | Prob. of Ruin < 5% | 100.00% | ❌ Fail |
| **Walk-Forward Stability** | All Out-of-Sample Exp > 0 | Unstable | ❌ Fail |
| **Stress Test Robustness** | 5-tick Slip Exp $\ge$ 0.02R | +0.055R | ✅ Pass |

## Final Certification Decision

> **Production Readiness Score**: **25/100**
> **Final Recommendation**: **Continue Research**
