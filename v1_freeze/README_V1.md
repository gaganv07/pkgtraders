# Strategy V1 — Final Freeze Manifest
**Tag**: `Strategy_V1_Final`
**Frozen**: 2026-06-27

---

## V1 Final Performance Metrics

| Metric | Value |
|:---|---:|
| Paper Trading Net PnL | -$515.84 |
| Win Rate | 26.32% |
| Expectancy (R) | -0.456 |
| Trades (15-day) | 19 |
| Experimental Best | -0.072R (still negative) |

## Verdict
Forensic analysis confirmed structural limitations in the V1 entry model.
5-change experimental correction improved expectancy +0.384R but could not achieve positive expectancy.
**Decision**: Replace entry model entirely. All infrastructure retained.

## Frozen Files (entry model only)
- `app/trade_quality.py` — Composite scorer (FVG, DOM, MSS, OF, session, news)
- `app/market_selector.py` — Symbol ranker (trend, volatility, OF, session, spread, volume)
- `app/microstructure.py` — Structure detector (BOS, CHoCH, FVG, swings)
- `app/order_flow.py` — Order flow engine (CVD, delta, pressure, absorption)
- `scripts/strategy_audit.py` — Production replay engine
- `scripts/strategy_audit_experimental.py` — Forensic experimental engine (5 corrections)

## Infrastructure Retained Unchanged
- `app/risk_manager.py` — Position sizing, drawdown, circuit breaker
- `app/trade_engine.py` — Execution, SL/TP, trailing, partial TPs
- `app/mt5_client.py` — Broker interface
- `app/market_data.py` — Bar/tick data, ATR, EMA, VWAP
- `app/session.py` — Session + news calendar
- `app/config.py` — Settings
- `backtesting/engine.py` — Walk-forward backtesting
- `scripts/strategy_research.py` — V2 research harness
