# PKGTRADERS — Multi-Account Architecture Pre-Audit Report

**Repository**: `https://github.com/gaganv07/pkgtraders`  
**Workspace**: `d:\dev\xauusd_pro\xauusd_pro`  
**Branch**: `feature/multi-account-mt5`  
**Date**: 2026-09-24  
**Author**: Antigravity AI Engineering  

---

## 1. Executive Summary

This pre-audit examines the existing PKGTRADERS trading bot codebase to evaluate its readiness for conversion from a single-account MetaTrader 5 architecture to a multi-account execution engine running on a single Windows machine.

### Core Audit Conclusion
The existing trading strategy, market data ingestion, and quality-scoring logic are robust, well-tested, and clean. However, the connection, risk management, and order execution layers are currently tightly coupled to a single global MT5 terminal connection and global configuration. 

Converting the system to multi-account requires isolating account state into explicit `AccountContext` objects, implementing a multi-session MT5 connection manager that honors MetaTrader 5's IPC architecture, fanning out strategy signals to independent account risk managers, and extending the trade ledger for account attribution—all without modifying the underlying trading strategy.

---

## 2. Current Architecture Overview

The system is organized into modular Python components:

```text
[Market Feed / MT5 Client] ──> [MarketData & MultiSymbolMarketData]
                                        │
                                        ▼
                              [MarketSelector Engine]
                                        │
                                        ▼
                                [TradeEngine]
                   (Quality Gate + ML Layer + Hard Vetoes)
                                        │
                                        ▼
                          [Single MT5Client & OrderExecutor]
                                        │
                                        ▼
                                [SQLite Database]
```

### Key Components:
- **`app/main.py` (`Orchestrator`)**: Coordinates async loops (`_tick_loop`, `_bar_loop`, `_account_loop`, `_news_loop`, `health_loop`, `dashboard`). Injects a single `MT5Client`, a single `RiskManager`, and a single `TradeEngine`.
- **`app/mt5_connection.py` & `app/mt5_connector.py`**: Manages connection lifecycle to a single local MT5 terminal using `MetaTrader5` Python package.
- **`app/mt5_client.py`**: High-level wrapper handling symbol discovery, tick/bar retrieval, DOM subscription, positions retrieval (`positions_get`), and order execution (`buy`, `sell`, `modify`, `close`).
- **`app/trade_engine.py`**: Evaluates entries (`evaluate()`), sizes positions, sends orders (`_open()`), manages open trades (`_manage()`, `manage_all()`), and updates the database.
- **`app/risk_manager.py`**: Tracks account drawdown against global limits (`settings.risk`), enforces max trades and exposure.
- **`app/position_sizer.py`**: Pure math module calculating lot size from balance, SL points, tick size, tick value, and broker constraints.
- **`app/database.py`**: SQLite database managing `trades`, `execution_log`, `quality_log`, `system_events`, and `daily_stats`.

---

## 3. Current MT5 Connection & Account-State Flow

### 3.1 Connection Flow
1. `MT5ConnectionManager.connect_mt5()` validates environment variables (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_PATH`).
2. Checks whether `terminal64.exe` is running via `psutil`. If not running, launches `subprocess.Popen([self.path])`.
3. Calls `mt5.initialize(path=...)`.
4. Checks `mt5.account_info()`. If not logged in as `MT5_LOGIN`, calls `mt5.login(login, password, server)`.
5. Polls up to 5 times for the server handshake.
6. Asserts `acct_info.login == self.login`. If mismatched, halts execution.

### 3.2 Account-State Flow
- `MT5Client.get_account()` calls `mt5.account_info()`.
- Returns a dictionary with `balance`, `equity`, `margin`, `free_margin`, `margin_level`, `leverage`.
- In `Orchestrator.start()`, `self.risk.initialize(account["balance"])` initializes the single global `RiskManager`.
- In `Orchestrator._account_loop()`, calls `self.risk.update_equity(acct["balance"], acct["equity"])`.
- Global mutable assumption: only one account balance, one equity value, and one drawdown state exist in memory.

---

## 4. Current Trade Execution Flow

1. In `app/main.py`:
   - Every tick, `MarketSelector` selects the highest-scoring symbol.
   - Calls `TradeEngine.evaluate(symbol, md)`.
2. In `app/trade_engine.py`:
   - Computes `QualityBreakdown` across indicators, order flow, microstructure, and session.
   - Adjusts score via `MLLayer`.
   - Validates filters: ATR, spread, session, news blackout, cooldown, risk gate (`approve_with_exposure`), and position limit (`open_trade_count() < max_open_trades`).
   - If decision is `ACCEPTED`:
     - Calls `self._open(symbol, active_qb, tick, atr, md)`.
     - Inside `_open()`:
       - Calls `self._client.get_account()` to read `live_balance`.
       - Calls `self._client.get_symbol_spec(symbol)` to get contract specifications.
       - Runs `PositionSizer.size(balance=live_balance, risk_pct=self._cfg.risk_per_trade_pct, ...)`.
       - Submits order via `self._client.buy()` or `self._client.sell()`.
       - Calls `self._risk.on_open()`.
       - Writes trade to `self._db.insert_trade()`.

---

## 5. Single-Account Assumptions in Current Code

The audit revealed the following single-account assumptions:

| Location | Single-Account Assumption | Required Refactoring |
| :--- | :--- | :--- |
| `app/config.py` (`MT5Config`, `RiskConfig`) | Assumes one `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MAGIC_NUMBER`, `RISK_PER_TRADE_PCT`. | Create `AccountConfig` and `AccountRegistry` supporting multi-account definitions. |
| `app/mt5_connection.py` | Global `MT5ConnectionManager` singleton with one login and one terminal path. | Scope connection management to individual account instances via `MT5AccountManager`. |
| `app/mt5_client.py` | One `MT5Client` instance holding single `_connected` status, single `_dom_active`, and single magic number. | Decouple market data feed from account execution; introduce isolated `IMT5Session`. |
| `app/trade_engine.py` | `evaluate()` directly triggers `_open()`, sizing lots for one balance and sending to one `MT5Client`. | Decouple signal generation (`NormalizedSignal`) from execution (`MultiAccountExecutionManager`). |
| `app/risk_manager.py` | Single `RiskManager` instance tracking one account's drawdown, loss streak, and cooldown. | Provide independent `AccountRiskManager` inside each `AccountContext`. |
| `app/database.py` | `trades` table has no `account_id`, `magic`, `login`, or `signal_id` columns. | Add non-destructive schema migration for multi-account trade ledger attribution. |
| `app/main.py` (`Orchestrator`) | Connects one `MT5Client`, starts one `_account_loop`, initializes one `risk` object. | Orchestrator delegates account lifecycle and execution to `MT5AccountManager`. |

---

## 6. MT5 Architectural Limitations on Windows

### 6.1 The MetaTrader 5 Python C-Extension Architecture
- The official Python package (`MetaTrader5` v5.0.5735) communicates via Windows IPC to a local terminal process.
- The IPC handle and session state within `MetaTrader5` are **module-level global C static state**.
- There is **no object-oriented session handle** exposed by the C-extension (e.g. `client = mt5.Client()`).
- In a single Python process:
  - Calling `mt5.initialize(path=...)` connects to one terminal instance.
  - Calling `mt5.login()` switches accounts inside that terminal, dropping existing market subscriptions, requiring 1–5 seconds for the server handshake, and disconnecting any active trading loop.
  - Attempting to call `mt5.initialize()` for a second terminal closes the IPC connection to the first terminal.

### 6.2 Architectural Requirement for True Multi-Account Operation
To safely operate multiple MT5 accounts simultaneously on a single Windows computer:
1. **Single-Terminal Mode (Serial / Fallback / In-Process)**:
   - For single-account legacy setups or testing, an in-process direct session (`MT5DirectSession`) is used.
2. **Multi-Terminal Instance Mode (Concurrent / Process-Isolated)**:
   - For simultaneous multi-account trading, each MT5 account connects to its own MT5 terminal instance (or separate portable `/data:` instance).
   - Each account session is managed in an isolated worker process (`MT5ProcessSession`) communicating with the main service via IPC pipes/queues.
   - If one terminal crashes, freezes, or disconnects, the parent process detects the event via process monitoring and timeout, marking that specific account as `DISCONNECTED` while all other account workers continue trading seamlessly.

---

## 7. Concurrency & Concurrency Problems

1. **Race Conditions on Account State**:
   - Resolved by encapsulating all account state inside dedicated, account-scoped `AccountContext` instances with synchronization locks.
2. **Slow Broker Blocking Other Accounts**:
   - An order to Broker B taking 800ms must not delay Broker A.
   - Resolved by concurrent fan-out using `asyncio.gather(*[session.execute_signal(...) for session in active_sessions], return_exceptions=True)`.
3. **Cascading Failures**:
   - An unhandled exception during order execution on Account B is caught and isolated to Account B's status, preventing process crashes.

---

## 8. Risks of Modifying Execution Engine & Mitigation

| Risk | Mitigation |
| :--- | :--- |
| Strategy regression or accidental alteration | Strategy calculations, indicators, and ML scoring remain 100% untouched. Signal output is normalized into an immutable `NormalizedSignal` dataclass. |
| Inadvertent real-order execution during testing | Implement `DRY_RUN=true` mode by default for testing. In dry run, orders are simulated, validated, and logged, but never sent to the broker. |
| Single-account breakage | `AccountRegistry` defaults to `.env` configuration if no multi-account file is provided, preserving legacy `python main.py` execution. |
| Credential leakage | Passwords are never committed, logged, or printed. Credentials support environment variable indirection (`password_env_var`). |

---

## 9. Baseline Test Suite Results

Prior to any code modification, the test suite was executed:
- **Environment**: Python 3.11.9, pytest 9.1.1 on Windows.
- **Result**: 161 tests passed out of 170.
- **Failures Analysis**:
  - The 9 failing tests in `test_all.py` and `test_institutional_platform.py` were caused by existing local test artifacts:
    - Pre-existing `database/ml_model.json` on disk (125 historical trades present) caused tests expecting an uninitialized ML model to fail.
    - Local `.env` file settings (`MAX_OPEN_TRADES=5`, `USE_RECALIBRATED_SCORING=true`) altered default threshold assumptions in older unit tests.
  - When run against isolated defaults, the core tests pass.
- All new multi-account code will have dedicated isolated tests that run without interference from workspace state.
