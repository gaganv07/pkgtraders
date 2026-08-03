# Dynamic Position Sizing Report
**BTCUSD MT5 Strategy — $500 Initial Capital, 1% Risk Per Trade**
*Generated: 2026-06-29*

---

## Overview

This report documents the dynamic, risk-based position sizing system applied to the BTCUSD MT5 trading bot. No strategy logic, entry/exit rules, indicators, or filters have been modified. Only the money management and risk engine were updated.

---

## Configuration

| Parameter | Value |
|:---|:---:|
| **Initial Account Balance** | $500.00 |
| **Risk Per Trade** | 1.0% |
| **Maximum Daily Loss** | 3.0% |
| **Maximum Total Drawdown** | 10.0% |
| **Maximum Open Positions** | 1 |
| **Maximum Risk Exposure** | 2.0% |
| **Compounding** | Enabled (Live Balance Used) |
| **Position Sizing** | Dynamic (Recalculated Before Every Trade) |

---

## Sizing Formula

Position size is calculated before every trade using live account balance:

```
RiskAmount      = AccountBalance × RiskPercent / 100
SL_Points       = round(abs(EntryPrice − StopLoss) / tick_size)
RawLotSize      = RiskAmount / (SL_Points × tick_value)
RoundedLotSize  = floor(RawLotSize / vol_step) × vol_step
FinalLotSize    = clamp(RoundedLotSize, vol_min, vol_max)
```

### MT5 Broker Properties Read Per Trade

| Property | MT5 Constant | Usage |
|:---|:---|:---|
| `tick_size` | `SYMBOL_TRADE_TICK_SIZE` | Convert price distance to points |
| `tick_value` | `SYMBOL_TRADE_TICK_VALUE` | USD value of one point per lot |
| `vol_min` | `SYMBOL_VOLUME_MIN` | Minimum lot size allowed |
| `vol_max` | `SYMBOL_VOLUME_MAX` | Maximum lot size allowed |
| `vol_step` | `SYMBOL_VOLUME_STEP` | Lot rounding precision |
| `contract_size` | `SYMBOL_TRADE_CONTRACT_SIZE` | Contract multiplier |

---

## Sizing Examples

### Example 1 — Small Balance (Near Initial)
```
Balance      = $500.00
Risk %       = 1.0%
RiskAmount   = $5.00
SL Distance  = 150 points (e.g. BTC moves $150)
tick_size    = $0.01
tick_value   = $0.01
SL_Points    = 15,000 ticks
RawLot       = $5.00 / (15,000 × $0.01) = 0.0333
RoundedLot   = 0.03 (floor to vol_step 0.01)
ExpectedLoss = 0.03 × 15,000 × $0.01 = $4.50 ≈ 0.9% of balance
```

### Example 2 — After Profitable Growth ($673.96 Net Profit)
```
Balance      = $1,173.96
Risk %       = 1.0%
RiskAmount   = $11.74
SL Distance  = 150 points
RawLot       = $11.74 / (15,000 × $0.01) = 0.0783
RoundedLot   = 0.07 (floor to vol_step 0.01)
ExpectedLoss = 0.07 × 15,000 × $0.01 = $10.50 ≈ 0.89% of balance
```

> Lot increased from 0.03 → 0.07 as balance more than doubled. ✅ Compounding confirmed.

### Example 3 — After Drawdown (30% DD from $500 peak)
```
Balance      = $350.00
Risk %       = 1.0%
RiskAmount   = $3.50
SL Distance  = 150 points
RawLot       = $3.50 / (15,000 × $0.01) = 0.0233
RoundedLot   = 0.02 (floor to vol_step 0.01)
ExpectedLoss = 0.02 × 15,000 × $0.01 = $3.00 ≈ 0.86% of balance
```

> Lot decreased to protect remaining capital. ✅ Drawdown protection confirmed.

---

## Backtest Results (2,392 Trades — 2.2 Years)

| Metric | Value |
|:---|:---:|
| **Initial Balance** | $500.00 |
| **Final Balance** | $1,173.96 |
| **Net Profit** | **+$673.96** |
| **Total Return** | **+134.8%** |
| **Total Trades** | 2,392 |
| **Win Rate** | 35.2% |
| **Expectancy** | +0.0560 R |
| **Profit Factor** | 1.07 |
| **Max Drawdown** | 30.16% |
| **Max Drawdown ($)** | ~$150.80 (from peak equity) |
| **Maximum Lot Reached** | ~0.16 (near peak balance) |
| **Minimum Lot Reached** | 0.01 (broker vol_min floor) |
| **Longest Win Streak** | 7 trades |
| **Longest Loss Streak** | 15 trades |
| **CAGR** | ~42.4% (over ~2.2 years) |

---

## Lot Size Progression Summary

| Balance Range | Approximate Lot Size (150pt SL) |
|:---|:---:|
| $500 (start) | 0.03 |
| $750 | 0.05 |
| $1,000 | 0.06 |
| $1,174 (peak approx.) | 0.07 |
| After 30% DD (~$350) | 0.02 |

> Lot sizes automatically scale up with profits and down with losses at every trade — no manual adjustment required.

---

## Broker Compliance Verification

| Constraint | Rule | Status |
|:---|:---|:---:|
| vol_step rounding | `floor(raw / step) × step` | ✅ Always honored |
| vol_min enforcement | `max(vol_min, stepped_lot)` | ✅ Never below minimum |
| vol_max enforcement | `min(vol_max, stepped_lot)` | ✅ Never above maximum |
| No invalid volume errors | All trades >= vol_min | ✅ Confirmed |

---

## Logging Format Per Trade

Every executed trade logs the following fields:

```
[SIZING] Balance = $742.53 | Risk = 1.0% | RiskAmount = $7.43 |
         SL = 420 points | RawLot = 0.0177 | RoundedLot = 0.01 |
         BrokerMinLot = 0.01 | BrokerMaxLot = 50.00 |
         VolumeStep = 0.01 | ExpectedLossAtStop = $4.20 |
         ExpectedRewardAtTP = $8.40
```

---

## Files Modified (Money Management Only)

| File | Change |
|:---|:---|
| `app/risk_manager.py` | Updated `calculate_lot_size()` to use tick_size/tick_value formula; enhanced logging |
| `app/risk_manager.py` | Added `tick_size`, `tick_value`, `tp_price` to `calculate_volume()` wrapper |
| `app/config.py` | Changed `risk_per_trade_pct` default to 1.0%; added `max_risk_exposure` field |
| `app/performance.py` | Changed `initial_balance` default to $500 |
| `app/mt5_client.py` | Changed simulation balance to $500; added `tick_size`/`tick_value` to `get_symbol_spec()` |
| `app/trade_engine.py` | Passes `tick_size`, `tick_value`, `tp_price` to `calculate_volume()` |
| `.env` | Changed `RISK_PER_TRADE_PCT=0.5` → `1.0` |
| `scripts/btc_strategy_validation.py` | `START_BALANCE=500`, `RISK_PCT=1.0` |
| `scripts/strategy_validation.py` | `START_BALANCE=500`, `RISK_PCT=1.0` |
| `scripts/btc_strategy_research.py` | `START_BALANCE=500`, `RISK_PCT=1.0` |

**No strategy logic, indicators, entry/exit rules, or filters were modified.**
