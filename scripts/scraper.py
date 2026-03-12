#!/usr/bin/env python3
"""Fetch LGA and JFK security wait times from API and insert into SQLite."""
import os
import sqlite3
import urllib.request
import json
from datetime import datetime, timezone

API_BASE = "https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints"
AIRPORTS = {
    "LGA": "https://www.laguardiaairport.com/",
    "JFK": "https://www.jfkairport.com/",
}
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_DB_PATH = os.path.join(REPO_ROOT, "tsa.db")


def fetch_airport(airport: str) -> list[dict]:
    url = f"{API_BASE}/{airport}"
    origin = AIRPORTS[airport]
    req = urllib.request.Request(
        url,
        headers={
            "Referer": origin,
            "Origin": origin,
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def store(db_path: str, airport: str, points: list[dict], scraped_at_utc: str) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    n = 0
    for p in points:
        terminal = p.get("terminal", "")
        queue_type = "general" if p.get("queueType") == "Reg" else "precheck"
        wait_minutes = int(p.get("timeInMinutes", 0))
        source_updated_at = p.get("updateTime") or None
        point_id = p.get("pointID")
        try:
            cur.execute(
                """
                INSERT INTO wait_times
                (scraped_at_utc, airport, terminal, queue_type, wait_minutes, source_updated_at, point_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (scraped_at_utc, airport, terminal, queue_type, wait_minutes, source_updated_at, point_id),
            )
            n += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return n


def run(db_path: str | None = None) -> None:
    db_path = db_path or os.environ.get("TSA_DB_PATH", DEFAULT_DB_PATH)
    scraped_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = 0
    for airport in AIRPORTS:
        points = fetch_airport(airport)
        n = store(db_path, airport, points, scraped_at_utc)
        total += n
    print(f"{scraped_at_utc} stored {total} rows ({db_path})")


if __name__ == "__main__":
    run()
