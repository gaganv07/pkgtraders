# PKGTRADERS — Multi-Account Architecture Implementation Report

**Repository**: `https://github.com/gaganv07/pkgtraders`  
**Workspace**: `d:\dev\xauusd_pro\xauusd_pro`  
**Branch**: `feature/multi-account-mt5`  
**Date**: 2026-09-24  
**Author**: Antigravity AI Engineering  

---

## 1. Executive Summary

This report documents the implementation of the **Multi-Account Trading Engine** for PKGTRADERS. The bot was successfully upgraded from a single-account MetaTrader 5 execution model to an enterprise-grade multi-account architecture. A single running bot service can now manage multiple MT5 accounts simultaneously with:

- **Isolated MT5 Sessions**: Dedicated terminal connection, login credentials, and session state per account.
- **Isolated Risk & Position Sizing**: Individual balance, equity, drawdown tracking, risk limits, and broker volume constraints per account.
- **Isolated Execution & Position Management**: Dedicated trade tickets, magic numbers, position tracking, and execution failure handling.
- **Fault-Tolerant Failure Isolation**: One account's network disconnection or order rejection does NOT affect or stop other accounts.
- **Preserved Core Strategy**: Signal generation, indicators, ML scoring, and entry/exit criteria remain 100% untouched.
- **Backward Compatibility**: Fully compatible with single-account `.env` configurations.
- **Safe Development**: Comprehensive `DRY_RUN=true` mode ensuring zero real broker orders were placed.

---

## 2. Target Architecture & Execution Flow

```text
                           PKGTRADERS CORE SERVICE
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            ▼                                                   ▼
     [Market Data Feed]                                 [TradeEngine Strategy]
     (Ticks, Bars, DOM)                                (Quality Gate + ML Veto)
            │                                                   │
            └─────────────────────────┬─────────────────────────┘
                                      ▼
                             [NormalizedSignal]
                                      │
                                      ▼
                        [MT5AccountManager] (Fan-Out)
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            ▼                         ▼                         ▼
      AccountWorker A           AccountWorker B           AccountWorker C
            │                         │                         │
     [Risk Validation]         [Risk Validation]         [Risk Validation]
     (Balance $10,000)         (Balance $2,000)          (Balance $50,000)
            │                         │                         │
   [Position Sizing: 0.20L]   [Position Sizing: 0.04L]  [Position Sizing: 1.00L]
            │                         │                         │
      [MT5 Session A]           [MT5 Session B]           [MT5 Session C]
   (Terminal Instance 1)     (Terminal Instance 2)     (Terminal Instance 3)
            │                         │                         │
            └─────────────────────────┼─────────────────────────┘
                                      ▼
                       [Trade Ledger & Database]
                   (account_id, magic, tickets, logs)
```

---

## 3. Implemented Components

All multi-account components are implemented under `app/multi_account/`:

### 3.1 `app/multi_account/account_registry.py`
- **`AccountConfig`**: Data model representing an MT5 account configuration:
  - `account_id`: Unique identifier (e.g., `acc_primary`, `client_101`).
  - `login`, `password`, `server`, `terminal_path`: Isolated MT5 credentials and executable paths.
  - `magic_number`: Unique integer magic number deterministic per account.
  - `risk_percent`, `max_daily_loss_pct`, `max_open_trades`: Account-specific risk boundaries.
  - `allowed_symbols`: Whitelist or wildcards per account.
  - `enabled`, `dry_run`: Independent operational toggles.
- **`AccountRegistry`**: Central registry that loads accounts from `accounts.json` or seamlessly falls back to `.env` for single-account backward compatibility.
  - Enforces strict uniqueness constraints on `account_id` and `magic_number`.
  - Implements `mask_credential()` to prevent credentials from ever leaking to logs or serialized states.

### 3.2 `app/multi_account/account_context.py`
- **`AccountStatus`**: State machine tracking account lifecycle:
  `[DISABLED, CONNECTING, CONNECTED, TRADING, PAUSED, DISCONNECTED, ERROR, RISK_LOCKED]`.
- **`AccountRiskState`**: Dynamic runtime state tracking starting balance, current balance, equity, daily P/L, peak balance, drawdown percentage, and circuit breaker trip states.
- **`AccountExecutionState`**: Tracks open positions, active orders, today's trade count, and latency metrics.
- **`AccountContext`**: Unified domain container encapsulating an account's configuration, active MT5 session, risk state, execution state, and structured logger.
- **`NormalizedSignal`**: Standardized signal payload carrying symbol, direction, entry estimate, stop loss, take profit targets, quality score, and score breakdown.
- **`TradeExecutionReport`**: Immutable result record reporting fill status, executed ticket, price, volume, commission, slippage, and error codes.

### 3.3 `app/multi_account/mt5_session.py`
- **`IMT5Session`**: Abstract session interface defining contract for MT5 interactions:
  `connect()`, `disconnect()`, `get_account_info()`, `get_positions()`, `send_order()`, `close_position()`, `is_connected()`.
- **`MT5DirectSession`**: In-process direct session supporting simulation/dry-run mode and single-account operations. Generates synthetic fills in dry-run mode without sending real network orders.
- **`MT5ProcessSession`**: Multi-terminal process isolation session. Solves the MetaTrader 5 Python C-extension limitation by spawning a dedicated worker subprocess (`multiprocessing.Process`) per MT5 terminal instance. IPC is conducted via duplex pipes.

### 3.4 `app/multi_account/account_worker.py`
- **`AccountWorker`**: Background worker managing the lifecycle of an individual account:
  - Maintains connection health via regular heartbeats.
  - Implements bounded exponential backoff reconnection `[5s, 15s, 30s, 60s, 120s]` with a maximum retry ceiling.
  - Periodically reconciles positions with the MT5 terminal.
  - Executes orders asynchronously without blocking other workers.
  - Provides structured contextual logging attributing every event to `account_id`, `login`, and `server`.

### 3.5 `app/multi_account/account_manager.py`
- **`MT5AccountManager`**: Top-level coordinator:
  - Manages worker pool and account lifecycle (`connect_all()`, `disconnect_all()`).
  - **Signal Fan-Out**: Takes a `NormalizedSignal` from `TradeEngine` and concurrently distributes it across all enabled, connected, and risk-cleared accounts.
  - **Account-Specific Position Sizing**: Uses `PositionSizer` with each account's isolated balance and risk percentage to compute tailored volume (e.g., $10k account gets 0.20 lots; $2k account gets 0.04 lots).
  - **Global Safety Controls**: Integrates `BOT_ENABLED` and `GLOBAL_EMERGENCY_STOP` switches. If triggered, halts order distribution instantly across all accounts.
  - **Telemetry**: Aggregates fleet-wide metrics (total accounts, connected accounts, total equity, open positions, daily P/L) ready for internal diagnostic endpoints and future web APIs.

---

## 4. Integration with Core Trading Engine

### 4.1 Database Layer (`app/database.py`)
- Executed backward-compatible schema migration via `_migrate_multi_account_schema()`:
  - Added columns to `trades` table: `account_id`, `broker`, `server`, `magic`, `signal_id`, `rejection_reason`.
- Added `insert_account_trade()` to record trade executions with full account attribution.
- Updated `get_trades()` to support optional filtering by `account_id`.

### 4.2 Trade Engine Layer (`app/trade_engine.py`)
- Kept 100% of the indicator calculations, market analysis, Order Flow scoring, Liquidity/Market Structure analysis, News vetoes, and ML scoring untouched.
- Added `set_account_manager()` hook.
- When an `ACCEPTED` decision is reached:
  - Constructs a `NormalizedSignal` with strategy parameters.
  - Dispatches signal to `self._account_mgr.distribute_signal(norm_signal)`.
  - Maintains the legacy single-account `_open()` path as fallback if no account manager is configured.

### 4.3 Orchestration Layer (`app/main.py`)
- Updated `Orchestrator.__init__()` to load `AccountRegistry` and initialize `MT5AccountManager`.
- Injected `self.account_mgr` into `self.trade_engine`.
- Added `await self.account_mgr.connect_all()` to `start()`.
- Added `await self.account_mgr.disconnect_all()` to `shutdown()`.
- Integrated multi-account telemetry into `_state["accounts"]`.

---

## 5. MT5 Terminal Limitations & Multi-Terminal Resolution

### Discovered MetaTrader 5 Limitation
The official `MetaTrader5` Python library (v5.0.5735) links against a Windows C-extension DLL containing static global state. Specifically:
1. `mt5.initialize()` establishes a connection to one terminal process at a time per OS process.
2. Subsequent calls to `mt5.login()` or `mt5.initialize()` in the same process switch or reset the active terminal session globally rather than opening a concurrent session.
3. Therefore, multiple accounts cannot run concurrently in the same OS process if they require different physical terminals or simultaneous logins.

### Architectural Solution
To achieve true multi-account concurrency on a single machine:
1. **Simulation & Dry-Run Mode**: Handled in-process via `MT5DirectSession`.
2. **Multi-Terminal Mode**: Supported via `MT5ProcessSession`. Each account runs in its own dedicated child process (`multiprocessing.Process`), launching its own isolated MT5 terminal instance (`/portable /data:<path>`) with its own login and data directory.
3. IPC commands (`CONNECT`, `DISCONNECT`, `SEND_ORDER`, `GET_POSITIONS`) are serialized over native OS pipes, ensuring zero cross-terminal interference.

---

## 6. Safety, Security & Operational Controls

1. **Global Safety Controls**:
   - `GLOBAL_EMERGENCY_STOP=true`: Blocks all new order placements instantly across all accounts.
   - `BOT_ENABLED=false`: Pauses fleet trading while maintaining session connectivity.
2. **Account Safety Controls**:
   - `enabled: false`: Disables individual accounts without affecting running accounts.
   - `dry_run: true`: Simulates execution locally without placing broker orders. Defaulted for safety.
   - Max open trades and daily drawdown circuit breakers trip per account into `RISK_LOCKED` status.
3. **Credential Protection**:
   - Added `accounts.json` and `*.accounts.json` to `.gitignore`.
   - Provided `accounts.example.json` with environment variable placeholders (`${ACCOUNT_001_PASSWORD}`).
   - All account logging passes through `mask_credential()` to prevent plaintext passwords in logs or reports.

---

## 7. Verification & Deliverables Summary

| Deliverable | Location | Status |
| :--- | :--- | :--- |
| **Account Context** | `app/multi_account/account_context.py` | Complete |
| **Account Registry** | `app/multi_account/account_registry.py` | Complete |
| **MT5 Session** | `app/multi_account/mt5_session.py` | Complete |
| **Account Worker** | `app/multi_account/account_worker.py` | Complete |
| **Account Manager** | `app/multi_account/account_manager.py` | Complete |
| **Fleet REST API** | `app/multi_account/multi_account_api.py` | Complete |
| **Dashboard UI Integration** | `dashboard/templates/control_center.html` | Complete |
| **Multi-Account Unit Tests** | `tests/test_multi_account.py` | 10/10 Passed |
| **Account Isolation Tests** | `tests/test_account_isolation.py` | 4/4 Passed |
| **Multi-Account Risk Tests** | `tests/test_multi_account_risk.py` | 3/3 Passed |
| **Execution Fan-Out Tests** | `tests/test_multi_account_execution.py` | 7/7 Passed |
| **Failure Isolation Tests** | `tests/test_failure_isolation.py` | 3/3 Passed |
| **Fleet API Tests** | `tests/test_multi_account_api.py` | 8/8 Passed |
| **Total Test Suite** | 6 test files | **35/35 Passed (100%)** |
| **Pre-Audit Report** | `reports/MULTI_ACCOUNT_PRE_AUDIT.md` | Complete |
| **Implementation Report** | `reports/MULTI_ACCOUNT_IMPLEMENTATION.md` | Complete |
| **Test Report** | `reports/MULTI_ACCOUNT_TEST_REPORT.md` | Complete |

