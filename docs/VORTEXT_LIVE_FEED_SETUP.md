# VORTEXT AI live trade feed setup

This integration is read-only. The MT5 bot publishes signed snapshots of bot-tagged open positions and recent deal history. The website only retrieves this data after server-side verification of the user's Supabase session and configured email allowlist.

## 1. Restore the dedicated Supabase project

The PKG Traders project (reference bucziqekzyrttgcoxtas) is currently inactive. Restore it before attempting live authentication or trade storage. The restore action was blocked by the Supabase free-project limit. Do not use a different production database just to bypass this limit.

## 2. Apply the database migration

When the project is active, apply the file at supabase/migrations/20261028120000_vortext_trade_snapshots.sql through Supabase SQL Editor or the Supabase CLI. Verify that public.vortext_trade_snapshots exists and RLS is enabled. Anonymous and authenticated client roles have no table access.

## 3. Set the website environment variables in Vercel

Project: pkgtraders-demo. Website root directory: website.

- SUPABASE_URL: the dedicated PKG Traders HTTPS URL.
- SUPABASE_PUBLISHABLE_KEY: its publishable key, used to verify signed-in sessions.
- SUPABASE_SERVICE_ROLE_KEY: server-only key used by the API to read/write snapshots. Never expose it to browser code.
- VORTEXT_BOT_HMAC_SECRET: random secret with at least 32 characters.
- VORTEXT_BOT_ID: vortext-main.
- VORTEXT_DASHBOARD_ALLOWED_EMAILS: comma-separated emails allowed to read the trade feed.

Generate a shared secret on the bot machine with: python -c "import secrets; print(secrets.token_hex(32))". Put the same value in Vercel and the bot machine's .env. Never commit that secret.

After these settings are configured, redeploy the website. Configure email/OAuth providers and allowed redirect URLs in Supabase Auth.

## 4. Configure the bot environment

Add to the bot machine's .env:

VORTEXT_DASHBOARD_SYNC_ENABLED=true
VORTEXT_DASHBOARD_INGEST_URL=https://pkgtraders-demo.vercel.app/api/trades
VORTEXT_BOT_ID=vortext-main
VORTEXT_PUBLISH_INTERVAL_SECONDS=5
VORTEXT_BOT_HMAC_SECRET=<same random secret set in Vercel>

The publisher is disabled unless all required settings exist and the bot is connected to a real MT5 terminal. Restart the running bot after setting the environment values. It filters deal history to the configured MT5 magic number.

## 5. Validate on a demo account

- A request to GET /api/trades without a bearer session must return 401 or a safe configuration 503, never trade data.
- An authenticated but non-allowlisted user must receive 403.
- Verify that the dashboard timestamp advances about every five seconds.
- Open/close a demo trade and confirm broker-reported positions/deals match the dashboard.
- Verify that the dashboard reports stale when updates stop.

No order submission, modification or closure operation was added.
