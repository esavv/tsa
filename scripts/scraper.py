#!/usr/bin/env python3
"""Fetch supported airport security wait times and insert them into SQLite."""
import gzip
import html
import json
import os
import re
import sqlite3
import urllib.request
import zlib
from datetime import datetime, timezone

NYC_API_BASE = "https://avi-prod-mpp-webapp-api.azurewebsites.net/api/v1/SecurityWaitTimesPoints"
NYC_AIRPORTS = {
    "LGA": "https://www.laguardiaairport.com/",
    "JFK": "https://www.jfkairport.com/",
    "EWR": "https://www.newarkairport.com/",
}
LAX_WAIT_TIMES_URL = "https://www.flylax.com/wait-times"
MIA_WAIT_TIMES_PAGE_URL = "https://www.miami-airport.com/tsa-waittimes.asp"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
DEFAULT_DB_PATH = os.path.join(REPO_ROOT, "tsa.db")
SCRAPE_AIRPORTS = ("LGA", "JFK", "EWR", "LAX", "MIA")
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Encoding": "gzip, deflate",
}
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def fetch_bytes(url: str, headers: dict[str, str] | None = None) -> bytes:
    merged_headers = dict(DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)
    req = urllib.request.Request(url, headers=merged_headers)
    with urllib.request.urlopen(req) as resp:
        body = resp.read()
        encoding = (resp.headers.get("Content-Encoding") or "").lower()
        if "gzip" in encoding:
            body = gzip.decompress(body)
        elif "deflate" in encoding:
            body = zlib.decompress(body)
        return body


def fetch_text(url: str, headers: dict[str, str] | None = None) -> str:
    return fetch_bytes(url, headers=headers).decode("utf-8", errors="ignore")


def fetch_json_url(url: str, headers: dict[str, str] | None = None):
    return json.loads(fetch_text(url, headers=headers))


def clean_html_text(value: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", value))).strip()


def normalize_terminal(value: str) -> str:
    value = clean_html_text(value)
    return re.sub(r"^Terminal\s+", "", value, flags=re.IGNORECASE)


def normalize_queue_type(value: str) -> str:
    lowered = value.lower()
    if "pre" in lowered:
        return "precheck"
    if "priority" in lowered:
        return "priority"
    return "general"


def parse_wait_minutes(value: str) -> int:
    lowered = value.lower()
    less_than = re.search(r"<\s*(\d+)", lowered)
    if less_than:
        return max(int(less_than.group(1)) - 1, 0)

    range_match = re.search(r"(\d+)\s*[-–]\s*(\d+)", lowered)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        return round((start + end) / 2)

    integer_match = re.search(r"(\d+)", lowered)
    if integer_match:
        return int(integer_match.group(1))

    return 0


def fetch_nyc_airport(airport: str) -> list[dict]:
    url = f"{NYC_API_BASE}/{airport}"
    origin = NYC_AIRPORTS[airport]
    points = fetch_json_url(
        url,
        headers={
            "Referer": origin,
            "Origin": origin,
        },
    )
    rows = []
    for point in points:
        rows.append(
            {
                "airport": airport,
                "terminal": point.get("terminal", ""),
                "queue_type": "general" if point.get("queueType") == "Reg" else "precheck",
                "wait_minutes": int(point.get("timeInMinutes", 0)),
                "source_updated_at": point.get("updateTime") or None,
                "point_id": point.get("pointID"),
            }
        )
    return rows


def fetch_lax_airport() -> list[dict]:
    page = fetch_text(LAX_WAIT_TIMES_URL)
    updated_match = re.search(
        r"Data Last Updated:</div>\s*<div>(.*?)</div>",
        page,
        flags=re.IGNORECASE | re.DOTALL,
    )
    source_updated_at = clean_html_text(updated_match.group(1)) if updated_match else None

    body_match = re.search(r"<tbody[^>]*>(.*?)</tbody>", page, flags=re.IGNORECASE | re.DOTALL)
    if not body_match:
        raise ValueError("Could not find LAX wait-times table body")

    rows = []
    for tr_html in re.findall(r"<tr[^>]*>(.*?)</tr>", body_match.group(1), flags=re.IGNORECASE | re.DOTALL):
        cells = re.findall(r"<td[^>]*>(.*?)</td>", tr_html, flags=re.IGNORECASE | re.DOTALL)
        if len(cells) < 3:
            continue
        terminal = normalize_terminal(cells[0])
        lane = clean_html_text(cells[1])
        wait_text = clean_html_text(cells[2])
        rows.append(
            {
                "airport": "LAX",
                "terminal": terminal,
                "queue_type": normalize_queue_type(lane),
                "wait_minutes": parse_wait_minutes(wait_text),
                "source_updated_at": source_updated_at,
                "point_id": None,
            }
        )
    return rows


def extract_mia_api_details() -> tuple[str, str]:
    page = fetch_text(MIA_WAIT_TIMES_PAGE_URL)
    script_match = re.search(r'src="([^"]*/js/wait-times/main\.[^"]+\.js)"', page)
    if not script_match:
        raise ValueError("Could not find MIA wait-times app bundle")

    script_url = urllib.request.urljoin(MIA_WAIT_TIMES_PAGE_URL, script_match.group(1))
    script = fetch_text(script_url)

    url_match = re.search(r'https://waittime\.api\.aero/waittime/v2/current/MIA', script)
    key_match = re.search(r'x-apikey":"([a-f0-9]+)"', script, flags=re.IGNORECASE)
    if not url_match or not key_match:
        raise ValueError("Could not extract MIA wait-times API details")
    return url_match.group(0), key_match.group(1)


def fetch_mia_airport() -> list[dict]:
    api_url, api_key = extract_mia_api_details()
    payload = fetch_json_url(
        api_url,
        headers={
            "x-apikey": api_key,
            "Referer": "https://www.miami-airport.com/",
            "Origin": "https://www.miami-airport.com",
        },
    )

    rows = []
    for point in payload.get("current", []):
        queue_name = (point.get("queueName") or "").strip()
        if not queue_name or " " not in queue_name:
            continue
        terminal, lane = queue_name.split(" ", 1)
        projected_wait_seconds = point.get("projectedWaitTime")
        if projected_wait_seconds is not None:
            wait_minutes = round(float(projected_wait_seconds) / 60)
        else:
            min_wait = int(point.get("projectedMinWaitMinutes", 0))
            max_wait = int(point.get("projectedMaxWaitMinutes", 0))
            wait_minutes = round((min_wait + max_wait) / 2)

        rows.append(
            {
                "airport": "MIA",
                "terminal": normalize_terminal(terminal),
                "queue_type": normalize_queue_type(lane),
                "wait_minutes": int(wait_minutes),
                "source_updated_at": point.get("time") or None,
                "point_id": None,
            }
        )
    return rows


def fetch_airport(airport: str) -> list[dict]:
    if airport in NYC_AIRPORTS:
        return fetch_nyc_airport(airport)
    if airport == "LAX":
        return fetch_lax_airport()
    if airport == "MIA":
        return fetch_mia_airport()
    raise ValueError(f"Unsupported airport: {airport}")


def store(db_path: str, rows: list[dict], scraped_at_utc: str) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    inserted = 0
    for row in rows:
        try:
            cur.execute(
                """
                INSERT INTO wait_times
                (scraped_at_utc, airport, terminal, queue_type, wait_minutes, source_updated_at, point_id)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scraped_at_utc,
                    row["airport"],
                    row["terminal"],
                    row["queue_type"],
                    row["wait_minutes"],
                    row.get("source_updated_at"),
                    row.get("point_id"),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    conn.close()
    return inserted


def run(db_path: str | None = None) -> None:
    db_path = db_path or os.environ.get("TSA_DB_PATH", DEFAULT_DB_PATH)
    scraped_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    total = 0
    failures: list[str] = []

    for airport in SCRAPE_AIRPORTS:
        try:
            rows = fetch_airport(airport)
            inserted = store(db_path, rows, scraped_at_utc)
            total += inserted
            print(f"{airport}: stored {inserted} rows")
        except Exception as exc:
            failures.append(f"{airport}: {exc}")
            print(f"{airport}: ERROR {exc}")

    if failures and total == 0:
        raise RuntimeError("All airport scrapes failed: " + "; ".join(failures))

    print(f"{scraped_at_utc} stored {total} rows ({db_path})")
    if failures:
        print("Failures: " + "; ".join(failures))


if __name__ == "__main__":
    run()
