# Cron setup

Run the scraper every 15 minutes so you build a local history of TSA wait times.

## One-time setup

1. From the repo root, create the DB (idempotent):

   ```bash
   python3 scripts/init_db.py
   ```

2. Test the scraper once:

   ```bash
   python3 scripts/run_scrape.py
   ```

   You should see a line like `2026-03-12T01:00:00Z stored 14 rows (…/tsa.db)` and rows in `tsa.db`.

## Crontab

Use the full path to `python3` and the repo so cron runs correctly:

```bash
crontab -e
```

Add:

```
# TSA wait times: every 15 minutes
*/15 * * * * cd /path/to/tsa && /usr/bin/env python3 scripts/run_scrape.py >> /path/to/tsa/logs/cron.log 2>&1
```

Replace `/path/to/tsa` with your repo path (e.g. `$HOME/Projects/tsa`). Create `logs` if you use it:

```bash
mkdir -p /path/to/tsa/logs
```

Optional: set `TSA_DB_PATH` in crontab if you want the DB elsewhere:

```
*/15 * * * * cd /path/to/tsa && TSA_DB_PATH=/path/to/tsa/tsa.db /usr/bin/env python3 scripts/run_scrape.py >> ...
```

## Querying the data

```bash
sqlite3 tsa.db "SELECT scraped_at_utc, airport, terminal, queue_type, wait_minutes FROM wait_times ORDER BY scraped_at_utc DESC LIMIT 20;"
```
