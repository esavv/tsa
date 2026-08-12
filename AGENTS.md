<!-- set-cursor:global:start; generated from ~/Projects/agentsmd/AGENTS.md; do not edit -->
AGENT: DO NOT MODIFY THIS FILE UNLESS EXPLICITLY ASKED

## Erik's coding setup

Devices:
- mac-mini: 2024 Mac Mini, Apple M4, 16GB memory, 256GB storage, macOS Tahoe 26.4
- macbook-air: 2024 Macbook Air, Apple M3, 8GB memory, 256GB storage, macOS Sequoia 15.6.1
- iphone-15: iPhone 15 Pro Max, 256GB storage, iOS 26.5

The mini is my dev server running headless from my home. Accessed remotely primarily from the macbook, sometimes from my phone. All devices connected via Tailscale.

This device is: mac-mini

## Style rules

- Always use ASD-STE100 Simplified Technical English when you talk to me 

## git conventions

- You must commit local changes immediately, early and often, unless told otherwise. No approval needed. But, never push your changes to remote unless given explicit permission
- Prepend commit messages with "feat: " for features, "fix: " for bugfixes, "doc: " for readme and other docs changes, "chore" for admin tasks, etc. For major features, use "feat/feature-name: ", and for fixing security gaps use "fix/security: ". For code quality chores, use "chore/format", "chore/lint", "chore/tsc", "chore/knip" etc as appropriate.
- If asked to build multiple features or fix multiple bugs at once, commit each feature and/or fix separately

## Development conventions

- When drafting commands for me to run, do not concat various commands with `&&` into one long and unreadable command (like `cd` and `git add` and `git commit`) and do not include `cd` commands. Just tell me which dir I should be in, and any other commands should be newline-separated
- No cheating! No @ts-ignore or @ts-expect-error. No eslint-disable or biome-ignore comments. No type assertions (as, !) unless absolutely necessary. No skipping files or tests when running checks. All TypeScript uses strict mode with no any types.

<!-- set-cursor:global:end -->

<!-- set-cursor:agent-warning -->

## Project Context
- This is a lightweight TSA wait-time tracker for US airports
- Data is collected from a public wait-times API every 15 minutes via cron (`scripts/run_scrape.py`) and stored in a local SQLite DB (`tsa.db`).
- Much of how airports are displayed and which data is used is configured in the airport catalog in `data/airports.json`\
- Airports fully supported (18): ATL, BWI, CLT, DCA, DEN, DFW, DTW, EWR, IAH, JFK, LAS, LGA, MCO, MIA, MSP, PHL, PHX, SEA. Check in `data/airports.json` to be sure
- LAX was retired on 12 August 2026: flylax.com removed its wait-times page, so LAX is `no_data` and is no longer scraped. Its history stays in the DB
- The Flask app (`app.py`) serves a home page with latest wait times plus mini trend sparklines, and per-terminal detail pages with interactive historical charts (range toggles, hover readouts).
- Analytics handled by PostHog
- Feedback email info@tsa-times.com configured with ImprovMX, forwarding to my personal email
- X/Twitter alerts via `@tsa_times`: after each scrape, `scripts/run_tweet_alerts.py` posts when enrolled airports cross wait thresholds (defaults 45/60/90 min; per-airport overrides in `data/airports.json`). Airports opt in with `tweet_alerts.enabled`; supports dry-run/backtest, 6h per-terminal cooldowns, escalation wording, a rolling weekly link budget, and links only during 6am–10pm airport-local time.
- Tech stack: Python scrapers (`urllib` against public JSON APIs and server-rendered HTML) writing to a local SQLite DB; no browser runtime. Two sources sit behind Cloudflare: ATL needs the full browser header set (`CHROME_NAV_HEADERS`) and falls back to the proxy if challenged, and SEA always needs residential egress via `SCRAPE_PROXY_URL`. Flask + Jinja templates serve the webapp; frontend is vanilla JS with Chart.js for historical charts. Deployed on EC2 behind nginx + certbot; scraper + alert runner run via cron every 15 min. X posts use Tweepy (OAuth 1.0a) with credentials in a local `.env`

## Develepment & Deployment
- Local dev runs with a Python venv; production currently runs on EC2 with nginx + certbot (HTTPS) in front of Flask.
- When testing locally, invoke the venv, do not depend on global/native python installations. When I ask for commands so I can test locally, invoke the venv's python vs global/native installations.
- When asked to inspect airport sites, use the Cursor IDE browser MCP when sites are not accessible via curl / blocked Cloudflare browser challenges etc
- v1 of the app was deployed to an ec2 instance on March 12, 2026
- Info about how this app is deployed is available in `docs/deploy.md`. When asked for assistance with deployment, instance management, and file transfer refer to this document

## git Conventions
- Never push to remote or merge to main without explicit approval
