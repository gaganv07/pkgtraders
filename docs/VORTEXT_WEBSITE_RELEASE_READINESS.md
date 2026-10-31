# VORTEXT AI website release-readiness gates

This branch is based on `phase78-public-pages`. It improves the website only; it does not enable live trading, publish MT5 snapshots, change broker execution, or make the multi-account dashboard available.

## Customer-facing statements

- The currently configured instrument roster is seven instruments: XAUUSD, EURUSD, GBPUSD, USDJPY, NAS100, US30 and BTCUSD. XAGUSD is not included.
- USD 200 is stated starting broker-account capital, not a VORTEXT AI fee. Software/subscription pricing is not published.
- The website dashboard is read-only. The separate MT5 bot performs execution where separately enabled.
- Access is restricted to approved users. Public onboarding is not open.
- The dashboard distinguishes feed freshness from account mode (DEMO / REAL / UNKNOWN). A fresh feed is not the same as a REAL account.
- No official support inbox is currently advertised. The Instagram contact URL remains intentionally disabled until the exact official profile URL is verified.
- The Privacy and Terms pages remain pre-launch drafts because operator identity, jurisdiction, privacy contact, retention schedule and applicable legal review are incomplete.

## Production Vercel environment gates

The Production environment was inspected on 2026-10-31. These server-side variables are still required by `website/api/trades.js` and were not present in Production at the time of inspection:

- `SUPABASE_SECRET_KEY` (or the legacy `SUPABASE_SERVICE_ROLE_KEY`)
- `VORTEXT_BOT_HMAC_SECRET` (minimum 32 characters; must match the secret configured in the bot publisher)
- `VORTEXT_DASHBOARD_ALLOWED_EMAILS` (comma-separated, explicitly approved email addresses)

`SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY` were present. Never expose the Supabase secret key or bot HMAC secret to browser code, Git, logs or support messages. Do not enable the publisher until these values are configured and verified in the correct environment.

The feed endpoint returns HTTP 503 when the required server configuration is missing. It must return a validated, fresh snapshot before the dashboard is described as operational.

## Email sign-in delivery status

The login page supports Google OAuth and an email magic-link flow for existing users only (`shouldCreateUser: false`). However, the email flow is not a production-ready customer delivery channel until an outbound SMTP sender is configured and tested.

ImprovMX forwarding configured for inbound mail (if DNS is later completed) does not itself provide outbound SMTP. Supabase's built-in default mailer is subject to project/team recipient restrictions and low rate limits; do not treat it as customer-grade email delivery. Until a verified outbound sender is configured, keep the visible warning on the login page and use Google OAuth for approved testers. Never expose SMTP credentials in browser code or Git.

## Supabase security audit — production project

A direct schema/grant and advisor inspection on 2026-10-31 found:

- 22 legacy tables in the exposed `public` schema have RLS disabled and no policies.
- The `anon` and `authenticated` roles have broad table privileges on those legacy tables, including SELECT, INSERT, UPDATE, DELETE and TRUNCATE.
- The affected tables include user/admin, KYC, broker/account, trade/position, deposit/withdrawal, transaction, notification, audit, API-key, performance, capital-event and invoice data.
- The dedicated `public.vortext_trade_snapshots` table has RLS enabled and no client policies. Its access is intended to remain server-side through the secret-key backend.
- `public.vortext_trade_snapshots` contained zero rows at inspection time.
- The Supabase security advisor also reports leaked-password protection disabled.

Do not add generic `auth.uid() = user_id` policies to every table. The legacy schema has mixed relationships and several privileged tables. First map actual runtime consumers and foreign-key ownership paths. For tables not intentionally exposed to browser clients, the preferred target is no `anon`/`authenticated` access, RLS enabled, and narrowly scoped server-side access. Create customer-facing policies only where a documented user-ownership model exists.

No production database grants or RLS policies were changed by this website branch.

## Support, privacy and legal gates

Before public customer onboarding:

1. Verify and publish the official support channel; establish a monitored response process.
2. Confirm the business/operator legal identity and operating jurisdiction.
3. Finalize the privacy contact and data-retention schedule, including Auth, trade snapshots, support requests and diagnostic logs.
4. Have the Terms, Privacy notice, financial-services disclosures and any jurisdiction-specific obligations reviewed by qualified counsel.
5. Do not imply that support email, customer email delivery, subscriptions or payment collection are available until the corresponding services are configured and tested.

## Verification

Run the static website checks:

```powershell
python -m pytest -q tests/test_website_readiness.py
```

Then verify the Vercel preview routes, response headers, login behavior, approved-user denial, stale-feed behavior and the `/api/trades` 503/200 paths. The current feed is not production-ready until the server environment and database security gates above are closed.
