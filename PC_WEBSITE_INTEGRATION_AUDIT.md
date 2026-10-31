# PKG Traders — Trading PC & Website Architecture Audit

**Document Version**: 2.0.0  
**Audit Timestamp**: 2026-09-28  
**Scope**: Architecture audit of the multi-account MT5 trading bot on the Trading PC and secure integration with central backend and dual web portals.

---

## 1. Multi-Account Trading Bot Architecture

### Source Code Inspection Summary
The PKG Traders bot is a production-grade multi-account MetaTrader 5 trading engine designed to manage isolated MT5 terminals on a dedicated Windows Trading PC.

```
TRADING BOT PC (Windows Dedicated Node)
├── app/main.py                              # Central bot loop & orchestrator
├── app/multi_account/
│   ├── account_registry.py                 # Configuration model & validation
│   ├── account_manager.py                  # Multi-account lifecycle manager
│   ├── account_worker.py                   # Isolated worker loop per account
│   ├── account_context.py                  # Account-level state, P&L, risk state
│   ├── mt5_session.py                      # MT5DirectSession & process isolation
│   ├── terminal_supervisor.py              # Pre-trade identity handshake guardrails
│   └── multi_account_api.py                # Internal telemetry & management API
└── accounts.json                           # Local account registry configuration
```

### Core Architecture Findings

| Architecture Element | Implementation in Codebase |
| :--- | :--- |
| **Account Representation** | `AccountConfig` dataclass in `app/multi_account/account_registry.py` |
| **Internal Account ID** | Strongly-typed string identifier (e.g. `account_001`, `account_003`). Never relies solely on email or login. |
| **MT5 Login Numbers** | `login: int` field (e.g. `26128885`, `26179878`). |
| **Broker / Server** | `server: str` (e.g. `VantageMarkets-Demo`) and `company: str`. Checked via fail-closed pre-trade handshake. |
| **Account Isolation** | Dedicated `AccountWorker` instance per account with independent position sizing, risk limits, magic numbers, and state context. |
| **Magic Numbers** | Unique integer per account (`20250701`, `20250703`). Prevents cross-account order collisions on shared terminals. |
| **Trades / Deals Retrieval** | `MT5DirectSession` calls `mt5.history_deals_get()` filtered by magic number and time window. |
| **Open Positions Retrieval** | `MT5DirectSession.get_positions()` queries live positions from MT5 filtered by ticket and magic. |
| **Balance & Equity Retrieval** | `MT5DirectSession.get_account_info()` returns balance, equity, margin, free margin, margin level. |
| **Bot Health Supervision** | `TerminalSupervisor` periodically verifies process responsiveness, connection state, and broker handshake status. |

---

## 2. Security & Boundaries

### 1. Data Isolation Boundaries
- **Trading PC**: Responsible solely for MT5 terminals, signal calculation, order execution, risk management, and outbound telemetry push.
- **Laptop / Web Applications**: Consume read-only presentation data from Central Backend API. Never directly communicate with MT5 terminals.
- **Central Backend**: Enforces server-side authorization. Client A can only view MT5 accounts explicitly mapped in `account_user_mappings`.

### 2. Secret Protection & Git Safety
- `accounts.json` contains local account configurations. Password resolution checks environment variables first (`MT5_PASSWORD_ACCOUNT_001`), falling back to masked strings.
- MT5 passwords and private credentials are **NEVER** transmitted over HTTP/HTTPS, NEVER included in backend telemetry payloads, and NEVER exposed to web clients.

---

## 3. Failure Handling & Resilience Matrix

| Failure Scenario | Bot / Trading PC Behavior | Backend / Web Behavior |
| :--- | :--- | :--- |
| **Trading PC Offline** | Local retry loop buffers telemetry. | Backend sets bot status to `DEGRADED`/`OFFLINE` after 90s without heartbeat. |
| **Internet Interruption** | MT5 orders remain protected by broker-side SL/TP. Sync retries with backoff. | Web displays last synchronized snapshot timestamp. |
| **Backend Offline** | Bot continues trading independently; queues telemetry in memory. | Web shows offline notice; bot reconnects automatically. |
| **Duplicate Telemetry** | Bot sends idempotent deal tickets and transaction IDs. | Database enforces `@unique` constraints on deal tickets (`dealTicket`). |
| **MT5 Terminal Crash** | `TerminalSupervisor` detects process drop and auto-restarts terminal. | Heartbeat status reflects temporary reconnect state. |
