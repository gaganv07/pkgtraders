# A/B Validation Report: Baseline vs. Recalibrated
**Automated Replay & Recalibration Strategy Validation**
*Generated: 2026-06-24 12:07 UTC*

---

## Executive Summary

We compared the **Baseline Strategy** (current production configuration) and the **Recalibrated Strategy** (blended weights and optimized thresholds) using a chronological, compounding replay over 22,274 historical signals.

### Deployment Recommendation

> [!WARNING]
> **Deployment Decision: REJECT**
> The recalibrated strategy **should NOT be deployed. Retain the baseline strategy.**

### Acceptance Criteria Checklist

| Criterion | Target | Baseline | Recalibrated | Status |
| :--- | :--- | :---: | :---: | :---: |
| **Trade Count** | Increase trades meaningfully | 1 | 51 | ✅ Passed |
| **Expectancy (R)** | Maintain or improve expectancy | -0.9216R | -0.4149R | ✅ Passed |
| **Max Drawdown** | Do not materially worsen DD (<= baseline + 3%) | 0.46% | 10.51% | ❌ Failed |
| **Safety Validation** | Zero violations of safety limits | 0 | 210 | ❌ Failed |

---

## Performance Comparison

| Metric | Baseline | Recalibrated | Difference |
| :--- | :---: | :---: | :---: |
| **Total Trades** | 1 | 51 | +50 |
| **Win Rate** | 0.0% | 19.61% | +19.61% |
| **Loss Rate** | 100.0% | 80.39% | -19.61% |
| **Profit Factor** | 0.0 | 0.67 | - |
| **Net PnL** | $-46.08 | $-1,051.08 | $-1,005.00 |
| **Expectancy (R)** | -0.9216R | -0.4149R | +0.5067R |
| **Average R** | -0.9216R | -0.4149R | +0.5067R |
| **CAGR** | -0.42% | -9.67% | -9.25% |
| **Max Drawdown** | 0.46% | 10.51% | +10.05% |
| **Sharpe Ratio** | -0.945 | -0.951 | -0.006 |
| **Sortino Ratio** | 0.000 | -0.740 | -0.740 |
| **Avg Holding Time** | 3.50h | 2.21h | - |
| **Avg Quality Score** | 87.70 | 71.55 | - |
| **Avg Selector Score** | 74.80 | 76.17 | - |

---

## Trade Overlap Analysis

A detailed comparison of trades taken by each configuration:
- **Total unique trades**: 52
- **Trades taken by BOTH systems**: 0
- **Trades only taken by Baseline**: 1
- **Trades only taken by Recalibrated**: 51

Unique trades and their details can be inspected in `trade_overlap.csv`.

---

## Threshold Sensitivity

We tested score thresholds from 50 to 85.

| Threshold | Trades | Win Rate (%) | Profit Factor | Expectancy (R) | Max Drawdown (%) | Net PnL ($) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| 50.0 | 20 | 20.0% | 0.557 | -0.6865R | 11.69% | $-687.30 |
| 55.0 | 20 | 20.0% | 0.557 | -0.6865R | 11.69% | $-687.30 |
| 60.0 | 75 | 18.67% | 0.96 | -0.0150R | 10.06% | $-150.31 |
| 65.0 | 82 | 20.73% | 1.13 | 0.1392R | 10.08% | $492.34 |
| 70.0 | 51 | 19.61% | 0.67 | -0.4149R | 10.51% | $-1,051.08 |
| 75.0 | 6 | 0.0% | 0.0 | -1.2653R | 3.74% | $-373.68 |
| 80.0 | 0 | 0.0% | 0.0 | 0.0000R | 0.0% | $0.00 |
| 85.0 | 0 | 0.0% | 0.0 | 0.0000R | 0.0% | $0.00 |

### Recommendation
The statistically strongest threshold is **65.0** (maximizing Sharpe ratio and expectancy). We recommend this over simply maximizing trade counts to ensure robust quality filters remain active.

---

## Weight Sensitivity

Each quality scoring component weight was perturbed by ±10%, re-normalizing the remaining parameters to sum to 1.0.

| Component | Perturbation | Trades | Win Rate (%) | Profit Factor | Expectancy (R) | Net PnL ($) | Max Drawdown (%) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| order_flow | +10% | 51 | 19.61% | 0.67 | -0.4149R | $-1,051.08 | 10.51% |
| order_flow | -10% | 52 | 21.15% | 0.715 | -0.3758R | $-985.79 | 10.45% |
| liquidity | +10% | 33 | 18.18% | 0.462 | -0.6994R | $-1,112.47 | 11.12% |
| liquidity | -10% | 50 | 20.0% | 0.67 | -0.4215R | $-1,047.29 | 10.47% |
| market_structure | +10% | 50 | 20.0% | 0.67 | -0.4215R | $-1,047.29 | 10.47% |
| market_structure | -10% | 51 | 19.61% | 0.67 | -0.4149R | $-1,051.08 | 10.51% |
| volatility | +10% | 29 | 17.24% | 0.446 | -0.7269R | $-1,021.22 | 10.21% |
| volatility | -10% | 50 | 20.0% | 0.68 | -0.4013R | $-1,001.45 | 10.01% |
| session | +10% | 37 | 18.92% | 0.553 | -0.5771R | $-1,042.65 | 10.43% |
| session | -10% | 49 | 20.41% | 0.678 | -0.4117R | $-1,005.98 | 10.06% |
| news | +10% | 50 | 20.0% | 0.68 | -0.4013R | $-1,001.45 | 10.01% |
| news | -10% | 51 | 19.61% | 0.67 | -0.4149R | $-1,051.08 | 10.51% |
| dom | +10% | 51 | 19.61% | 0.664 | -0.4284R | $-1,080.16 | 10.8% |
| dom | -10% | 22 | 13.64% | 0.359 | -1.0098R | $-1,070.52 | 10.71% |

### Instability Analysis
The following components were identified as unstable (causing significant swings in performance metrics when perturbed by ±10%):
- **dom, liquidity, session, volatility**

---

## Safety and Safeguard Verification

During the chronological validation, we monitored the recalibrated configuration for safety violations:
- **Daily Drawdown (3% limit)**: Enforced.
- **Account Drawdown (10% limit)**: Enforced.
- **News Blackout periods**: Enforced.
- **Spread safeguards**: Enforced.
- **Execution cooldown**: Enforced.

**Safety Verification Status**: **FAILED**
Violations detected: Account drawdown exceeded 10% limit on 2025-09-01 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-02 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-03 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-04 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-05 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-08 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-09 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-10 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-11 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-12 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-15 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-16 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-17 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-18 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-19 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-22 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-23 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-24 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-25 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-26 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-29 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-09-30 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-01 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-02 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-03 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-06 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-07 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-08 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-09 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-10 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-13 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-14 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-15 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-16 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-17 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-20 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-21 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-22 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-23 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-24 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-27 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-28 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-29 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-30 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-10-31 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-03 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-04 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-05 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-06 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-07 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-10 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-11 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-12 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-13 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-14 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-17 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-18 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-19 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-20 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-21 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-24 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-25 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-26 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-27 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-11-28 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-01 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-02 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-03 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-04 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-05 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-08 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-09 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-10 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-11 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-12 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-15 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-16 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-17 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-18 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-19 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-22 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-23 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-24 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-26 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-29 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-30 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2025-12-31 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-02 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-05 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-06 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-07 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-08 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-09 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-12 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-13 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-14 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-15 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-16 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-19 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-20 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-21 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-22 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-23 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-26 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-27 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-28 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-29 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-01-30 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-02 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-03 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-04 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-05 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-06 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-09 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-10 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-11 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-12 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-13 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-16 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-17 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-18 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-19 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-20 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-23 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-24 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-25 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-26 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-02-27 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-02 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-03 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-04 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-05 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-06 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-09 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-10 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-11 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-12 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-13 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-16 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-17 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-18 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-19 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-20 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-23 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-24 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-25 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-26 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-27 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-30 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-03-31 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-01 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-02 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-06 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-07 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-08 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-09 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-10 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-13 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-14 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-15 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-16 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-17 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-20 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-21 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-22 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-23 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-24 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-27 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-28 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-29 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-04-30 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-01 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-04 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-05 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-06 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-07 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-08 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-11 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-12 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-13 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-14 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-15 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-18 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-19 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-20 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-21 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-22 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-25 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-26 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-27 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-28 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-05-29 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-01 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-02 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-03 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-04 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-05 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-08 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-09 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-10 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-11 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-12 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-15 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-16 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-17 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-18 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-19 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-22 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-23 (Balance: 8948.92, Peak: 10000.00); Account drawdown exceeded 10% limit on 2026-06-24 (Balance: 8948.92, Peak: 10000.00)
