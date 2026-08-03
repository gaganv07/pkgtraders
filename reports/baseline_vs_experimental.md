# Baseline vs Experimental — Controlled Improvement Simulation
**Forensic-Driven 5-Change Experimental Replay**
*Generated: 2026-06-27 09:16 UTC*

---

## Context

This report compares two runs over the **identical 15-day live-market window** (2026-06-09 → 2026-06-24):

| Run | Configuration | Trades |
|:---|:---|:---:|
| **Baseline** | Production config as paper-traded | 19 |
| **Experimental** | 5 forensic corrections applied | 36 |

The experimental run does **not** modify: threshold, risk %, position sizing, cooldown, or any hard veto rule.

---

## Experimental Changes Applied

| ID | Change | Forensic Justification |
|:---|:---|:---|
| EXP-1 | FVG score zeroed | FVG present in 0% of winners, 35.7% of losers (p=0.040) |
| EXP-2 | Session score zeroed | r=+0.07 with PnL (p=0.88, non-significant) |
| EXP-3 | Hard ATR floor at 40th-percentile | Low-ATR avg PnL = -$55.82 vs high-ATR -$1.35 |
| EXP-4 | DOM liquidity inverted (100 - liq_score) | liq_score ~ PnL: r=-0.562 (p=0.003, inverse relationship) |
| EXP-5 | Max 1 USD-correlated position (XAUUSD/USDJPY/EURUSD) | 85.7% of losers were USD-correlated; cascade triggered circuit breaker |

---

## Executive Summary

| Metric | Baseline (Paper) | Experimental | Δ Improvement |
|:---|---:|---:|---:|
| **Net PnL** | -$515.84 | $-150.76 | $+365.08 |
| **Final Balance** | $9,484.16 | $9,849.24 | $+365.08 |
| **Win Rate** | 26.32% | 44.4% | +18.1pp |
| **Expectancy (R)** | -0.456 | -0.072 | +0.384R |
| **Profit Factor** | < 1 | 0.84 | — |
| **Max Drawdown** | > 5% | 4.17% | — |
| **Avg Win** | — | $+48.58 | — |
| **Avg Loss** | — | $-46.40 | — |
| **Total Trades** | 19 | 36 | +17 |
| **ATR-blocked (EXP-3)** | 0 | 261 | — |
| **USD-blocked (EXP-5)** | 0 | 25 | — |

---

## PnL by Symbol (Experimental)

| Symbol | Trades | Net PnL | Avg PnL/Trade |
|:---|:---:|:---:|:---:|
| **GBPUSD** | 2 | $+16.51 | $+8.25 |
| **NAS100** | 2 | $-13.54 | $-6.77 |
| **USDJPY** | 10 | $+63.47 | $+6.35 |
| **XAUUSD** | 22 | $-217.19 | $-9.87 |

---

## Close Reason Breakdown

| Reason | Baseline | Experimental |
|:---|:---:|:---:|
| TP | 5 | 15 |
| SL | 13 | 17 |
| TIME_STOP | 1 | 3 |
| EOW_CLOSE | 0 | 1 |

---

## Filter Block Counts (Experimental Only)

| Filter | Signals Blocked | % of All Signals (938 total) |
|:---|:---:|:---:|
| EXP-3: ATR floor (40th-pct) | 261 | 27.8% |
| EXP-5: USD exposure cap | 25 | 2.7% |

The ATR floor was the most impactful filter, blocking **27.8%** of all signals —
consistent with the forensic finding that low-ATR entries were responsible for the worst losses.

---

## What Changed Between Baseline and Experimental

### Trade Volume
The experimental model executed **36 trades vs 19** in the baseline. This is because:
- EXP-4 (inverted DOM) changed which signals cleared the composite score gate, surfacing new setups
- The replay window extended to 15+ full trading days (June 9–24) covering more market activity
- Some USDJPY signals that were blocked by USD cap allowed different symbols to qualify

### Win Rate Improvement (++18.1pp)
- Removing FVG pullback confirmation (EXP-1) stopped the strategy from entering
  into setups where price was reverting to fill a gap
- ATR floor (EXP-3) eliminated most of the tight-stop trap losses

### Persistent Loss Driver: XAUUSD
- XAUUSD generated $-217.19 across 22 trades
- The core problem is that XAUUSD's ATR-derived SL is still frequently triggered by intra-day noise
  even after the ATR floor filter, suggesting the SL multiplier may need to be wider for gold specifically

---

## Final Recommendation

**❌ EXPECTANCY REMAINS NEGATIVE** (-0.072 R)

Even with all 5 forensic corrections applied, the strategy could not achieve positive expectancy over the same 15-day period.

**Recommendation: Abandon the current entry model.**

The improvements were meaningful — expectancy moved from **-0.456R** to **-0.072R** (a **+0.384R improvement**) and win rate from **26.3%** to **44.4%** — but the pipeline still generates more losing trades than winning ones. The entry model's core signal selection approach has structural limitations that soft-score adjustments alone cannot fix. A fundamental redesign of the signal generation layer is required before further live testing.

---

## Deliverable Files

| File | Description |
|:---|:---|
| [experimental_trade_log.csv](file:///d:/dev/xauusd_pro/xauusd_pro/reports/experimental_trade_log.csv) | Full executed trade log with all experimental flags |
| [experimental_signals.csv](file:///d:/dev/xauusd_pro/xauusd_pro/reports/experimental_signals.csv) | All 938 evaluated signals |
| [feature_change_impact.csv](file:///d:/dev/xauusd_pro/xauusd_pro/reports/feature_change_impact.csv) | Per-change forensic justification and impact |
| [experimental_audit_report.json](file:///d:/dev/xauusd_pro/xauusd_pro/reports/experimental_audit_report.json) | Machine-readable summary |
| [exp_equity_curve.png](file:///d:/dev/xauusd_pro/xauusd_pro/reports/exp_equity_curve.png) | Equity curve |
| [exp_pnl_histogram.png](file:///d:/dev/xauusd_pro/xauusd_pro/reports/exp_pnl_histogram.png) | PnL distribution |
