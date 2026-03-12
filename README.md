# TSA Wait Times

Scrape and visualize TSA security wait times for **JFK**, **LGA**, and **EWR** (Port Authority NY/NJ). Data comes from a public API; we store it locally and serve a small webapp.

## Quick start

- **Scraper (every 15 min):** See [docs/cron.md](docs/cron.md). Use the venv: `./venv/bin/python scripts/run_scrape.py`
- **Webapp:** `./venv/bin/pip install -r requirements.txt` then `./venv/bin/python app.py` → http://127.0.0.1:5000
- **API details:** [docs/api-findings.md](docs/api-findings.md)
