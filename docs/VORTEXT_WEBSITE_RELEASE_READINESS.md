# VORTEXT AI website and MT5 dashboard release readiness

Inspection date: 2026-11-01. This integration branch combines the PR #5 website-readiness pages, the existing read-only MT5 snapshot publisher, shared authenticated dashboard access, a Getting Started guide and explicit release-state disclosures.

## Release posture

- Branch: `feat/vortext-authenticated-mt5-dashboard`.
- Review: Draft PR #6; not merged.
- Deployment scope: Vercel Preview and isolated Supabase staging only.
- Production has not been migrated, updated or deployed by this work.
- Product status displayed on the homepage: **LIMITED ACCESS · INTEGRATION TESTING**.
- VORTEXT AI is not generally available. Public customer onboarding remains closed.
- The verified website scope in this branch is read-only monitoring. No public commitment is made for unreleased research or execution modules.

## User-facing readiness changes

- Homepage has an accessible three-line hamburger control at mobile widths, with open/close state, Escape-key close and close-on-navigation.
- Homepage links to `/getting-started.html`.
- Getting Started explains official MT5 desktop installation, broker/account compatibility checks, account connection, demo-only testing, credential handling and release limitations.
- The homepage explicitly marks DOM, order-flow, market-structure, multi-timeframe, risk-management and execution analytics as under validation and not generally available.
- Public pages retain risk, pre-launch, privacy, pricing and access limitations.

## Dashboard status indicators

The dashboard displays three independent status fields:

1. **Feed connection:** `FEED CONNECTED · FRESH`, `FEED STALE`, `FEED UNAVAILABLE` or `AWAITING FIRST UPDATE`.
2. **Account mode:** broker-reported `DEMO`, `REAL`, `CONTEST`, `MIXED` or `UNKNOWN`.
3. **Last successful broker update:** the timestamp of the latest accepted snapshot, displayed in UTC.

Feed freshness is not used as a synonym for a real-money account. The dashboard uses explicit DEMO/REAL labels for account mode. A stale snapshot is visibly marked stale and the timestamp does not advance until a newer accepted broker snapshot is received.

## Shared dashboard access model

The Preview API:

1. Requires a Supabase bearer access token and validates it with Supabase Auth.
2. Uses the server-only Supabase secret for snapshot and operator metadata reads.
3. Exposes only the server-configured IDs in `VORTEXT_DASHBOARD_SHARED_ACCOUNTS` to all valid signed-in users.
4. May add per-user account grants from `vortext_authorized_operators.allowed_accounts`.
5. Blocks an explicitly inactive or mismatched operator record.
6. Filters `accounts`, `positions` and `deals` to the allowed set before returning data. Query-string account IDs do not grant access.
7. Rejects anonymous requests. Website code has no order submit, modify or close operation.

Shared IDs are configured on the Vercel Preview branch only. They do not make the feed publicly readable.

## Vercel Preview state

Project: `vortexbot-ai`, website root: `website`.

- Branch-only `VORTEXT_BOT_ID=vortext-fleet`.
- Branch-only `VORTEXT_DASHBOARD_SHARED_ACCOUNTS=account_003`.
- Preview Supabase URL and publishable key point to the isolated staging project.
- At last environment inspection, Preview `SUPABASE_SECRET_KEY` and `VORTEXT_BOT_HMAC_SECRET` were empty. Both must be provisioned before the API can ingest/read snapshots.
- The local HMAC secret on the Windows trading PC must match the Preview HMAC secret. Never paste either secret into chat, Git or screenshots.
- No Production environment variable was changed by this work.

## MT5 account mapping

- An earlier repository integration log mapped MT5 login `26179878` to internal alias `account_003` on `VantageMarkets-Demo`.
- The private current Windows account registry still requires local confirmation.
- The publisher must run from the owner-controlled Windows trading PC and send a signed snapshot to the exact Preview `/api/trades` URL.
- The numeric MT5 login is not the website allowlist alias.

## Supabase staging state

Project: `xtyszeuvtfcgognkrwxv` (`VORTEXT AI Staging`, ap-south-1).

- Existing staging schema contains `vortext_authorized_operators`, `vortext_trade_snapshots` and the timestamp-ordered snapshot RPC.
- RLS is enabled on the VORTEXT tables; browser roles cannot write snapshots or execute the service-only upsert RPC.
- Operator rows were empty at inspection.
- Auth lookup for `gagangowdabm27@gmail.com` returned no user.
- Trade snapshot rows were empty at inspection.
- Do not apply the incompatible old PR #4 multi-account migration to staging.
- Production Supabase security findings remain a separate workstream and have not been changed here.

## Test results

Latest isolated Vercel sandbox run before the UI additions:
- Node API tests: 11 passed.
- Python website-readiness tests: 8 passed.

The new UI/Getting Started tests must be rerun after the current branch changes. A passing unit/static test suite does not replace the Preview browser smoke test or real MT5 publication test.

## Remaining release gates

1. Configure non-empty Preview `SUPABASE_SECRET_KEY` and `VORTEXT_BOT_HMAC_SECRET`.
2. Verify the private Windows account registry maps login 26179878 to `account_003`.
3. Provision the intended Supabase Auth users using the approved onboarding route; email magic-link login does not create new users.
4. Verify the publisher configuration and endpoint on the Windows trading PC; keep all broker credentials and secrets local/server-side.
5. Publish signed snapshots to Preview and verify timestamps advance, feed freshness transitions correctly, and the dashboard renders the exact broker account mode.
6. Smoke-test desktop and mobile navigation, status indicators, Getting Started links, login and account-filter protections.
7. Keep the PR draft until Preview and end-to-end checks pass. No merge or Production rollout is implied.

No live trading, MT5 order execution or Production deployment is authorized by these website changes.
