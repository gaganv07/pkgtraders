# Pre-Migration Backup Report

**System Name:** XAUUSD Pro Trading Bot  
**Backup Timestamp:** 2026-08-04 10:06:00 UTC  
**Previous Broker Account:** Vantage Markets Demo (`#25687070`)  
**Target Migration Broker:** BlackBull Markets  

---

## 1. Environment & MT5 Connection Backup (`.env`)

| Environment Key | Pre-Migration Value | Description |
| :--- | :--- | :--- |
| `MT5_LOGIN` | `25687070` | Vantage Demo Account Login ID |
| `MT5_PASSWORD` | `c!&S7Afx` | Account Password (Masked for Security) |
| `MT5_SERVER` | `VantageMarkets-Demo AS01` | Vantage MT5 Demo Server Name |
| `MT5_PATH` | `C:\Program Files\MetaTrader 5\terminal64.exe` | Main MT5 Executable Path |
| `MAGIC_NUMBER` | `20250701` | System Expert Advisor Magic ID |
| `SYMBOL` | `XAUUSD` | Target Symbol Override |
| `TIMEFRAME` | `M15` | Default Analysis Timeframe |

---

## 2. Pre-Migration Broker Specifications

| Parameter | Recorded Vantage Live State |
| :--- | :--- |
| **Account Holder** | `KUSHANTH M` |
| **Account Number** | `#25687070` |
| **Broker Company** | `Vantage Markets (Pty) Ltd` |
| **Server Name** | `VantageMarkets-Demo` / `VantageMarkets-Demo AS01` |
| **Account Mode** | `Demo` |
| **Account Balance** | `$500.00 USD` |
| **Account Equity** | `$500.00 USD` |
| **Free Margin** | `$500.00 USD` |
| **Leverage Ratio** | `1:100` |
| `AutoTrading` / `EA Allowed` | `True` |

---

## 3. Pre-Migration Symbol Mapping & Resolution Rules

Canonical symbols configured in system:
- `XAUUSD` → `XAUUSD` (Variants: `XAUUSDm`, `XAUUSD.a`, `XAUUSD+`, `Gold`, `GOLD`)
- `BTCUSD` → `BTCUSD` (Variants: `BTCUSDm`, `BTCUSD+`, `BTC/USD`, `BITCOIN`)
- `EURUSD` → `EURUSD` (Variants: `EURUSDm`, `EURUSD.a`, `EURUSD+`)
- `GBPUSD` → `GBPUSD` (Variants: `GBPUSDm`, `GBPUSD.a`, `GBPUSD+`)
- `USDJPY` → `USDJPY` (Variants: `USDJPYm`, `USDJPY.a`, `USDJPY+`)
- `NAS100` → `NAS100` (Variants: `NAS100m`, `NASDAQ`, `US100`, `USTEC`)
- `US30`   → `US30`   (Variants: `US30m`, `DJ30`, `DJIA`, `DOW30`, `WS30`)

---

## 4. Reports & System Configuration Backup

- **Database Path:** `database/trading.db`
- **Dashboard Host/Port:** `0.0.0.0:8080`
- **Risk Limits:** `INITIAL_BALANCE=500`, `RISK_PER_TRADE_PCT=1.0%`, `DAILY_DD_LIMIT_PCT=3.0%`, `MIN_QUALITY_SCORE=85`
- **ML Layer:** `ML_ENABLED=true`, `USE_RECALIBRATED_SCORING=true`, `SHADOW_MODE=false`

---

> [!NOTE]
> Backup completed successfully. Phase 2 (Configuration Update) can proceed safely.
