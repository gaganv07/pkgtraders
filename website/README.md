# VORTEXT AI Website

This directory is the website root for the VORTEXT AI trading-bot demonstration.

## Current implementation

- Responsive VORTEXT AI landing page and scalable SVG brand asset.
- Sign-in page with Google, Apple and email magic-link options wired to Supabase Auth when configured.
- Dashboard page checks the Supabase session before showing the dashboard shell.
- Serverless `/api/auth-config` endpoint publishes only the browser-safe Supabase URL and publishable key; it never returns a service-role key.
- Dashboard trade values remain empty until a verified, server-side, read-only broker data feed is built and connected.
- No trading order submission, modification or closure endpoints are provided by this website.

## Vercel

Project: `pkgtraders-demo`  
Repository: `gaganv07/pkgtraders`  
Development branch: `phase77-website`  
Root directory: `website`

Configure these Vercel environment variables only after the Supabase project is active:

- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`

The publishable key is intended for browser use; never configure a service-role key as this value. Apply variables to Preview first, then Production only after review.

## Supabase Auth provider setup

1. Restore or provision an active Supabase project; the existing PKG Traders project was inactive when this scaffold was prepared.
2. In Supabase Auth, enable Google and Apple only after you have their provider credentials configured. Email OTP/magic-link sign-in also requires valid URL and email settings.
3. Set the production Site URL to the deployed public website URL.
4. Add the exact sign-in callback URL, including `https://<domain>/dashboard.html`, to the allowed redirect URLs. Add localhost only for local development. Restrict production redirects to domains you control.
5. Add the two Vercel environment variables above and redeploy the Preview branch.
6. Test provider sign-in, email link sign-in, session persistence, sign-out, expired sessions and direct navigation to the dashboard before enabling Production.

Until these steps are complete, sign-in controls fail closed and the dashboard displays no trading data. A working sign-in page alone is not server-side authorization for private trade records.

## Required next work for private trades

Implement a secure server-side data bridge from the staging MT5 bot to a backend API. Authenticate the bot-to-backend request, validate and deduplicate trade events, reconcile positions with broker state, and enforce authorization on every data API request. Never expose SQLite, MT5 credentials or raw account data directly to the browser. A missing or stale feed must show a visible warning rather than old values as live.

## Git safety

Never commit real `.env` files, credentials, service-role keys, account databases, logs with account details or backups. Keep secrets in Vercel/Supabase provider settings and use placeholder-only templates in Git.
