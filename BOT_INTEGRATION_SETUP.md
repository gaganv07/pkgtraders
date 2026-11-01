# PKG Traders — Trading PC Integration & Setup Guide

**Document Version**: 2.0.0  
**Target Environment**: Windows Trading Bot PC  

---

## 1. Environment Variable Configuration

Create or update `.env` on the Trading PC with the following configuration variables:

```env
# ---------------------------------------------------------
# CENTRAL BACKEND INTEGRATION SECRETS
# ---------------------------------------------------------
BACKEND_API_URL="http://localhost:4000"
BOT_HMAC_SECRET="dev_bot_hmac_secret_64bytes_minimum_key_for_pkgtraders!"
BOT_API_KEY="pkg_bot_live_api_key_v1"
BOT_SYNC_INTERVAL_SECONDS="30"
BOT_INSTANCE_NAME="TRADING_BOT_PC_01"

# ---------------------------------------------------------
# TRADING BOT CONFIGURATION (UNCHANGED)
# ---------------------------------------------------------
MIN_QUALITY_SCORE="65.0"
MT5_PASSWORD_ACCOUNT_001="[MASKED]"
MT5_PASSWORD_ACCOUNT_003="[MASKED]"
```

---

## 2. Code File Change Matrix

### Files Created on Trading PC
- [`scripts/bot_backend_sync.py`](file:///c:/Users/user/Desktop/BOT%204%20ALL%207%20PAIRS%20AD%20level/scripts/bot_backend_sync.py) — Outbound HMAC-SHA256 telemetry worker script.
- [`web/backend/server.py`](file:///c:/Users/user/Desktop/BOT%204%20ALL%207%20PAIRS%20AD%20level/web/backend/server.py) — Central Backend REST API server instance.
- [`tests/test_web_platform_integration.py`](file:///c:/Users/user/Desktop/BOT%204%20ALL%207%20PAIRS%20AD%20level/tests/test_web_platform_integration.py) — Integration test suite.

### Files That Must NOT Be Modified (FROZEN)
- `app/main.py` — Core trading signal & orchestrator loop.
- `app/multi_account/*` — Trading engine, risk context, execution worker.
- `strategies/*` — Dynamic scoring models & strategy rules.
- `v1_freeze/*` — Immutable strategy freeze layer.
- `tests/test_*.py` — Pre-existing 248 trading engine unit tests.

---

## 3. Running & Verifying Telemetry Sync

### 1. Launch Central Backend API (Port 4000)
```powershell
python web/backend/server.py
```

### 2. Run Outbound Telemetry Worker
```powershell
python scripts/bot_backend_sync.py
```

### 3. Verification Log Output
```
2026-09-28 19:47:25 [INFO] [BOT_SYNC] Starting Bot Outbound Sync Worker -> Backend (http://localhost:4000)
2026-09-28 19:47:27 [INFO] [BOT_SYNC] [account_001] MT5 logged in as #26128885
2026-09-28 19:47:30 [INFO] [BOT_SYNC] [account_003] MT5 logged in as #26179878
2026-09-28 19:47:30 [INFO] [BOT_SYNC] Snapshot prepared for 2 accounts: [26128885, 26179878]
2026-09-28 19:47:32 [INFO] [BOT_SYNC] Successfully pushed telemetry snapshot (2 accounts) to backend.
```

---

## 4. Test Verification
To run the automated integration test suite:
```powershell
pytest -q tests/test_web_platform_integration.py
```
*Result: 6 / 6 PASSED*

To run the complete test suite:
```powershell
pytest -q
```
*Result: 254 / 254 PASSED*

---

## 5. HANDOFF TO LAPTOP

To develop the Client Website and Admin Website from your laptop:

1. **Deploy / Connect Central Backend**:
   - Run the Central Backend REST API on your cloud server or accessible laptop host (e.g. `https://api.pkgtraders.com` or `http://localhost:4000`).
   - Set `BACKEND_API_URL` on the Trading PC `.env` to point to the backend URL.
2. **Configure HMAC Secret**:
   - Match `BOT_HMAC_SECRET` on both the Trading PC and Central Backend.
3. **Consume REST Endpoints on Laptop**:
   - **Client Login**: `POST /api/v1/client/auth/login`
   - **Client Dashboard**: `GET /api/v1/client/dashboard` (Header: `Authorization: Bearer <JWT>`)
   - **Client Deposit**: `POST /api/v1/client/deposits`
   - **Client Withdrawal**: `POST /api/v1/client/withdrawals`
   - **Admin Login**: `POST /api/v1/admin/auth/login`
   - **Admin Overview**: `GET /api/v1/admin/overview` (Header: `Authorization: Bearer <ADMIN_JWT>`)
   - **Admin KYC Action**: `POST /api/v1/admin/kyc/action`
   - **Admin Deposits Action**: `POST /api/v1/admin/deposits/action`
   - **Admin Withdrawals Action**: `POST /api/v1/admin/withdrawals/action`
   - **Admin Audit Logs**: `GET /api/v1/admin/audit-logs`
4. **Security Isolation Guarantee**:
   - Laptop web clients NEVER contact MT5 terminals directly.
   - MT5 credentials remain isolated on the Trading PC.
