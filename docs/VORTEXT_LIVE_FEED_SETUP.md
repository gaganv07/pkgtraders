# VORTEXT AI Live Trade Feed Setup (Multi-Account Fleet & Single-Account)

This integration is strictly read-only. The MT5 bot system publishes signed, authenticated snapshots of broker-confirmed open positions, deal history, and financial metrics across single accounts or the multi-terminal fleet. The website only retrieves this data after server-side verification of the user's Supabase session and configured email allowlist.

Zero order submission, modification, or cancellation capabilities are present in the feed publisher.

---

## 1. Supabase Project Setup & Database Migrations

Apply the database migrations in order through the Supabase SQL Editor or the Supabase CLI:

1. **Fleet & Single-Account Snapshots:**
   - Apply `supabase/migrations/20261028120000_vortext_trade_snapshots.sql`
   - Creates `public.vortext_trade_snapshots` and `public.upsert_vortext_trade_snapshot()`.
   - Enables Row Level Security (RLS) with service-role-only grants.

2. **Per-Account Granular Snapshots & Access Mapping:**
   - Apply `supabase/migrations/20261031120000_vortext_multi_account_snapshots.sql`
   - Creates `public.vortext_account_snapshots`, `public.vortext_user_account_access`, and `public.upsert_vortext_multi_account_snapshot()`.
   - Allows granular per-account querying and user access controls.

---

## 2. Website Environment Variables (Vercel)

Project: `pkgtraders-demo`. Website Root Directory: `website`.

| Variable | Description |
|---|---|
| `SUPABASE_URL` | Dedicated PKG Traders HTTPS URL (e.g. `https://bucziqekzyrttgcoxtas.supabase.co`). |
| `SUPABASE_PUBLISHABLE_KEY` | Public client key used to verify user sessions. |
| `SUPABASE_SECRET_KEY` | Server-only secret key (or service_role key) used by API to read/write snapshots. Never expose to client. |
| `VORTEXT_BOT_HMAC_SECRET` | 32+ character hex or random string shared with the trading bot. |
| `VORTEXT_BOT_ID` | Identifier for the trading fleet (e.g. `vortext-fleet` or `vortext-main`). |
| `VORTEXT_DASHBOARD_ALLOWED_EMAILS` | Comma-separated list of authorized email addresses. |

Generate a shared secret on the bot machine:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```
Place the identical secret in Vercel and the bot's `.env`. Never commit secrets to Git.

---

## 3. Trading Bot Environment Configuration

Add the following settings to the bot machine's `.env` (or set in environment):

```env
# Enable live dashboard sync
VORTEXT_DASHBOARD_SYNC_ENABLED=true

# Secure ingest endpoint hosted on Vercel
VORTEXT_DASHBOARD_INGEST_URL=https://pkgtraders-demo.vercel.app/api/trades

# Bot / Fleet identifier
VORTEXT_BOT_ID=vortext-fleet

# Publish interval in seconds (3.0 to 60.0, default: 5.0)
VORTEXT_PUBLISH_INTERVAL_SECONDS=5.0

# 32+ character shared HMAC secret matching Vercel
VORTEXT_BOT_HMAC_SECRET=<shared-32-char-secret>
```

### Safety & Operational Notes:
- The publisher is **disabled by default**. It will only activate when `VORTEXT_DASHBOARD_SYNC_ENABLED=true`, a valid `https://` ingest URL is specified, `VORTEXT_BOT_HMAC_SECRET` is at least 32 characters, and at least one real (non-simulated) MT5 account is connected.
- If running simulated / dry-run accounts, the publisher **refuses** to publish mock or simulated data to protect production feed integrity.
- Each snapshot is digitally signed using HMAC-SHA256 (`X-Vortext-Signature: hmac_sha256(secret, timestamp + "." + body)`).
- Timeouts, clock skew checks (300 seconds), and payload validation protect against replay attacks and stale telemetry.

---

## 4. Multi-Account Fleet Payload Structure

In multi-account fleet mode, the publisher aggregates telemetry across all enabled accounts in `MT5AccountManager`:

```json
{
  "bot_id": "vortext-fleet",
  "captured_at": "2026-10-31T12:00:00Z",
  "account": {
    "server": "Fleet (2 accounts)",
    "currency": "USD",
    "balance": 258.86,
    "equity": 258.86,
    "margin": 0.0,
    "free_margin": 258.86,
    "leverage": 100,
    "trade_mode": "DEMO",
    "total_accounts": 2
  },
  "accounts": [
    {
      "account_id": "account_003",
      "login": 26179878,
      "server": "VantageMarkets-Demo",
      "currency": "USD",
      "balance": 258.86,
      "equity": 258.86,
      "margin": 0.0,
      "free_margin": 258.86,
      "leverage": 100,
      "trade_mode": "DEMO",
      "enabled": true,
      "trading_enabled": true,
      "positions_count": 0,
      "deals_count": 0
    }
  ],
  "fleet_summary": {
    "total_accounts": 1,
    "total_balance": 258.86,
    "total_equity": 258.86,
    "total_floating_pnl": 0.0,
    "total_positions": 0,
    "total_recent_deals": 0
  },
  "positions": [],
  "deals": [],
  "bot_status": "running"
}
```

The top-level `account`, `positions`, and `deals` remain fully backward-compatible with single-account dashboards, while the `accounts` and `fleet_summary` objects power multi-account views.

---

## 5. Verification Checklist

1. **Unauthenticated GET:** `GET /api/trades` without Bearer token must return `401 Unauthorized` or safe `503`.
2. **Unauthorized Email:** Authenticated user not in `VORTEXT_DASHBOARD_ALLOWED_EMAILS` must return `403 Forbidden`.
3. **Invalid Signature:** POST with missing or incorrect HMAC must return `401 Unauthorized`.
4. **Clock Skew:** POST with timestamp drifted >300s must return `401 Unauthorized`.
5. **Fresh Telemetry:** Authenticated GET with allowlisted email returns `connected: true, stale: false` and live broker metrics.
6. **No-Trade Guarantee:** Confirm terminal history has zero unauthorized orders placed or modified by the feed engine.
