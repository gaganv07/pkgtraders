# P8 ORB V2 Validation Report
**Generated**: 2026-07-16 18:53 UTC

## P8 vs P4 Walk-Forward Comparison

P8 is a forensics-guided redesign of P4 Opening Range Breakout.
Key fixes: wider SL (max of OR range vs ATR), dual-TF EMA requirement, 
stricter volume threshold (1.5×), ATR percentile floor (≥40), 
shortened trade window (08:00–11:30 UTC).

| Metric | P4 (Baseline) | P8 (V2) | Δ |
|:---|:---:|:---:|:---:|
| **Trades** | 82 | 32 | -50 |
| **Win Rate** | 3.66% | 6.25% | +2.59% |
| **Expectancy** | -0.9268R | -0.8293R | +0.0975R |
| **Profit Factor** | 0.109 | 0.085 | -0.024 |
| **Max DD** | 50.39% | 22.23% | -28.16% |
| **Net PnL** | $-5,038.70 | $-2,222.97 | $+2,815.73 |
| **Sharpe** | -2.453 | -1.696 | +0.757 |
| **Prob. of Ruin** | 100.00% | 87.40% | -12.60% |

---

## Certification Scorecard

| Requirement | Threshold | P4 | P8 |
|:---|:---|:---:|:---:|
| **Expectancy** | ≥ +0.10 R | -0.9268R ❌ | -0.8293R ❌ |
| **Profit Factor** | ≥ 1.20 | 0.109 ❌ | 0.085 ❌ |
| **Max Drawdown** | < 12% | 50.39% ❌ | 22.23% ❌ |
| **Sample Size** | ≥ 100 | 82 ❌ | 32 ❌ |
| **Prob. of Ruin** | < 5% | 100.00% ❌ | 87.40% ❌ |

**P4 Decision**: ❌ NOT CERTIFIED (0/5)
**P8 Decision**: ❌ NOT CERTIFIED (0/5)

---

## Monte Carlo Detail

| Parameter | P4 | P8 |
|:---|:---:|:---:|
| Simulations | 1000 | 1000 |
| Prob. of Ruin (20% DD) | 100.00% | 87.40% |
| Median Final Balance | $7,999.84 | $7,952.18 |

---

## P8 Design Changes from P4

| Attribute | P4 | P8 | Rationale |
|:---|:---|:---|:---|
| SL distance | 0.3× ATR | max(OR range, 1.0× ATR) | P4's SL inside intraday noise |
| Volume threshold | 1.2× avg | 1.5× avg | Too many weak-move entries |
| EMA requirement | H1 only | H1 AND M15 | P4 took counter-trend trades |
| ATR percentile | None | ≥ 40 | V3 finding: low-ATR traps |
| OR range filter | ≥ 0.2× ATR | ≥ 1.5× ATR | Old filter was trivially easy |
| Trade window end | 13:00 UTC | 11:30 UTC | Late signals had poor fills |

---

## Files
- `reports/p8_trades.csv` — P8 per-trade log
- `reports/p4_trades.csv` — P4 baseline per-trade log
- `reports/p8_validation.log` — full validation log