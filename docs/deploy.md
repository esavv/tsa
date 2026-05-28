# Deploy on EC2

Production runs on EC2 (Ubuntu 24.04) behind nginx + certbot (HTTPS). The Flask app is supervised by systemd so it survives SSH disconnect and reboots, and a cron job runs the scraper every 15 minutes.

## SSH into the instance

From the project root (where `aws_ec2.pem` lives):

```bash
ssh -i aws_ec2.pem ubuntu@ec2-98-89-0-90.compute-1.amazonaws.com
```

If your instance's public DNS or IP changes, update the host in the command above.

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

## Querying the data

```bash
sqlite3 tsa.db "SELECT scraped_at_utc, airport, terminal, queue_type, wait_minutes FROM wait_times ORDER BY scraped_at_utc DESC LIMIT 20;"
```
