Agent: Do not modify this file unless explicitly requested

## Project Context
- This is a lightweight TSA wait-time tracker for US airports
- Data is collected from a public wait-times API every 15 minutes via cron (`scripts/run_scrape.py`) and stored in a local SQLite DB (`tsa.db`).
- Much of how airports are displayed and which data is used is configured in the airport catalog in `data/airports.json`\
- Airports fully supported (19): ATL, BWI, CLT, DCA, DEN, DFW, DTW, EWR, IAH, JFK, LAS, LAX, LGA, MCO, MIA, MSP, PHL, PHX, SEA. Check in `data/airports.json` to be sure
- The Flask app (`app.py`) serves a home page with latest wait times plus mini trend sparklines, and per-terminal detail pages with interactive historical charts (range toggles, hover readouts).
- Analytics handled by PostHog
- Feedback email info@tsa-times.com configured with ImprovMX, forwarding to my personal email
- X/Twitter alerts via `@tsa_times`: after each scrape, `scripts/run_tweet_alerts.py` posts when enrolled airports cross wait thresholds (defaults 45/60/90 min; per-airport overrides in `data/airports.json`). Airports opt in with `tweet_alerts.enabled`; supports dry-run/backtest, 6h per-terminal cooldowns, escalation wording, a rolling weekly link budget, and links only during 6am–10pm airport-local time.
- Tech stack: Python scrapers (mostly `urllib` against public JSON APIs; Playwright + Chromium for ATL's Cloudflare-gated page) writing to a local SQLite DB. Flask + Jinja templates serve the webapp; frontend is vanilla JS with Chart.js for historical charts. Deployed on EC2 behind nginx + certbot; scraper + alert runner run via cron every 15 min. X posts use Tweepy (OAuth 1.0a) with credentials in a local `.env`

## Develepment & Deployment
- Local dev runs with a Python venv; production currently runs on EC2 with nginx + certbot (HTTPS) in front of Flask.
- When testing locally, invoke the venv, do not depend on global/native python installations. When I ask for commands so I can test locally, invoke the venv's python vs global/native installations.
- When asked to inspect airport sites, use the Cursor IDE browser MCP when sites are not accessible via curl / blocked Cloudflare browser challenges etc
- v1 of the app was deployed to an ec2 instance on March 12, 2026
- Info about how this app is deployed is available in `docs/deploy.md`. When asked for assistance with deployment, instance management, and file transfer refer to this document

## git Conventions
- Never push to remote or merge to main without explicit approval
