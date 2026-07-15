# Deploy on EC2

Production runs on EC2 (Ubuntu 24.04) behind nginx + certbot (HTTPS). The Flask app is supervised by systemd so it survives SSH disconnect and reboots, and a cron job runs the scraper every 15 minutes.

## SSH into the instance

From the project root (where `aws_ec2.pem` lives):

```bash
ssh -i aws_ec2.pem ubuntu@ec2-54-226-252-200.compute-1.amazonaws.com
ssh -i aws_ec2.pem ubuntu@tsa-times.com
```

If your instance's public DNS or IP changes, update the host in the command above.

## Copy prod database locally

```bash
scp -i aws_ec2.pem ubuntu@ec2-54-226-252-200.compute-1.amazonaws.com:/home/ubuntu/tsa/tsa.db ./tsa.db
scp -i aws_ec2.pem ubuntu@tsa-times.com:/home/ubuntu/tsa/tsa.db ./tsa.db
```

## First-time host setup

1. From the repo root, create the DB (idempotent):

   ```bash
   python3 scripts/init_db.py
   ```

2. Install Playwright's Chromium build (needed for **ATL** scraping):

   ```bash
   ./venv/bin/pip install -r requirements.txt
   ./venv/bin/playwright install chromium
   ```

   On Linux servers you may also need system libraries; see [Playwright system dependencies](https://playwright.dev/docs/intro#system-requirements).

3. Test the scraper once:

   ```bash
   python3 scripts/run_scrape.py
   ```

   You should see a line like `2026-03-12T01:00:00Z stored 14 rows (…/tsa.db)` and rows in `tsa.db`.

   Dry-run one airport (no DB writes), including ATL:

   ```bash
   ./venv/bin/python scripts/scraper.py --preview ATL
   ```

## Webapp (systemd)

So the app keeps running after you disconnect and restarts on reboot.

### 1. Create the systemd unit

On the EC2 instance:

```bash
sudo nano /etc/systemd/system/tsa-webapp.service
```

Paste (adjust paths if your repo is elsewhere):

```ini
[Unit]
Description=TSA Wait Times webapp
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/tsa
Environment=FLASK_HOST=0.0.0.0
Environment=FLASK_DEBUG=false
ExecStart=/home/ubuntu/tsa/venv/bin/python app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Save and exit.

### 2. Enable and start

```bash
sudo systemctl daemon-reload
sudo systemctl enable tsa-webapp
sudo systemctl start tsa-webapp
sudo systemctl status tsa-webapp
```

If status shows `active (running)`, open **http://\<ec2-public-ip\>:5000** in your browser (and ensure the EC2 security group allows inbound port 5000).

### 3. Useful commands

- **Logs:** `journalctl -u tsa-webapp -f`
- **Restart:** `sudo systemctl restart tsa-webapp`
- **Stop:** `sudo systemctl stop tsa-webapp`

## Cron

Use the repo's **venv** so cron uses the same Python as your local runs (and avoids version/type-hint issues).

```bash
crontab -e
```

Add:

```
# TSA wait times: every 15 minutes
*/15 * * * * cd /path/to/tsa && ./venv/bin/python scripts/run_scrape.py >> /path/to/tsa/logs/cron.log 2>&1

# Daily memory snapshot — leak tripwire kept after the May 2026 chromium-OOM incident; see scripts/mem_snapshot.sh.
7 12 * * * /path/to/tsa/scripts/mem_snapshot.sh
```

Replace `/path/to/tsa` with your repo path (e.g. `$HOME/Projects/tsa`). Create `logs` if you use it:

```bash
mkdir -p /path/to/tsa/logs
```

Optional: set `TSA_DB_PATH` in crontab if you want the DB elsewhere:

```
*/15 * * * * cd /path/to/tsa && TSA_DB_PATH=/path/to/tsa/tsa.db ./venv/bin/python scripts/run_scrape.py >> ...
```

## X wait-time alerts

The alert runner defaults to a safe dry run. It evaluates 45-, 60-, and
90-minute thresholds with a six-hour per-terminal cooldown. At most one
production tweet in any rolling seven-day period includes a link; additional
tweets are text-only until the link cooldown expires.

Within the terminal cooldown, crossing 60 minutes changes single-terminal copy
to “even longer,” and crossing 90 minutes changes it to “very long.” Initial
alerts and alerts after the cooldown continue to use “elevated.” Grouped
multi-terminal posts retain the standard heading.

Preview and backtest commands:

```bash
./venv/bin/python scripts/run_tweet_alerts.py --dry-run
./venv/bin/python scripts/run_tweet_alerts.py --dry-run --airport JFK
./venv/bin/python scripts/run_tweet_alerts.py --backtest-days 7
./venv/bin/python scripts/run_tweet_alerts.py --backtest-days 7 --airport JFK
./venv/bin/python scripts/run_tweet_alerts.py --backtest-days 7 --summary
```

Dry runs and backtests evaluate all supported airports. Live posting only
includes airports with `tweet_alerts.enabled` set to `true` in
`data/airports.json`.

Detailed dry-run and backtest output assigns each generated tweet a stable ID.
It also identifies whether each post includes a link. Backtest summaries split
the forecast into link and text-only posts, calculate expected API cost at
$0.200 per link post and $0.015 per text-only post, and break out tweet counts
and costs per airport.
To publish one enrolled airport's generated tweet as an explicit API test:

```bash
./venv/bin/python scripts/run_tweet_alerts.py --post-id 20260714T200000Z-JFK-0123456789ab
```

Use an ID copied from actual command output. This publishes the historical
tweet exactly as shown and requires the same credentials as `--live`. Test
tweets are recorded in `tweet_alerts`, cannot be posted twice by the same ID,
and do not affect production cooldowns. Delete the test post manually from X
after checking it.

Live posting requires these OAuth 1.0a credentials:

```bash
X_CONSUMER_KEY=...
X_CONSUMER_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...
```

Store credentials outside the repository. To run alerts after each successful
scrape, load the credentials from an owner-readable environment file rather
than placing their values directly in crontab, then use:

```cron
*/15 * * * * cd /path/to/tsa && (set -a && . /path/to/x-alerts.env && set +a && ./venv/bin/python scripts/run_scrape.py && ./venv/bin/python scripts/run_tweet_alerts.py --live) >> /path/to/tsa/logs/cron.log 2>&1
```

The `--live` and `--post-id` commands are the only modes that call X or write to
`tweet_alerts`. Each successfully published post is recorded once per included
chart target so subsequent production runs can enforce cooldowns.

## Querying the data

```bash
sqlite3 tsa.db "SELECT scraped_at_utc, airport, terminal, queue_type, wait_minutes FROM wait_times ORDER BY scraped_at_utc DESC LIMIT 20;"
```
