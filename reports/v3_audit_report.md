# V3 Strategy Audit Report
**Generated**: 2026-07-16 18:58 UTC

## Executive Summary

Comparison of three scoring engines replayed on live M15 bar history.
Trade simulation: SL/TP filled at actual bar H/L; 30-bar time stop.

### Certification Criteria
| Criterion | Target |
|:---|:---|
| Trade Count | ≥ 100 |
| Expectancy | ≥ +0.10 R |
| Profit Factor | ≥ 1.20 |
| Max Drawdown | < 12% |

---

## Performance Comparison

| Engine | Trades | Win Rate | Expectancy | PF | Max DD | Net PnL | Sharpe | Status |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|
| **V3** | 0 | 0.0% | +0.0000R | 0.000 | 0.00% | $+0.00 | 0.000 | ❌ NOT CERTIFIED (1/4 criteria) |
| **Recalibrated** | 4710 | 31.95% | -0.3607R | 0.260 | 1719216.42% | $-170,650,562.23 | -0.387 | ❌ NOT CERTIFIED (1/4 criteria) |
| **Legacy** | 0 | 0.0% | +0.0000R | 0.000 | 0.00% | $+0.00 | 0.000 | ❌ NOT CERTIFIED (1/4 criteria) |

---

## Per-Engine Detail

### V3 Engine

| Metric | Value |
|:---|---:|
| **Total Trades** | 0 |
| **Win Rate** | 0.0% |
| **Expectancy** | +0.0000 R |
| **Profit Factor** | 0.000 |
| **Max Drawdown** | 0.00% |
| **Net PnL** | $+0.00 |
| **Sharpe (R-based)** | 0.000 |

### Recalibrated Engine

| Metric | Value |
|:---|---:|
| **Total Trades** | 4710 |
| **Win Rate** | 31.95% |
| **Expectancy** | -0.3607 R |
| **Profit Factor** | 0.260 |
| **Max Drawdown** | 1719216.42% |
| **Net PnL** | $-170,650,562.23 |
| **Sharpe (R-based)** | -0.387 |

**Quality Score Distribution** (4710 accepted signals):
- Mean: 69.4
- Median: 68.7
- Std Dev: 3.5
- Min / Max: 65.0 / 83.5

**PnL by Symbol:**
- EURUSD: $-25,236.22 (0/254 wins)
- GBPUSD: $-12,420.17 (0/125 wins)
- NAS100: $-35,164.63 (489/1332 wins)
- US30: $-51,242.81 (549/1623 wins)
- USDJPY: $-170,495,812.27 (47/228 wins)
- XAUUSD: $-30,686.13 (420/1148 wins)

### Legacy Engine

| Metric | Value |
|:---|---:|
| **Total Trades** | 0 |
| **Win Rate** | 0.0% |
| **Expectancy** | +0.0000 R |
| **Profit Factor** | 0.000 |
| **Max Drawdown** | 0.00% |
| **Net PnL** | $+0.00 |
| **Sharpe (R-based)** | 0.000 |

---

## V3 Key Changes vs Recalibrated

| Change | Old Behaviour | New Behaviour | Forensics Basis |
|:---|:---|:---|:---|
| **FVG confluence** | +8 to ms_score | -10 penalty | p=0.040, 0% winners had FVG |
| **DOM liquidity** | Higher = better | Medium ideal (40-65), high (>75) penalised | corr=-0.562, p=0.0034 |
| **ATR veto** | None | Hard reject if ATR pct < 25th | Low-ATR avg loss -$55.82 |
| **Order flow weight** | 22% | 35% | corr=+0.520 with PnL |
| **Session weight** | 8.8% | 5% | corr=+0.07, hard veto sufficient |
| **News weight** | 19.3% | 5% | Was constant 50.0, uninformative |
| **EMA veto (OF)** | No hard veto | OF < 30 vetoes LONG; OF > 70 vetoes SHORT | Directional clarity |

---

## Files
- `reports/v3_executed_trades.csv` — per-trade detail for V3 engine
- `reports/v3_audit.log` — full audit log