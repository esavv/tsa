## project context
- This is a lightweight TSA wait-time tracker for Port Authority airports (currently JFK, LGA, EWR).
- Data is collected from a public wait-times API every 15 minutes via cron (`scripts/run_scrape.py`) and stored in a local SQLite DB (`tsa.db`).
- The Flask app (`app.py`) serves a home page with latest wait times plus mini trend sparklines, and terminal detail pages with interactive historical charts (range toggles, hover readouts).
- Local dev typically runs with a Python venv; production currently runs on EC2 with nginx + certbot (HTTPS) in front of Flask.
- Analytics handled by PostHog
- Feedback email info@tsa-times.com configured with ImprovMX, forwarding to my personal email

## deployment history
- a v1 of the app was deployed to an ec2 instance on March 12, 2026

## git conventions
- if asked to build multiple features or fix multiple bugs at once, commit each feature and/or fix separately
- prepend commit messages with "feat: " for features, "fix: " for bugfixes, "doc: " for readme and other docs changes, "chore: " for gitignore changes, file restructures. For major features, use "feat/feature-name: ". if you're not sure if a feature is "major", ask me. if you're not sure what to prepend with, ask me.
- when making frontend changes, don't commit, but do draft the commit command and message. I'll want to test the change first
- when drafting commit commands for me to run, do not concat various commands with `&&` into one long and unreadable command (like `cd` and `git add` and `git commit`). just tell me which dir I should be in, and any other commands should be newline-separated
- never push to remote or merge to main without explicit approval. assume that I will handle this normally
