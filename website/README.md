# Website — Initial Hosting Scaffold

This directory is the intended Vercel root for the PKG Traders demonstration website.

## Current status

- Static, responsive landing page scaffold: implemented.
- Vercel project: `pkgtraders-demo`, linked to `gaganv07/pkgtraders`.
- Development branch: `phase77-website`.
- Live MT5 feed: **not connected**.
- Google/Apple/email authentication: **not implemented**.
- Open positions and floating P&L: deliberately unavailable until the read-only feed is verified.

## Deploy flow

The Vercel project is configured to build from this directory. Changes pushed to `phase77-website` should create Preview deployments after the Git integration and project root are verified. The production branch remains `main`; do not merge the website to `main` until review and testing are complete.

## Safety

Never put broker passwords, MT5 credentials, account databases, trade logs, OAuth secrets or environment files with real values in this directory or in Git. Public dashboard output must be sanitized and backed by verified read-only data. Do not add trade-execution endpoints to the website.
