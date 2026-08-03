# MT5 Terminal Process Lifecycle & Connection Audit Report

**System Name:** Legacy Asset Partners — Institutional AI Trading System  
**Audit Timestamp:** 2026-08-03 22:12:00 UTC  
**Target Account:** `#25687070` (Vantage Demo Account)  
**Resolution Status:** `RESOLVED & VERIFIED`

---

## 1. Root-Cause Analysis

### Problem Description
The MT5 Terminal GUI (`terminal64.exe`) was closing automatically shortly after the Python trading bot started execution.

### Identified Causes
1. **Premature Account Assertion before Handshake Completion:**
   - When `mt5.login(25687070, password, server="VantageMarkets-Demo AS01")` was called, the MetaTrader 5 terminal initiated network authentication with Vantage servers.
   - Querying `mt5.account_info()` on the exact same millisecond returned the pre-login terminal state (e.g. account `#907901`).
   - The strict target account assertion evaluated `account_info().login != 25687070` to `True`, triggered `disconnect_mt5()`, called `mt5.shutdown()`, and exited `main.py`, shutting down the MT5 terminal window.

2. **Terminal Process Termination on `mt5.shutdown()`:**
   - When MT5 is launched via `subprocess.Popen([path])`, calling `mt5.shutdown()` terminates the child terminal process `terminal64.exe`.
   - Any transient failure during initialization caused `mt5.shutdown()` to close the user's terminal window.

---

## 2. Implemented Resolutions

### A. Server Handshake Polling (`app/mt5_connection.py`)
- Added a 5-second polling retry loop immediately following `mt5.login()` to allow Vantage network authentication to complete before querying `mt5.account_info()`.
- Added detailed log markers (`[STARTUP]`, `[CONNECTION]`, `[LOGIN]`, `[MAIN_LOOP]`, `[RECONNECT]`, `[SHUTDOWN]`) across all lifecycle phases.

### B. Terminal Protection & Graceful Reconnection
- Updated `disconnect_mt5()` so that `mt5.shutdown()` is called gracefully only during explicit application exit (`KeyboardInterrupt` / `SIGTERM`), preventing premature process termination during transient connection retries.

### C. Main Execution Loop Resilience (`app/main.py`)
- Verified that all main orchestration loops (`_tick_loop`, `_bar_loop`, `_account_loop`) catch exceptions gracefully, attempt automatic reconnection (`client.reconnect()`), and continue running continuously without shutting down MT5.

---

## 3. Strict Non-Interference Verification

- **Trading Strategy:** `100% UNCHANGED`
- **Technical Indicators:** `100% UNCHANGED`
- **AI Models & Scoring:** `100% UNCHANGED`
- **Risk Management:** `100% UNCHANGED`
- **Position Sizing:** `100% UNCHANGED`

---

## 4. Operational Sign-Off

> [!NOTE]
> MT5 Terminal process lifecycle is fully protected. The bot remains connected continuously to Vantage Demo account `#25687070` without closing `terminal64.exe`.
