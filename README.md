# TSA Wait Times

Scrape and visualize TSA security wait times for **JFK**, **LGA**, and **EWR** (Port Authority NY/NJ). Data comes from a public API; we store it locally and serve a small webapp.

## Quick start

- **Scraper (every 15 min):** See [docs/cron.md](docs/cron.md). Use the venv: `./venv/bin/python scripts/run_scrape.py`
- **Webapp:** `./venv/bin/pip install -r requirements.txt` then `./venv/bin/python app.py` → http://127.0.0.1:5000
- **API details:** [docs/api-findings.md](docs/api-findings.md)

## Code quality

Install development dependencies after creating the Python virtual environment:

```bash
./venv/bin/pip install -r requirements-dev.txt
npm install
```

Run all linting, formatting checks, dead-code detection, and Python tests:

```bash
npm run check
```

Use `npm run format:python` and `npm run format:js` to format source files. Husky runs Ruff and ESLint/Prettier fixes on staged files before commits. The pre-push hook runs the full `npm run check` suite.
