# VORTEXT AI read-only MT5 dashboard integration

This document describes the integration branch's staging path. It does not authorize live order execution, change the MT5 trading strategy, or deploy the public Production website.

## 1. Data flow

1. The existing MT5 process connects to its configured real accounts on the trading PC.
2. `app/vortext_dashboard.py` reads account state, bot-tagged open positions and recent deals from connected sessions. It refuses simulated/dry-run sessions.
3. The publisher sends a JSON snapshot to the Vercel Preview `/api/trades` route over outbound HTTPS. It signs the raw body with HMAC-SHA256 and a timestamp.
4. The Vercel route validates the signature and snapshot, then uses the server-side Supabase secret to call the staging multi-account snapshot RPC. A fresh single-account database can use the base snapshot RPC fallback.
5. A dashboard user signs in through Supabase Auth. For every GET, the API validates the bearer token with `/auth/v1/user`, looks up `vortext_authorized_operators` by the immutable Auth user ID, checks the email and `is_active`, and filters the snapshot to the exact `allowed_accounts` list.
6. The dashboard renders only the authorized accounts, positions and deals. The browser never receives the Supabase secret or bot HMAC secret.

No inbound connection to the trading PC is required. No order submit, modify or close operation is available from the website.

## 2. Supabase staging schema already provisioned

Staging project: `xtyszeuvtfcgognkrwxv` (`VORTEXT AI Staging`).

The remote staging project already has the following tables and functions from the separately applied durable-telemetry migrations:

- `public.vortext_authorized_operators`: `user_id`, `email`, `role`, `allowed_accounts`, `is_active`, timestamps.
- `public.vortext_trade_snapshots`: one row per `bot_id`, with `captured_at`, JSONB `snapshot`, and `updated_at`.
- `public.upsert_vortext_multi_account_snapshot(text,timestamptz,jsonb)`: atomic, timestamp-ordered snapshot write.

Observed staging controls:
- RLS is enabled on both VORTEXT tables.
- Browser roles do not have write access to the snapshot RPC or tables.
- The multi-account RPC is executable by `service_role`; `anon` and `authenticated` cannot execute it.
- The security advisor returned no staging security findings at inspection.
- The operator table had zero rows and the snapshot table had zero rows at inspection.

**Do not apply the old PR #4 `20261031120000_vortext_multi_account_snapshots.sql` migration to this staging database.** It creates a second account-access table and assumes a `created_at` column that the existing staging snapshot table does not contain. The integration branch removes that obsolete migration and uses the already provisioned `vortext_authorized_operators` model. Do not change the Production database as part of this work.

## 3. Grant access to the existing website user

Access is a database-side grant, not a client-side email check. Obtain the exact login email from the Supabase Auth user and the stable `account_id` alias from the private trading PC account registry. Do not use the MT5 password or broker login number as the alias.

In the Supabase SQL editor for **VORTEXT AI Staging**, replace both placeholders and run:

```sql
insert into public.vortext_authorized_operators
  (user_id, email, role, allowed_accounts, is_active)
select
  u.id,
  lower(u.email),
  'SUPER_ADMIN',
  jsonb_build_array('REPLACE_WITH_EXACT_ACCOUNT_ID'),
  true
from auth.users as u
where lower(u.email) = lower('REPLACE_WITH_SUPABASE_LOGIN_EMAIL')
on conflict (user_id) do update
set email = excluded.email,
    role = excluded.role,
    allowed_accounts = excluded.allowed_accounts,
    is_active = true,
    updated_at = pg_catalog.now();
```

Then verify the grant without selecting any password or token fields:

```sql
select user_id, email, role, allowed_accounts, is_active
from public.vortext_authorized_operators
where lower(email) = lower('REPLACE_WITH_SUPABASE_LOGIN_EMAIL');
```

The allowed account list must be a JSON array of exact registry IDs, for example `["mt5-primary"]`. Do not grant a wildcard or use an account alias copied from an example file. Grant each customer only the account(s) they are permitted to view.

## 4. Vercel Preview environment

Vercel project: `vortexbot-ai`, website root: `website`.

Required **Preview-only** variables:

| Variable | Value |
|---|---|
| `SUPABASE_URL` | `https://xtyszeuvtfcgognkrwxv.supabase.co` |
| `SUPABASE_PUBLISHABLE_KEY` | Staging publishable key. |
| `SUPABASE_SECRET_KEY` | Staging secret key; server-side only. |
| `VORTEXT_BOT_HMAC_SECRET` | Random secret at least 32 characters; must match the trading PC. |
| `VORTEXT_BOT_ID` | `vortext-fleet`. |

`VORTEXT_DASHBOARD_ALLOWED_EMAILS` is optional as an additional restriction. If it is configured, the user's email must also be included. It does not replace the mandatory operator row and account mapping.

Never decrypt, paste or send the secret values through chat. Verify presence in Vercel's Preview settings and keep all these variables out of Production until a separate production release review.

## 5. Trading PC environment

Add or verify these values in the local process environment on the Windows trading PC:

```env
VORTEXT_DASHBOARD_SYNC_ENABLED=true
VORTEXT_DASHBOARD_INGEST_URL=https://<verified-preview-deployment>/api/trades
VORTEXT_BOT_ID=vortext-fleet
VORTEXT_PUBLISH_INTERVAL_SECONDS=5.0
VORTEXT_BOT_HMAC_SECRET=<same-random-secret-as-vercel-preview>
```

Use the exact Preview deployment URL returned by Vercel after the branch preview is ready. Do not use `https://vortexbot.ai/api/trades`, `pkgtraders-demo.vercel.app` or another domain unless it has been verified to be the non-production Preview deployment for this branch.

The MT5 username/password, broker server and terminal settings remain in the existing private account registry or local environment. Do not copy `accounts.json`, `.env`, broker login details or passwords into GitHub, Supabase, Vercel or this chat.

## 6. Verification

1. Open the branch's Vercel Preview and verify the login page loads.
2. Confirm the approved Supabase user can sign in. Email magic-link sign-in must not create new users.
3. `GET /api/trades` without a bearer token must return `401`.
4. A valid signed-in user without an active operator row must return `403`.
5. A user mapped to account A must not be able to request account B by changing `?account_id=`; that request must return `403`.
6. A user mapped to account A must receive only A's account snapshot, positions and deals; account B data must not appear in the response.
7. Start the existing bot with the intended real MT5 account connected. The first signed snapshot should be stored and `captured_at` should advance on each publication.
8. Verify fresh data is labelled `FEED FRESH`; stop the publisher and confirm data becomes `FEED STALE` after the freshness window.
9. Confirm no website route can place, modify or close orders.
10. Check Vercel environment scope, Supabase security advisor and the GitHub Preview CI/build result.

## 7. Current blockers

The code path is prepared, but live end-to-end verification is not complete yet:

- The staging operator table is empty; no specific Supabase Auth user is currently granted an account.
- The staging snapshot table is empty; the bot has not published a verified live snapshot.
- The real trading PC and its private MT5 account registry are not accessible from this repository session, so the exact current account alias and local HMAC match cannot be verified here.
- Production environment variables and Production deployment remain untouched.
