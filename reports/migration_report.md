# Migration Report — Universal Dynamic Risk & Money Management Upgrade

**Date**: 2026-06-30  
**Author**: Antigravity  
**Status**: ✅ Complete

---

## Executive Summary

The money management layer of the XAU/USD Pro MT5 trading bot has been upgraded to a universal, dynamic, risk-based position sizing engine. This upgrade covers **every symbol** and **every strategy** in the project.

> **Strategy logic was not modified.** Entry conditions, exit conditions, indicators, filters, signal generation, trend logic, order flow, BOS, MSS, FVG, liquidity logic, session filters, news filters, TP/SL logic, and backtesting engine logic remain **exactly as they were**.

---

## What Changed

### New Files

| File | Purpose |
|:---|:---|
| `app/position_sizer.py` | Single canonical sizing engine — all strategies call this |
| `scripts/generate_risk_reports.py` | Generates all 8 management reports |

### Modified Files

| File | Change Summary |
|:---|:---|
| `app/config.py` | Added `initial_balance`, `compounding_enabled`; updated `max_open_trades` 1→3, `weekly_dd_limit` 7→6%, `max_risk_exposure` 2→3% |
| `.env` | Added `INITIAL_BALANCE=500`, `COMPOUNDING_ENABLED=true`, `MAX_OPEN_TRADES=3`, `MAX_RISK_EXPOSURE_PCT=3.0`, `WEEKLY_DD_LIMIT_PCT=6.0` |
| `app/risk_manager.py` | Rewrote to delegate sizing to `PositionSizer`; added `open_risk_pct` field to `DrawdownState`; added `approve_with_exposure()`; updated `on_open(risk_pct)` and `on_close(risk_pct)` |
| `app/mt5_client.py` | Added `ETHUSD` to `_SYM_VARIANTS`, `_SIM_PRICES`, `_SIM_SPREADS`, `_SIM_CONTRACT`; added `_SIM_TICK_SPECS` dict with accurate per-symbol `tick_size` and `tick_value`; upgraded `get_symbol_spec()` sim path to use `_SIM_TICK_SPECS` |
| `app/trade_engine.py` | Imported `PositionSizer`, `BrokerSpec`; replaced `calculate_volume()` call with `PositionSizer.size()`; updated `approve()` → `approve_with_exposure()`; updated `on_open(risk_pct=)` and `on_close(risk_pct=)` |
| `scripts/btc_strategy_validation.py` | Replaced `calculate_lot_size` import/call with `PositionSizer.size()` + `BrokerSpec.fallback()` |
| `scripts/strategy_validation.py` | Same as above; removed hardcoded `VOLUME_SPECS` dict |
| `scripts/btc_strategy_research.py` | Same as above; removed hardcoded sizing constants |
| `tests/test_all.py` | Fixed `TestRiskManager` for new defaults; added `TestPositionSizer` (13 tests), `TestDynamicCompounding` (1 test), `TestBrokerCompliance` (5 tests), `TestRiskExposure` (4 tests) |

---

## Architecture: Before vs After

### Before
```
TradeEngine._open()
  └── self._risk.calculate_volume(balance, entry, sl, cs, vol_min, ...)
        └── calculate_lot_size(...)  [in risk_manager.py]
              └── formula: RawLot = balance * risk% / (sl_dist * cs)  [no tick awareness]

Scripts (btc_strategy_validation, strategy_validation, btc_strategy_research)
  └── calculate_lot_size(...)  [direct import from risk_manager, hardcoded specs]
```

### After
```
TradeEngine._open()
  ├── BrokerSpec.from_spec_dict(client.get_symbol_spec(symbol))  [live tick specs]
  ├── PositionSizer.size(balance, entry, sl, spec, risk_pct, ...)
  │     └── formula: RawLot = balance * risk% / (sl_points * tick_value)  [tick-aware]
  │     └── auto-appends SizingResult to reports/position_size_history.csv
  └── approve_with_exposure(risk_pct)  [exposure gate enforced]

Scripts (all 3)
  └── PositionSizer.size(..., spec=BrokerSpec.fallback(sym), write_csv=False)
        └── identical formula, no external dependency

RiskManager
  ├── calculate_volume(...)  → delegates to calculate_lot_size() → PositionSizer.size()
  ├── on_open(risk_pct)      → tracks DrawdownState.open_risk_pct
  └── on_close(pnl, risk_pct) → releases exposure slot
```

---

## Position Sizing Formula

```
RiskAmount  = AccountBalance × (RiskPercent / 100)
SL_Points   = round(|Entry - StopLoss| / TickSize)
RawLot      = RiskAmount / (SL_Points × TickValue)
SteppedLot  = floor(RawLot / VolStep) × VolStep    ← always conservative
FinalLot    = clamp(SteppedLot, VolMin, VolMax)    ← broker compliance
```

**Key properties:**
- `math.floor` is used — never over-risks by rounding up
- Recalculated from live balance before every trade (auto-compounding)
- Broker constraints enforced per-symbol (vol_min, vol_max, vol_step, tick_size, tick_value)
- If result is 0 (balance too small), trade is skipped — no bad orders sent

---

## Configuration Defaults

| Parameter | Before | After |
|:---|:---:|:---:|
| `INITIAL_BALANCE` | N/A | **$500** |
| `RISK_PER_TRADE_PCT` | 1.0% | 1.0% |
| `COMPOUNDING_ENABLED` | N/A | **true** |
| `MAX_OPEN_TRADES` | 1 | **3** |
| `MAX_RISK_EXPOSURE_PCT` | 2.0% | **3.0%** |
| `WEEKLY_DD_LIMIT_PCT` | 7.0% | **6.0%** |
| `DAILY_DD_LIMIT_PCT` | 3.0% | 3.0% |
| `ACCOUNT_DD_LIMIT_PCT` | 10.0% | 10.0% |

---

## Symbols Covered

| Symbol | Contract | TickSize | TickValue | Status |
|:---|:---:|:---:|:---:|:---:|
| XAUUSD | 100 | 0.01 | $1.00 | ✅ |
| EURUSD | 100,000 | 0.0001 | $1.00 | ✅ |
| GBPUSD | 100,000 | 0.0001 | $1.00 | ✅ |
| USDJPY | 100,000 | 0.001 | $0.0067 | ✅ |
| BTCUSD | 1 | 0.01 | $0.01 | ✅ |
| ETHUSD | 1 | 0.01 | $0.01 | ✅ **NEW** |
| NAS100 | 1 | 0.01 | $0.01 | ✅ |
| US30 | 1 | 0.01 | $0.01 | ✅ |

---

## Reports Generated

| Report | Path | Contents |
|:---|:---|:---|
| 1 | `reports/dynamic_risk_report.md` | Formula, config snapshot, summary stats |
| 2 | `reports/lot_progression.csv` | Per-trade lot history |
| 3 | `reports/account_growth.csv` | Balance/equity time series |
| 4 | `reports/risk_statistics.md` | Per-symbol lot distribution |
| 5 | `reports/position_size_history.csv` | All 29 fields written live per trade |
| 6 | `reports/drawdown_analysis.md` | Daily DD table + max drawdown |
| 7 | `reports/margin_usage.csv` | Per-trade margin estimates |
| 8 | `reports/performance_summary.md` | PnL, CAGR, Sharpe, PF, WR |

Run with:
```bash
python scripts/generate_risk_reports.py           # from live data
python scripts/generate_risk_reports.py --demo    # with synthetic data
```

---

## Attestations

- ✅ No strategy logic was modified
- ✅ Every trade uses dynamic balance-based sizing
- ✅ Auto-compounding: lot grows with balance, shrinks with losses
- ✅ Broker compliance enforced (vol_step floor-rounding, vol_min/max clamp)
- ✅ Universal: one `PositionSizer` for all symbols and all strategies
- ✅ All scripts use `$500` as baseline
- ✅ `position_size_history.csv` written on every live trade (29 fields per row)
- ✅ All existing tests pass; 23 new tests added
