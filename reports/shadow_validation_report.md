# Shadow Validation Report: Legacy vs. Recalibrated
**Trade Quality Engine Shadow Mode Performance Analysis**
*Generated: 2026-06-24 18:15 UTC*

---

## 1. Executive Summary

This report documents the performance of the trade quality scoring engine in **shadow mode** over a 15-day chronological validation window (evaluating all symbols: `XAUUSD`, `EURUSD`, `GBPUSD`, `USDJPY`, `NAS100`, `US30`).

During this phase, the bot was configured as follows:
- `USE_RECALIBRATED_SCORING = False` (Legacy scoring active and executing trades)
- `SHADOW_MODE = True` (Recalibrated scoring evaluated in parallel, logged but never executed)

### Deployment Recommendation

> [!TIP]
> **Final Recommendation: Ready for paper trading**
> Recalibrated scoring ran without any crashes or exceptions. It successfully unlocked 163 setups (18.67% of evaluated signals) while legacy scoring unlocked 0 trades due to an unreachable 85.0 threshold. We recommend proceeding to paper trading on a MT5 demo account to validate real-time execution, execution latency, and slippage before any live deployment.

---

## 2. Shadow Mode Metrics Summary

| Metric | Legacy Engine | Recalibrated Engine (Shadow) | Status / Disagreement |
| :--- | :---: | :---: | :---: |
| **Total Signals Evaluated** | 873 | 873 | - |
| **Accepted Trades (Score >= Thresh)** | 0 | 163 | 163 Disagreements |
| **Rejected Signals** | 873 | 710 | - |
| **Average Score** | 61.8 | 64.8 | +3.0 Difference |
| **Maximum Score** | 86.3 | 91.6 | +5.3 Difference |
| **Minimum Score** | 39.5 | 39.9 | +0.4 Difference |

---

## 3. Score Distributions

Both engines produced continuous score distributions, but the recalibrated engine shifted the mean upward and smoothed out discrete step functions:

### Legacy Engine Scores
- **Mean**: 61.81
- **Standard Deviation**: 8.45
- **Minimum**: 39.50
- **25% Percentile**: 55.70
- **Median (50%)**: 61.70
- **75% Percentile**: 68.10
- **Maximum**: 86.30

### Recalibrated Engine Scores (Shadow)
- **Mean**: 64.77
- **Standard Deviation**: 8.68
- **Minimum**: 39.90
- **25% Percentile**: 58.80
- **Median (50%)**: 65.20
- **75% Percentile**: 70.60
- **Maximum**: 91.60

---

## 4. Hard Veto Frequencies

Vetoes act as hard safeguards to reject signals regardless of score. The frequencies of activated vetoes were tracked separately:

### Legacy Engine Vetoes (Total Evaluated: 873)
- **Outside active session**: 237 counts
- **Outside active session & EMA opposing trend**: 140 counts
- **EMA opposing trend**: 108 counts
- **Order Flow opposing trend**: 78 counts
- **Outside active session & Order Flow opposing trend**: 76 counts
- **ATR filter failed & Order Flow opposing trend**: 9 counts
- **Outside active session & Spread too high**: 7 counts
- **Other combinations**: 18 counts
- **No vetoes**: 194 counts (all rejected due to score below legacy 85.0 threshold)

### Recalibrated Engine Vetoes (Total Evaluated: 873)
- **Outside active session**: 453 counts
- **ATR filter failed**: 15 counts
- **Outside active session & Spread too high**: 12 counts
- **Outside active session & ATR filter failed**: 11 counts
- **Spread too high**: 2 counts
- **No vetoes**: 380 counts (163 accepted, 217 rejected due to score below adaptive 65.0 threshold)

---

## 5. Soft Score Component Statistics

For the recalibrated engine, we analyzed the soft score components (0-100 scale before weights are applied):

| Component | Mean | Std Dev | Min | Max | Weight |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Order Flow** | 56.46 | 18.76 | 9.4 | 95.2 | 22.0% |
| **Liquidity (DOM/Fallback)** | 64.60 | 6.30 | 30.0 | 70.0 | 19.0% |
| **Market Structure** | 60.20 | 17.12 | 30.5 | 85.0 | 25.8% |
| **Volatility** | 56.29 | 25.58 | 10.0 | 95.0 | 5.2% |
| **Session Quality** | 55.17 | 31.73 | 10.0 | 95.0 | 8.8% |
| **News State** | 50.00 | 0.00 | 50.0 | 50.0 | 19.3% |

### ICT Confluence Bonus Activations
- **MSS (Market Structure Shift) detected**: 5.50% of signals
- **FVG (Fair Value Gap) present**: 13.06% of signals
- **Liquidity Sweep**: 10.19% of signals
- **BOS (Break of Structure) detected**: 15.01% of signals

---

## 6. System Verification

We monitored system stability and risk control compliance throughout the shadow validation phase:
- **Crashes / Errors**: **ZERO** crashes or runtime errors were logged.
- **Config Loading**: **PASSED**. dynamic config files `recommended_weights.json` and `recommended_threshold.json` loaded successfully with no warning fallbacks.
- **Scoring Exceptions**: **ZERO** scoring exceptions.
- **Risk Control Violations**: **PASSED**. Since legacy scoring was active and rejected all 873 setups, no trades were executed, resulting in zero drawdown and zero risk exposure. Recalibrated scoring ran strictly in shadow mode with zero execution pathways.
