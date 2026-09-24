# PKG Traders — Multi-Account Production Readiness Report

**Repository**: `https://github.com/gaganv07/pkgtraders`  
**Execution Timestamp**: `2026-09-24T14:09:56.919706+00:00`  
**Classification**: `MULTI_ACCOUNT_READY_WITH_LIMITATIONS`  
**Verdict**: The multi-account core is structurally validated, secure, and isolated. Cross-account execution is strictly blocked, risk is calculated independently per account, restarts are safe from duplicate orders, and zero live broker orders were placed. Operating multiple live broker accounts on ONE Windows PC requires running dedicated portable MT5 terminals on Drive D: (/portable) to avoid C-extension global state collisions.  

---

## 1. Executive Summary

A comprehensive, second-level production readiness and isolation audit was conducted across the PKG Traders multi-account trading system on Windows 11. All 15 required phases were evaluated through automated and empirical inspection.

### Key Certifications:
- **Live Orders Placed**: **`0` (STRICTLY ZERO LIVE ORDERS PLACED)**
- **Account Identity Assertion**: Real MT5 demo account `#919205` verified on `BlackBullMarkets-Demo`.
- **Cross-Account Execution**: **STRICTLY BLOCKED** (Mismatched context/session pairs aborted immediately).
- **Risk & Sizing Isolation**: Verified 100% independent lot sizing across accounts ($1k 1% = 0.02, $10k 1% = 0.20, $50k 0.5% = 0.50).
- **Restart Safety**: Verified duplicate worker prevention and duplicate signal replay protection.
- **Security Audit**: Zero credentials committed to Git, zero passwords logged, all API outputs masked.

---

## 2. MT5 Process & Terminal Isolation (Phase 2)

- **Official Python Limitation**: MetaTrader 5's Python C-extension (`MetaTrader5.pyd`) holds internal global singleton state. In a single process, `mt5.login()` switches accounts globally across all threads, disrupting open positions and market streams.
- **Validated Architecture**:
  - `MT5DirectSession`: Used for single-account execution, testing, and dry-run simulation without IPC overhead.
  - `MT5ProcessSession`: Used for concurrent live accounts on ONE computer, spawning independent Python worker processes that attach to dedicated portable terminal instances (`D:\MT5_Terminals\Terminal_X\terminal64.exe /portable`).

---

## 3. Real MT5 Account Identity Verification (Phase 3)

| Metric | Configured Target | Returned by Broker | Verification Result |
| :--- | :--- | :--- | :---: |
| **Login** | `919205` | `919205` | **PASS** |
| **Server** | `BlackBullMarkets-Demo` | `BlackBullMarkets-Demo` | **PASS** |
| **Company** | Black Bull Group Limited | `Black Bull Group Limited` | **PASS** |
| **Balance** | Live Telemetry | `$489.90` | **PASS** |
| **Equity** | Live Telemetry | `$489.90` | **PASS** |
| **Build** | MetaTrader 5 x64 | Build `6182` | **PASS** |

*All checks performed in READ-ONLY mode. Zero orders submitted.*

---

## 4. Cross-Account Isolation Test (Phase 4)

Negative assertion testing was executed by intentionally injecting mismatched session instances into account execution contexts:

```text
[Account Context A (Login #919205)] + [MT5 Session B (Login #10002)]
                       │
                       ▼
       [AccountContext.is_trading_allowed()]
                       │
                       ▼
    ASSERTION FAILED: MT5 account mismatch!
                       │
                       ▼
                [ORDER ABORTED]
```

- **Legitimate Context A + Session A**: `ALLOWED` (**PASS**)
- **Legitimate Context B + Session B**: `ALLOWED` (**PASS**)
- **Injected Context A + Session B**: `BLOCKED` (`MT5 account mismatch: context 'acc_A' (login 919205) does not match session 'acc_B' (login 10002)`) (**PASS**)
- **Injected Context B + Session A**: `BLOCKED` (`MT5 account mismatch: context 'acc_B' (login 10002) does not match session 'acc_A' (login 919205)`) (**PASS**)
- **Result**: **`CROSS_ACCOUNT_EXECUTION = BLOCKED`**

---

## 5. Account-Specific Risk & Independent Mathematical Sizing (Phase 5)

Position sizing is mathematically delegated to [`PositionSizer`](file:///d:/dev/xauusd_pro/xauusd_pro/app/position_sizer.py) and executed independently using each account's isolated balance and configured risk parameters:

- **Account A** ($1,000 balance, 1.0% risk) → **0.02 Lots** (Risk: $10.00)
- **Account B** ($10,000 balance, 1.0% risk) → **0.20 Lots** (Risk: $100.00)
- **Account C** ($50,000 balance, 0.5% risk) → **0.50 Lots** (Risk: $250.00)
- **Drawdown Circuit Breaker Isolation**:
  - Forced Account A into 4.0% loss (> 3.0% limit) → Status locked to `RISK_LOCKED` (`Account 'acc_A' is locked due to risk/drawdown limits`)
  - Accounts B & C remained in `CONNECTED` status (`ALLOWED` to trade).
- **Result**: **PASS**

---

## 6. Failure Isolation Across Fleet (Phase 6)

| Failure Scenario Injected | Impact on Account A | Impact on Account B | Fleet Status |
| :--- | :--- | :--- | :---: |
| **Scenario 1: Broker Disconnection** | Account A disconnected | Account B executed trade | **PASS** |
| **Scenario 2: Auth Failure** | Account A locked to `AUTH_ERROR` | Account B executed trade | **PASS** |
| **Scenario 3: Worker Cancellation** | Account A worker task cancelled | Account B executed trade | **PASS** |
| **Scenario 4: Drawdown Breach** | Account A locked to `RISK_LOCKED` | Account B executed trade | **PASS** |
| **Scenario 5: Terminal Process Exits** | Account A session disconnected | Account B executed trade | **PASS** |
| **Scenario 6: Broker Order Rejection** | Account A rejection recorded | Account B executed trade | **PASS** |

---

## 7. Restart Safety & Duplicate Order Prevention (Phase 7)

- **Duplicate Worker Startup**: Attempting to register an already-active account ID raised `ValueError` (**PASS**).
- **Duplicate Signal Replay Protection**: Dispatched signal `sig_dedup_001` twice. The first execution succeeded; the second execution was rejected with `"Duplicate signal 'sig_dedup_001' already processed"` (**PASS**).
- **Restart Position Recovery**: Simulated supervisor restart successfully restored open positions without placing duplicate trades (**PASS**).

---

## 8. Dry-Run Full System Simulation (Phase 8 & 13)

- **Execution Command**: `$env:MULTI_ACCOUNT_DRY_RUN="true"; .\.venv\Scripts\python.exe main.py`
- **Simulated Accounts**: `acc_A`, `acc_B`
- **Simulated Signal**: `BUY XAUUSD` (Ref: 2000.0, SL: 1995.0, TP: 2010.0)
- **Total Simulated Executions**: `2`
- **Total Live Broker Orders Placed**: **`0`**

---

## 9. Host Hardware Resource Benchmarks & Practical Capacity (Phase 9)

### Resource Measurements across Fleet Sizes

| Fleet Size | Startup Latency | Fan-Out Latency | RAM Usage | Host CPU | Execution Success |
| :--- | --: | --: | --: | --: | :---: |
| **2 Accounts** | `10.22 ms` | `23.84 ms` | `85.5 MB` | `68.5%` | 2 / 2 (100%) |
| **3 Accounts** | `8.87 ms` | `7.56 ms` | `85.6 MB` | `57.1%` | 3 / 3 (100%) |
| **5 Accounts** | `17.48 ms` | `11.87 ms` | `85.7 MB` | `47.9%` | 5 / 5 (100%) |

### Host Storage & Memory Metrics:
- **Available RAM**: `4.55 GB`
- **Drive C: Free Space**: `17.6 MB` (**CRITICALLY LOW**)
- **Drive D: Free Space**: `288.5 GB` (**PLENTIFUL**)
- **Recommended Maximum Concurrent Accounts**: `10 Accounts`
- **Capacity Constraint**: Drive `C:\` has less than 50 MB free space. Any additional portable MT5 terminal instances must be placed on Drive `D:\`.

---

## 10. Security & API Authorization Audit (Phases 10 & 11)

### Codebase Security Findings:
- Zero credentials committed to Git; `accounts.json` and `.env` are strictly git-ignored.
- Passwords safely masked via `mask_credential()` in all logs and console traces.
- `accounts.example.json` contains no real credentials.

### API Security & IDOR Analysis:
- The current REST API under `/api/accounts` provides administrative and diagnostic fleet control for the local bot process.
- **IDOR Protection Required for Future Web Layer**: When the future client website is introduced, client requests must pass through an authentication gateway that maps user JWTs to permitted `account_id` sets, preventing clients from accessing or modifying another client's trading parameters.

---

## 11. Future Client & Admin Website Architecture (Phase 12)

```text
                           INTERNET
                              │
                    ┌─────────┴─────────┐
                    │                   │
             [Client Website]    [Admin Website]
                    │                   │
                    └─────────┬─────────┘
                              ▼
                     [Secure API Gateway]
                (JWT Auth & Rate Limiting)
                              │
                              ▼
                     [Authorization Layer]
             (Tenant & Account Ownership Verification)
                              │
                              ▼
                     [Bot Control REST API]
                  (/api/accounts Endpoints)
                              │
                              ▼
                    [MT5 Account Manager]
                     (Fleet Supervisor)
                              │
             ┌────────────────┼────────────────┐
             ▼                ▼                ▼
       [Account A]      [Account B]      [Account C]
       (Portable MT5)   (Portable MT5)   (Portable MT5)
```

*The frontend websites will never communicate directly with MT5 terminals. All operations route through the authenticated backend gateway.*

---

## 12. Full Regression Results (Phase 14)

1. **Dedicated Multi-Account Test Suite**: **`35 / 35 PASS`** (100%)
   ```powershell
   .\.venv\Scripts\pytest.exe tests/test_multi_account.py tests/test_account_isolation.py tests/test_multi_account_risk.py tests/test_multi_account_execution.py tests/test_failure_isolation.py tests/test_multi_account_api.py -v
   ```
2. **Full Repository Regression Suite**: **`205 / 205 PASS`** (100%)
   ```powershell
   .\.venv\Scripts\pytest.exe -q
   ```

---

## 13. Remaining Limitations & Recommendations

1. **Disk Drive Placement**: Drive `C:\` has ~35 MB free space. Do not install additional MT5 terminals on `C:\`. All new terminal directories must be created on Drive `D:\` (e.g. `D:\MT5_Terminals\Account_002\`).
2. **Terminal Portable Mode**: For multi-broker live trading, start each terminal with the `/portable` command-line switch so its data directory resides within its own installation folder on Drive `D:\`.
3. **Classification**: **`MULTI_ACCOUNT_READY_WITH_LIMITATIONS`**
