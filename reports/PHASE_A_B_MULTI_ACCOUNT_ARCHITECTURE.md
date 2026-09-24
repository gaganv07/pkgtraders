# PKGTRADERS — MULTI-ACCOUNT MT5 ARCHITECTURE
## Phase A: Architecture Audit & Phase B: Multi-Account Abstraction Design

**Date**: 2026-09-24  
**Workspace**: `d:\dev\xauusd_pro`  
**Git Branch**: `feature/multi-account-mt5`  
**Target Platform**: MetaTrader 5 (Windows) / Python 3.11  

---

## 1. Executive Summary

This document presents the **Phase A (Audit)** and **Phase B (Design)** for converting the existing single-account PKGTRADERS trading bot into a robust, process-isolated, multi-account MT5 execution architecture on a single Windows machine.

### Critical Guarantees
1. **Zero Strategy Alterations**: Strategy logic, ML layer, trade quality scoring, indicators, and market selection are untouched.
2. **True MT5 Session Isolation**: Rather than assuming `MetaTrader5` can multiplex logins inside a single Python process, we account for the C-extension's single-IPC limitation by providing process-level isolation.
3. **Independent Risk & Lot Sizing**: The same signal is fanned out to all enabled accounts, but each account independently evaluates drawdown limits, max open trades, and calculates its own lot size based on its live balance and equity.
4. **Failure Isolation**: An order rejection, broker timeout, margin failure, or terminal disconnect on Account $N$ will never block, crash, or delay execution on any other account.
5. **100% Backward Compatibility**: If no multi-account configuration is supplied, the system seamlessly initializes a single default account session from `.env`, preserving `python main.py` functionality.

---

## 2. Phase A: Current Architecture Audit

### 2.1 MT5 Connection Architecture & API Capabilities
- **Package**: `MetaTrader5` version 5.0.5735 (MetaQuotes Ltd.).
- **Underlying Mechanism**: The official `MetaTrader5` Python package is a C-extension (`.pyd`) communicating with a local MetaTrader 5 terminal process via Windows IPC (named pipes / shared memory).
- **Core Limitation**: The IPC handle and connection context in `MetaTrader5` are **module-level global C static state**. There is **no object-oriented session handle** exposed by the C-extension (e.g. no `client = mt5.Client()`).
  - Calling `mt5.initialize()` establishes a connection to one terminal.
  - Calling `mt5.login()` switches the active account in that terminal, dropping subscriptions, requiring a 1–5 second server handshake, and disconnecting any active trading loop.
  - Attempting to manage multiple accounts concurrently within a single Python thread or process risks cross-account state pollution, order misrouting, and race conditions.
- **Architectural Requirement**: Simultaneous multi-account trading on a single Windows machine requires:
  1. Separate MT5 terminal instances (or distinct `/data:` portable directories) for each broker account.
  2. Isolated execution contexts: each MT5 terminal connection is maintained either in an isolated process worker (`MT5ProcessSession`) or, in single-account mode, directly in-process (`MT5DirectSession`).

### 2.2 Connection Lifecycle
- **Existing Files**: `app/mt5_connection.py`, `app/mt5_connector.py`, `app/mt5_client.py`.
- **Initialization**: `MT5ConnectionManager.connect_mt5()` validates credentials, checks for running terminal processes via `psutil`, auto-launches terminal if configured, calls `mt5.initialize()`, then calls `mt5.login()`, and waits for the server handshake.
- **Health Checks & Monitoring**: Periodic calls to `mt5.terminal_info()` and `mt5.account_info()` verify connection status and broker permissions (`trade_allowed`, `trade_expert`).
- **Disconnection & Shutdown**: `mt5.market_book_release()` releases DOM subscriptions, followed by `mt5.shutdown()`.

### 2.3 Signal Generation & Order Execution Path
- **Signal Generation**: In `app/trade_engine.py`:
  - `TradeEngine.evaluate(symbol, market_md, selector)` is called on each scan cycle.
  - Evaluates market data, DOM order flow, microstructure, and session filters.
  - Computes `QualityBreakdown` using `TradeQualityEngine` (evaluating both legacy and recalibrated engines).
  - Queries `MLLayer.quality_adjustment()` to adjust score.
  - Evaluates hard filters: ATR, spread, session, news blackout, cooldown, risk approval, and position limits.
  - Output: Decision (`ACCEPTED` or `REJECTED`), direction (`LONG` or `SHORT`), entry price, SL, TP1, TP2, TP3.
- **Current Execution Coupling (Single-Account)**:
  - If `ACCEPTED`, `TradeEngine._open()` immediately fetches live balance from `self._client.get_account()`.
  - Calculates lot size using `PositionSizer.size()` with the global account's balance.
  - Sends order directly to `self._client.buy()` / `self._client.sell()`.
  - Records trade in `self._db.insert_trade()` and calls `self._risk.on_open()`.
- **Refactoring Target**: Decouple signal generation from execution. `evaluate()` will emit a `NormalizedSignal`, which is passed to `MultiAccountExecutionManager`.

### 2.4 Risk Path & Position Sizing
- **Existing Files**: `app/risk_manager.py`, `app/position_sizer.py`.
- **Drawdown State**: Tracked in `DrawdownState` (`account_start`, `daily_start`, `weekly_start`, `peak_equity`, `current_equity`, `daily_dd_pct`, `weekly_dd_pct`, `account_dd_pct`).
- **Position Sizing Formula**:
  $$\text{Lot Size} = \left\lfloor \frac{\text{Balance} \times \text{RiskPct}}{\text{SL Points} \times \text{TickValue}} \right\rfloor_{\text{vol\_step}}$$
  Enforces broker constraints: `vol_min`, `vol_max`, `vol_step`.
- **Current Limitation**: `RiskManager` currently reads from global `settings.risk`. In the multi-account architecture, each account must maintain its own independent `AccountRiskManager` instance initialized with its own balance and risk thresholds.

### 2.5 Database Schema & Trade Ledger
- **Existing File**: `app/database.py` (SQLite WAL mode).
- **Current `trades` Table**:
  `id`, `ticket`, `symbol`, `direction`, `status`, `entry_price`, `entry_time`, `close_price`, `close_time`, `close_reason`, `volume`, `initial_vol`, `risk_usd`, `quality_score`, `atr_entry`, `sl`, `tp1`, `tp2`, `tp3`, `realized_pnl`, `spread_entry`, `latency_ms`, `slippage`, `tp1_done`, `tp2_done`, `breakeven_done`, `trailing_active`, `created_at`, `updated_at`.
- **Missing Attribution Fields**:
  Does not store `account_id`, MT5 `login`, `magic_number`, `signal_id`, `requested_vol`, `executed_vol`, `requested_price`, `rejection_reason`, or `strategy_version`.
- **Migration Plan**: Non-destructive `ALTER TABLE` / automatic column migration to preserve existing records while storing full account attribution for all new trades.

### 2.6 Configuration System
- **Existing Files**: `app/config.py`, `.env`.
- **Mechanism**: Loads `.env` via `python-dotenv` into typed dataclasses (`MT5Config`, `RiskConfig`, `SystemConfig`, `Settings`).
- **Single-Account Variables**: `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_PATH`, `MAGIC_NUMBER`, `RISK_PER_TRADE_PCT`, etc.

### 2.7 Dashboard Dependencies
- **Existing Files**: `dashboard/app.py`, `dashboard/control_center.py`.
- **Dependencies**: Injects `_state` dictionary from `Orchestrator`, reads `_db.get_trades()`, `_health.latest`.
- **Multi-Account Compatibility**: Maintain all existing dictionary keys (`account`, `trade`, `risk`, `health`) mapped to primary/aggregate data, while adding `accounts` for granular multi-account operator inspection.

---

## 3. Phase B: Multi-Account Architecture Design

```
                               ┌─────────────────────────────────────────────────────────────┐
                               │                    ORCHESTRATOR / BOT                      │
                               │                                                             │
                               │  ┌────────────────────┐       ┌───────────────────────────┐ │
                               │  │   Market Data &    │       │   Existing Trading        │ │
                               │  │   MarketSelector   │──────>│   Strategy Engine         │ │
                               │  └────────────────────┘       └─────────────┬─────────────┘ │
                               │                                             │               │
                               │                                     NormalizedSignal        │
                               │                                             │               │
                               │                                             v               │
                               │                          ┌────────────────────────────────┐ │
                               │                          │ MultiAccountExecutionManager   │ │
                               │                          └────────────────┬───────────────┘ │
                               └───────────────────────────────────────────┼─────────────────┘
                                                                           │
                                               Fan-out signal concurrently │ (asyncio / isolated tasks)
                        ┌──────────────────────────────────────────────────┼──────────────────────────────────────────────────┐
                        │                                                  │                                                  │
                        v                                                  v                                                  v
        ┌───────────────────────────────┐                  ┌───────────────────────────────┐                  ┌───────────────────────────────┐
        │      AccountSession 001       │                  │      AccountSession 002       │                  │      AccountSession 003       │
        │  ┌─────────────────────────┐  │                  │  ┌─────────────────────────┐  │                  │  ┌─────────────────────────┐  │
        │  │ AccountConfig (Acct 1)  │  │                  │  │ AccountConfig (Acct 2)  │  │                  │  │ AccountConfig (Acct 3)  │  │
        │  ├─────────────────────────┤  │                  ├  ├─────────────────────────┤  │                  ├  ├─────────────────────────┤  │
        │  │ AccountRiskManager (1)  │  │                  │  │ AccountRiskManager (2)  │  │                  │  │ AccountRiskManager (3)  │  │
        │  │ • Independent Balance   │  │                  │  │ • Independent Balance   │  │                  │  │ • Independent Balance   │  │
        │  │ • Independent Drawdown  │  │                  │  │ • Independent Drawdown  │  │                  │  │ • Independent Drawdown  │  │
        │  │ • Independent Sizing    │  │                  │  │ • Independent Sizing    │  │                  │  │ • Independent Sizing    │  │
        │  ├─────────────────────────┤  │                  ├  ├─────────────────────────┤  │                  ├  ├─────────────────────────┤  │
        │  │ MT5 Session (Worker 1)  │  │                  │  │ MT5 Session (Worker 2)  │  │                  │  │ MT5 Session (Worker 3)  │  │
        │  │ Magic: 20250701         │  │                  │  │ Magic: 20250702         │  │                  │  │ Magic: 20250703         │  │
        │  └────────────┬────────────┘  │                  │  └────────────┬────────────┘  │                  │  └────────────┬────────────┘  │
        └───────────────┼───────────────┘                  └───────────────┼───────────────┘                  └───────────────┼───────────────┘
                        │                                                  │                                                  │
                        v (IPC)                                            v (IPC)                                            v (IPC)
        ┌───────────────────────────────┐                  ┌───────────────────────────────┐                  ┌───────────────────────────────┐
        │  MT5 Terminal 1 (Account A)   │                  │  MT5 Terminal 2 (Account B)   │                  │  MT5 Terminal 3 (Account C)   │
        └───────────────────────────────┘                  └───────────────────────────────┘                  └───────────────────────────────┘
```

### 3.1 AccountConfig
Immutable, typed configuration representation for each account:
```python
@dataclass
class AccountConfig:
    account_id: str                          # Unique identifier (e.g. "acct_vantage_01")
    enabled: bool = True                     # Master enable/disable switch
    login: int = 0                           # MT5 Login Number
    server: str = ""                         # MT5 Server Name
    password: str = ""                       # Resolved password (never serialized/logged)
    password_env_var: str = ""               # Env var name for credential isolation
    terminal_path: str = ""                  # Path to terminal64.exe
    data_directory: str = ""                 # Optional isolated data folder
    magic_number: int = 20250701             # Unique magic number per account
    symbols: List[str] = field(default_factory=list)  # Permitted symbols (empty = all)
    risk_per_trade_pct: float = 1.0          # Account-specific risk %
    daily_drawdown_limit_pct: float = 3.0    # Account-specific daily DD %
    weekly_drawdown_limit_pct: float = 6.0   # Account-specific weekly DD %
    account_drawdown_limit_pct: float = 10.0 # Account-specific max DD %
    max_open_trades: int = 3                 # Account-specific max open positions
    max_risk_exposure_pct: float = 3.0       # Account-specific max risk exposure %
```

### 3.2 AccountRegistry
Central repository for discovering, validating, and managing accounts:
- **Validation**:
  - Ensures all `account_id`s are unique.
  - Ensures all `magic_number`s are unique across all accounts (preventing cross-account trade hijacking).
  - Verifies presence of credentials (either directly or through `password_env_var`).
  - Verifies `terminal_path` exists on disk.
- **Backward Compatibility**:
  - If `accounts.json` is not found, `AccountRegistry.load_default()` generates a default `AccountConfig` from `.env` (`MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`, `MT5_PATH`, `MAGIC_NUMBER`, `RISK_PER_TRADE_PCT`, etc.).
  - Legacy workflows (`python main.py`) work immediately with zero configuration changes.

### 3.3 AccountSession & MT5 Session Isolation
An `AccountSession` encapsulates the complete lifecycle, risk state, and MT5 connection for a single account:
- **Components**:
  - `config: AccountConfig`
  - `risk_manager: RiskManager` (isolated drawdown state, open trade counts, cooldowns)
  - `connection: IMT5Session` (isolated MT5 communication interface)
  - `status: SessionStatus` (`CONNECTING`, `CONNECTED`, `DEGRADED`, `DISCONNECTED`, `AUTH_ERROR`, `STOPPED`)
  - `last_error: str`
  - `active_positions: Dict[int, PositionSnapshot]`
- **Session Implementation Architecture**:
  1. `MT5DirectSession`: In-process MT5 connector (used in single-account mode or simulation mode).
  2. `MT5ProcessSession`: Out-of-process MT5 worker using Python `multiprocessing`. Runs a dedicated child process with its own `MetaTrader5` C-extension instance, connected to its account's specific terminal.
  - Communication occurs over duplex `multiprocessing.Pipe` or `Queue` with timeouts (15s for execution, 5s for queries).
  - If the child process or terminal hangs or crashes, the parent catches the timeout, sets status to `DISCONNECTED` or `DEGRADED`, and the remaining accounts proceed uninterrupted.

### 3.4 MultiAccountExecutionManager
Coordinates fan-out signal execution across all registered, enabled account sessions:
- **Flow**:
  1. Receives `NormalizedSignal` from `TradeEngine`.
  2. Identifies enabled, connected account sessions.
  3. Uses `asyncio.gather(*[session.execute_signal(signal) for session in sessions], return_exceptions=True)`.
  4. For each account:
     - Evaluates account-specific risk guards (drawdown, max trades, circuit breaker).
     - Checks if symbol is permitted for this account.
     - Fetches live account balance from that account's session.
     - Runs `PositionSizer.size()` using that account's live balance, equity, and leverage.
     - Constructs order with that account's unique `magic_number`.
     - Submits order through that account's MT5 session.
     - Logs trade in `trades` table with `account_id`, `login`, `magic`, and `signal_id`.
  5. Aggregates results: returns a structured `MultiAccountExecutionReport`.

---

## 4. Concurrency, Failure Isolation & Safety

### 4.1 Failure Isolation Matrix
| Scenario | Impact on Failing Account | Impact on Other Accounts |
| :--- | :--- | :--- |
| Broker rejects order (Invalid Stops) | Marked `REJECTED`, error logged in DB | **None**. Other accounts execute normally |
| Terminal process crashes / IPC disconnect | Marked `DISCONNECTED`, auto-reconnect triggered | **None**. Other accounts execute normally |
| Account reaches Daily Drawdown limit | Marked `RISK_LOCKED`, order blocked | **None**. Other accounts execute normally |
| Insufficient Margin | Marked `INSUFFICIENT_MARGIN`, logged | **None**. Other accounts execute normally |
| Invalid / Expired Password | Marked `AUTH_ERROR`, disabled until resolved | **None**. Other accounts execute normally |

### 4.2 Credential Protection
- Passwords are never committed to version control.
- `accounts.json` is added to `.gitignore`. An `accounts.example.json` template is provided.
- `AccountConfig.__repr__` and all log formatters sanitize/mask password attributes (`mask_credential()`).
- Credentials can be referenced via environment variable names (`password_env_var: "MT5_PASSWORD_ACCOUNT_2"`).

---

## 5. Implementation Roadmap (Phases C through G)

1. **Phase C — Implementation**:
   - Create `app/accounts/account_config.py` (configuration models and validation).
   - Create `app/accounts/account_registry.py` (registry and multi-account loading).
   - Create `app/accounts/mt5_session.py` (session abstraction, process worker, in-process fallback).
   - Create `app/accounts/account_session.py` (isolated session state, account risk manager).
   - Create `app/accounts/execution_manager.py` (signal coordinator and fan-out executor).
   - Integrate `NormalizedSignal` into `app/trade_engine.py` without modifying strategy calculations.
   - Update `app/database.py` with non-destructive schema migrations for account attribution.
   - Update `app/main.py` to route execution through `MultiAccountExecutionManager`.
2. **Phase D — Targeted Tests & Regression**:
   - Unit tests for `AccountConfig`, `AccountRegistry`, duplicate ID/magic validation.
   - Session isolation and risk isolation tests (verifying Account A state does not bleed into Account B).
   - Fan-out and failure isolation tests (mocking Account 1 success, Account 2 rejection, Account 3 disconnection).
   - Full test suite execution (`pytest`).
3. **Phase E — Single-Account Backward Compatibility Verification**:
   - Run tests ensuring standard `.env` configuration operates seamlessly as a single-account session.
4. **Phase F — MT5 Demo Validation**:
   - End-to-end verification in demo / simulation mode.
5. **Phase G — Final Comprehensive Report**:
   - Generate `reports/PHASE_MULTI_ACCOUNT_IMPLEMENTATION.md`.
