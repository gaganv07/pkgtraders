# VORTEXT AI Website

This directory is the root of the VORTEXT AI customer-facing website.

## Current behavior

- Responsive VORTEXT AI public pages use the approved logo and current product disclosures.
- Sign-in uses Google OAuth or an email magic link for existing Supabase users only. Email magic-link sign-up is disabled with `shouldCreateUser: false`.
- The dashboard is private and read-only. It cannot submit, modify, or close MT5 orders.
- `/api/auth-config` publishes only the browser-safe Supabase URL and publishable key.
- `/api/trades` accepts bot snapshots only when the request has a valid HMAC-SHA256 signature.
- Dashboard reads require a valid Supabase access token and an active row in `public.vortext_authorized_operators`. The server checks the Auth user ID and email, then returns only account IDs listed in `allowed_accounts`.
- Account selectors and trade rows are restricted to the signed-in operator's own mapped account IDs. An account ID in a query string is not an authorization grant.
- Missing snapshots show an explicit waiting state. Old snapshots are marked stale. No sample or fabricated account values are rendered.

## Vercel project

- Project: `vortexbot-ai`
- Website root: `website`
- Git branch deployments are Preview deployments. Production is not changed by this branch.

## Preview environment variables

Configure these only in the Vercel **Preview** environment for this integration:

| Variable | Purpose |
|---|---|
| `SUPABASE_URL` | Supabase staging project URL. |
| `SUPABASE_PUBLISHABLE_KEY` | Browser-safe key used by Supabase Auth. |
| `SUPABASE_SECRET_KEY` | Server-only secret used by `/api/trades` to read authorization records and snapshots. |
| `VORTEXT_BOT_HMAC_SECRET` | At least 32 random characters; must exactly match the bot's local setting. |
| `VORTEXT_BOT_ID` | `vortext-fleet` for the current publisher. |
| `VORTEXT_DASHBOARD_ALLOWED_EMAILS` | Optional additional email fence. The database operator/account grant is mandatory even when this is unset. |

Never expose `SUPABASE_SECRET_KEY` or `VORTEXT_BOT_HMAC_SECRET` to browser code, Git, logs or screenshots. Never place an MT5 password in Vercel.

## Operator and account authorization

The staging project already contains `public.vortext_authorized_operators`. An account is visible only when the signed-in Supabase Auth user has an active record with:

- `user_id`: the exact `auth.users.id` value for the signed-in account;
- `email`: the same email as the Auth user;
- `is_active = true`;
- `allowed_accounts`: a JSON array of exact MT5 registry `account_id` strings.

The database table is read by the server using the secret key. It is not queried directly by browser JavaScript. Do not use editable user metadata as an authorization source.

Example seeding SQL is documented in `docs/VORTEXT_LIVE_FEED_SETUP.md`. Replace the placeholders only after confirming the Supabase login email and the stable `account_id` in the trading PC's private account registry.

## MT5 publisher

The optional publisher in `app/vortext_dashboard.py` reads connected real MT5 sessions and emits broker-confirmed read-only snapshots over outbound HTTPS. It does not expose the terminal, local database or credentials to the website. The publisher is disabled by default and refuses simulated/dry-run accounts.

For staging, set the publisher's ingest URL to the verified Vercel **Preview deployment** URL for this branch, not `vortexbot.ai` or another production domain. See `docs/VORTEXT_LIVE_FEED_SETUP.md`.

## Operational limitations

- The trading PC must be running with the intended real MT5 account connected for new snapshots to arrive.
- The local account registry's `account_id` must be granted to the correct website user.
- The Supabase staging operator table and trade snapshot table were empty at the last inspection; the first live snapshot has not yet been verified.
- Email magic-link delivery is not customer-grade until a monitored outbound SMTP sender is configured and tested. Google OAuth is the configured sign-in provider.
- Public support, legal identity, jurisdiction, privacy contact, retention and legal review gates remain open. Public customer onboarding must remain closed.

## Git and credential safety

Never commit real `.env` files, `accounts.json`, MT5 passwords, service secrets, broker databases, logs with account details or backups. Keep account credentials on the trading PC. Only the stable non-secret account alias should be used in `allowed_accounts`.
