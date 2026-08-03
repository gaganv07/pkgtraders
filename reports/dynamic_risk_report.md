# Dynamic Risk & Money Management Report

**Generated**: 2026-06-30 07:00 UTC

## Formula

```
RiskAmount  = Balance × (RiskPct / 100)
SL_Points   = round(|Entry - StopLoss| / TickSize)
RawLot      = RiskAmount / (SL_Points × TickValue)
FinalLot    = floor(RawLot / VolStep) × VolStep
FinalLot    = clamp(FinalLot, VolMin, VolMax)
```

## Configuration Snapshot

| Parameter | Value |
|:---|:---|
| initial_balance | 500.0 |
| risk_per_trade_pct | 1.0 |
| compounding | True |
| max_open_trades | 3 |
| max_risk_exposure | 3.0 |
| daily_dd_limit | 3.0 |
| weekly_dd_limit | 6.0 |
| account_dd_limit | 10.0 |

## Summary Statistics

| Metric | Value |
|:---|:---|
| Total Sizing Decisions | 50 |
| Symbols Covered | BTCUSD, EURUSD, XAUUSD |
| Strategies Covered | BTC_P3_OrderFlow, StrategyValidation, XAUUSD_LiveEngine |
| Min Lot | 0.0100 |
| Max Lot | 7.1400 |
| Avg Lot | 0.8686 |
| Std Lot | 1.6242 |
| Avg Risk Amount | $5.00 |
| Avg Expected Loss | $4.37 |
