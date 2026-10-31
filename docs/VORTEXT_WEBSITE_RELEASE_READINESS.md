# VORTEXT AI website and MT5 dashboard release readiness

Inspection date: 2026-10-31. This integration branch combines the PR #5 website-readiness pages with the existing read-only MT5 snapshot publisher and a per-user, per-account dashboard authorization check.

## Release posture

- This work is on `feat/vortext-authenticated-mt5-dashboard`.
- The changes are intended for Vercel Preview and the isolated Supabase staging project only.
- Production has not been changed, migrated or deployed by this branch.
- PR #3, PR #4 and PR #5 remain separate draft PRs; this branch does not merge them.
- Live end-to-end data verification is still blocked until the correct Supabase Auth user is granted the exact MT5 registry account ID and the trading PC publishes the first signed snapshot.

## Website disclosures retained

- Seven configured instruments are shown: XAUUSD, EURUSD, GBPUSD, USDJPY, NAS100, US30 and BTCUSD. XAGUSD is not included.
- USD 200 is described as starting broker-account capital, not a VORTEXT AI fee. Software/subscription pricing is not published.
- The website dashboard is read-only and cannot submit, modify or close MT5 orders.
- Public onboarding is not open; dashboard access requires an approved signed-in user and a server-side account grant.
- Feed freshness and broker account mode (DEMO / REAL / UNKNOWN) are displayed separately.
- No monitored support inbox is advertised. Privacy and Terms pages remain pre-launch disclosures while legal identity, jurisdiction, privacy contact and retention obligations remain unverified.
- Email magic links do not create new Supabase users. Delivery is not customer-grade until outbound SMTP is configured and tested. Google OAuth is the configured sign-in provider.

## Authenticated account-data controls

The new `website/api/trades.js` GET path:

1. Requires a Supabase bearer access token.
2. Validates that token against Supabase Auth.
3. Looks up `public.vortext_authorized_operators` using the immutable `auth.users.id`.
4. Requires the returned email to match the Auth session, `is_active = true`, and a non-empty JSON array of account IDs.
5. Rejects a requested `account_id` that is not in the user's assigned list.
6. Filters the stored snapshot's `accounts`, `positions` and `deals` to the authorized IDs before returning any data.

The bot POST path validates a timestamped HMAC-SHA256 signature. The browser receives only the Supabase publishable key and verified, account-scoped snapshot data. It never receives the Supabase secret key or HMAC secret. `VORTEXT_DASHBOARD_ALLOWED_EMAILS` remains an optional additional email restriction; it does not replace the database account grant.

## Vercel status

Project: `vortexbot-ai`, website root `website`.

- A Preview environment is configured to use the separate `VORTEXT AI Staging` Supabase project.
- Preview environment metadata contains entries for `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`, `SUPABASE_SECRET_KEY` and `VORTEXT_BOT_HMAC_SECRET`. Secret values were not decrypted or printed, so their correctness and equality with the trading PC secret are not yet verified.
- `VORTEXT_BOT_ID` must be `vortext-fleet` for the current publisher. The API uses the same default.
- Production has `SUPABASE_URL` and `SUPABASE_PUBLISHABLE_KEY`, but the server-only Supabase secret and bot HMAC secret were not present in Production metadata at inspection. Production was not modified.
- The current Preview ingest URL must be the exact Preview deployment for this branch, never the public production domain.

## Supabase staging state

Project: `xtyszeuvtfcgognkrwxv` (`VORTEXT AI Staging`, ap-south-1).

Applied staging migrations recorded by Supabase:
- `20261031164736` — `001_durable_telemetry_and_replay_store`
- `20261031164759` — `002_harden_telemetry_access_and_atomic_ordering`
- `20261031164855` — `003_optimize_operator_profile_rls`

Verified state:
- `public.vortext_authorized_operators` and `public.vortext_trade_snapshots` exist with RLS enabled.
- `service_role` can read/write snapshots and read operator grants.
- `anon` and `authenticated` cannot execute the snapshot-upsert RPC.
- The RPC is restricted to `service_role`.
- Staging security advisor returned no security findings.
- Operator rows: 0.
- Trade snapshot rows: 0.

The integrated code uses this existing `vortext_authorized_operators.allowed_accounts` model. It does not create the duplicate `vortext_user_account_access` mapping table. The old PR #4 multi-account migration was removed from this integration branch because it assumed a `created_at` column absent from this staging table and would replace the working RPC with an incompatible version.

## Production Supabase security findings — not changed here

The Production project `bucziqekzyrttgcoxtas` was inspected read-only:
- Supabase advisors reported 22 legacy public tables with RLS disabled.
- The dedicated `vortext_trade_snapshots` table had RLS enabled with no browser-client policies, and no snapshots were present at inspection.
- Leaked-password protection was disabled.
- The existing VORTEXT snapshot store has not been granted to browser roles.

These findings are a separate Production security workstream. Do not add broad authenticated policies or loosen the snapshot store to make the dashboard work. Do not apply staging migrations to Production as part of this branch.

## Remaining launch gates

1. Verify the actual Supabase Auth email for the owner/operator account.
2. Verify the exact non-secret `account_id` alias in the trading PC's private account registry.
3. Add one active `vortext_authorized_operators` row mapping that Auth user ID to that account ID; instructions are in `docs/VORTEXT_LIVE_FEED_SETUP.md`.
4. Verify Preview `SUPABASE_SECRET_KEY` and `VORTEXT_BOT_HMAC_SECRET` are populated and match the staging project and trading PC. Do not paste secret values into chat or Git.
5. Set Preview `VORTEXT_BOT_ID=vortext-fleet`.
6. Point the trading PC publisher to this branch's exact Vercel Preview deployment and run it with the existing real MT5 session connected.
7. Verify the first signed snapshot is stored, timestamps advance, only the mapped user's account is visible, an unauthorized account ID returns 403, and stale data is labelled stale.
8. Run all Python tests and `node --test tests/test_vortext_trade_feed_api.js`; then perform Preview browser checks.
9. Keep the PR draft until these checks pass. Production remains out of scope until a separately approved release and database security review.

## Automated checks

```powershell
python -m pytest -q tests/test_website_readiness.py tests/test_website_login_providers.py tests/test_vortext_dashboard.py
node --test tests/test_vortext_trade_feed_api.js
```

No live trading, MT5 order execution or Production deployment is authorized by these website changes.
