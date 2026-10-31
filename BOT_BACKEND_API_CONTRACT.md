# PKG Traders — Bot-to-Backend Outbound API Contract Specification

**Contract Version**: 1.0.0  
**Transport**: Outbound HTTPS POST  
**Authentication**: HMAC SHA-256 Signature Header Verification  
**Base URL**: `http://localhost:4000` (Dev) / `https://api.pkgtraders.com` (Prod)  

---

## 1. Authentication & Security Headers

Every request sent from the Trading Bot PC to the Central Backend must include the following headers:

| Header Name | Data Type | Required | Description / Example |
| :--- | :--- | :--- | :--- |
| `Content-Type` | String | Yes | Must be `application/json` |
| `X-Bot-Api-Key` | String | Yes | Unique bot identifier key (`pkg_bot_live_api_key_v1`) |
| `X-Bot-Timestamp` | String | Yes | UNIX epoch timestamp in seconds (`1790589600`) |
| `X-Bot-Signature` | String | Yes | HMAC-SHA256 signature calculated over `${timestamp}.${raw_json_body}` |

### HMAC Signature Generation (Python Reference)
```python
import hmac
import hashlib

def calculate_signature(payload_json: str, timestamp_str: str, secret_key: str) -> str:
    message = f"{timestamp_str}.{payload_json}".encode('utf-8')
    return hmac.new(secret_key.encode('utf-8'), message, hashlib.sha256).hexdigest()
```

---

## 2. API Endpoint Specification

### `POST /api/v1/bot/sync`
Unified snapshot push endpoint combining bot health, active account states, open positions, and recently executed MT5 deals.

#### Request Payload Structure
```json
{
  "instance_name": "TRADING_BOT_PC_01",
  "pc_hostname": "TRADING-DESKTOP",
  "bot_version": "2.0.0",
  "timestamp": "2026-09-28T14:17:30Z",
  "accounts": [
    {
      "account_id": "account_001",
      "mt5_login": 26128885,
      "server": "VantageMarkets-Demo",
      "magic_number": 20250701,
      "balance": 495.37,
      "equity": 483.96,
      "margin": 18.56,
      "free_margin": 465.40,
      "margin_level": 2607.54,
      "open_positions": [
        {
          "position_ticket": 2103686984,
          "symbol": "GBPUSD",
          "direction": "SELL",
          "volume": 0.07,
          "entry_price": 1.32841,
          "current_price": 1.32680,
          "stop_loss": 1.32609,
          "take_profit": 1.32473,
          "unrealized_pnl": -11.41,
          "opened_at": "2026-09-23T18:45:05Z"
        }
      ],
      "recent_trades": [
        {
          "deal_ticket": 1662528771,
          "order_ticket": 2076943879,
          "symbol": "XAUUSD",
          "direction": "BUY",
          "volume": 0.01,
          "entry_price": 4310.53,
          "realized_pnl": 6.22,
          "commission": 0.00,
          "swap": 0.00,
          "executed_at": "2026-09-23T19:51:22Z",
          "comment": "[tp 4310.53]"
        }
      ]
    }
  ]
}
```

#### Field Schema Dictionary

| Field Name | Type | Required | Meaning & Idempotency Rules |
| :--- | :--- | :--- | :--- |
| `instance_name` | String | Yes | Identifies Trading PC instance (`TRADING_BOT_PC_01`). |
| `pc_hostname` | String | Yes | Windows OS hostname. |
| `bot_version` | String | Yes | Current software release version. |
| `timestamp` | String | Yes | ISO 8601 UTC timestamp. |
| `accounts[].account_id` | String | Yes | Internal account identifier matching `AccountConfig.account_id`. |
| `accounts[].mt5_login` | Integer | Yes | Raw MT5 login number (e.g. `26128885`). |
| `accounts[].balance` | Float | Yes | Account balance in account currency. |
| `accounts[].equity` | Float | Yes | Net account equity. |
| `open_positions[].position_ticket` | Integer | Yes | Unique MT5 position ticket ID. |
| `recent_trades[].deal_ticket` | Integer | Yes | Unique MT5 deal ticket ID (**Primary key for idempotency**). |

#### Success Response (`200 OK`)
```json
{
  "status": "SUCCESS",
  "message": "Telemetry snapshot synchronized cleanly."
}
```
