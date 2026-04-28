Agent: Do not modify this file unless explicitly requested

## Project Context
- This is a lightweight TSA wait-time tracker for US airports
- Data is collected from a public wait-times API every 15 minutes via cron (`scripts/run_scrape.py`) and stored in a local SQLite DB (`tsa.db`).
- Status as of Apr 27, 2026:
  - Airports fully supported: ATL, CLT, DEN, DFW, EWR, JFK, LAX, LAS, LGA, MCO, MIA, PHX, SEA, 
- Brief summary of tech stack: TODO
- Much of how airports are displayed and which data is used is configured in the airport catalog in `data/airports.json`\
- The Flask app (`app.py`) serves a home page with latest wait times plus mini trend sparklines, and per-terminal detail pages with interactive historical charts (range toggles, hover readouts).
- Analytics handled by PostHog
- Feedback email info@tsa-times.com configured with ImprovMX, forwarding to my personal email

## Develepment & Deployment
- Local dev runs with a Python venv; production currently runs on EC2 with nginx + certbot (HTTPS) in front of Flask. When testing locally, invoke the venv, do not depend on global/native python installations
- When asked to inspect airport sites, use the Cursor IDE browser MCP when sites are not accessible via curl / blocked Cloudflare browser challenges etc
- v1 of the app was deployed to an ec2 instance on March 12, 2026
- Info about how this app is deployed is available in `docs/deploy-ec2.md`. When asked for assistance with deployment, instance management, and file transfer refer to this document

## git Conventions
- If asked to build multiple features or fix multiple bugs at once, commit each feature and/or fix separately
- For bigger multi-step work, split distinct chunks into separate local commits when it makes sense (for example: research/docs in one commit, implementation in another)
- Local commits do not need explicit approval; default to committing locally when the work is ready
- Prepend commit messages with "feat: " for features, "fix: " for bugfixes, "doc: " for readme and other docs changes, "chore: " for gitignore changes, admin tasks, file restructures. For major features, use "feat/feature-name: ". if you're not sure if a feature is "major", ask me. if you're not sure what to prepend with, ask me.
- Never push to remote or merge to main without explicit approval
- If I say I want to commit a change myself but ask you for a draft command, do not concat various commands with `&&` into one long and unreadable command (like `cd` and `git add` and `git commit`). just tell me which dir I should be in, and any other commands should be newline-separated
