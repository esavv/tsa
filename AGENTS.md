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

## Style Rules
Follow these style rules in your responses:
- No setup/payoff constructions. Don't use this pattern: concede something, comma, "and," then reveal. No "You were right, and I muddied it", "not quite, and the difference is the whole reason", "Yes, and here's the argument that actually decides it"
- No two-fragment pairs used for the same cadence ("Right shape, correctly deferred")
- No landing sentences and summary beats. No "That's the whole feature", "That's the real lesson", "Two things, and they're the point"
- No significance markers: real, actual, genuinely, exactly, precisely, whole, entire, the one X, that matter, specifically
- No tautologically obvious modifiers that can be left unspoken. No "worth knowing", "in the order I'd recommend"
- Headings summarize content, not the category. No headings that withold. "A tradeoff: cold starts add 200ms", not "The one tradeoff to know about"
- No analogies, metaphors, or figurative language. Ban "shape", "load-bearing", "leans on", "the next rung", "hand over". Describe the thing directly
- No performed honesty or candor. No "to be straight with you", "the honest answer", "what I really want you to see"
- No em dashes. No rule-of-three lists unless there are exactly three things
- Don't compare against a strawman baseline. No "you get X [good] instead of Y [bad thing no one mentioned]"
- No stakes inflation or predictions about the future. No "Do that and you're ahead of where I was for years", "You're building an archive. In two years it'll know things you don't"

## Develepment & Deployment
- Local dev runs with a Python venv; production currently runs on EC2 with nginx + certbot (HTTPS) in front of Flask.
- When testing locally, invoke the venv, do not depend on global/native python installations. When I ask for commands so I can test locally, invoke the venv's python vs global/native installations.
- When asked to inspect airport sites, use the Cursor IDE browser MCP when sites are not accessible via curl / blocked Cloudflare browser challenges etc
- v1 of the app was deployed to an ec2 instance on March 12, 2026
- Info about how this app is deployed is available in `docs/deploy.md`. When asked for assistance with deployment, instance management, and file transfer refer to this document
- When asked to make changes, always commit your changes unless told not to. 

## git Conventions
- If asked to build multiple features or fix multiple bugs at once, commit each feature and/or fix separately
- For bigger multi-step work, split distinct chunks into separate local commits when it makes sense (for example: research/docs in one commit, implementation in another)
- Prepend commit messages with "feat: " for features, "fix: " for bugfixes, "doc: " for readme and other docs changes, "chore: " for gitignore changes, admin tasks, file restructures. For major features, use "feat/feature-name: ". if you're not sure if a feature is "major", ask me. if you're not sure what to prepend with, ask me.
- Never push to remote or merge to main without explicit approval
- If I say I want to commit a change myself but ask you for a draft command, do not concat various commands with `&&` into one long and unreadable command (like `cd` and `git add` and `git commit`). just tell me which dir I should be in, and any other commands should be newline-separated
