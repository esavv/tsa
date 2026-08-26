#!/usr/bin/env python3
"""Check production scraper health without invoking an agent."""

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AIRPORTS_PATH = REPO_ROOT / "data" / "airports.json"
REPO_EC2_KEY = REPO_ROOT / "aws_ec2.pem"
PRIMARY_EC2_KEY = Path.home() / "Projects" / "tsa" / "aws_ec2.pem"
DEFAULT_EC2_KEY = REPO_EC2_KEY if REPO_EC2_KEY.exists() else PRIMARY_EC2_KEY
DEFAULT_SSH_TARGET = "ubuntu@tsa-times.com"
DEFAULT_REMOTE_DB = "/home/ubuntu/tsa/tsa.db"
DEFAULT_THRESHOLD_HOURS = 24
DEFAULT_CRON_STALE_MINUTES = 45
INCIDENT_EXIT = 2

HEALTH_SQL = """
WITH stats AS (
    SELECT
        airport,
        MAX(scraped_at_utc) AS last_attempt_at,
        MAX(CASE WHEN ok = 1 THEN scraped_at_utc END) AS last_success_at
    FROM scrape_airport_stats
    GROUP BY airport
),
latest AS (
    SELECT s.airport, s.ok AS latest_ok, s.error AS latest_error
    FROM scrape_airport_stats AS s
    JOIN stats
      ON stats.airport = s.airport
     AND stats.last_attempt_at = s.scraped_at_utc
),
data AS (
    SELECT airport, MAX(scraped_at_utc) AS last_data_at
    FROM wait_times
    GROUP BY airport
)
SELECT
    stats.airport,
    stats.last_attempt_at,
    stats.last_success_at,
    data.last_data_at,
    latest.latest_ok,
    latest.latest_error
FROM stats
JOIN latest ON latest.airport = stats.airport
LEFT JOIN data ON data.airport = stats.airport
ORDER BY stats.airport;
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_active_airports(path: Path = AIRPORTS_PATH) -> list[str]:
    with path.open(encoding="utf-8") as catalog_file:
        catalog = json.load(catalog_file)
    return sorted(
        airport["code"]
        for airport in catalog["airports"]
        if airport.get("status") == "active"
    )


def query_local_db(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(HEALTH_SQL).fetchall()]
    finally:
        conn.close()


def query_remote_db(
    ssh_target: str = DEFAULT_SSH_TARGET,
    ssh_key: Path = DEFAULT_EC2_KEY,
    remote_db: str = DEFAULT_REMOTE_DB,
) -> list[dict]:
    command = [
        "/usr/bin/ssh",
        "-i",
        str(ssh_key),
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        ssh_target,
        "sqlite3",
        "-json",
        remote_db,
    ]
    result = subprocess.run(
        command,
        input=HEALTH_SQL,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or f"SSH exited {result.returncode}"
        raise RuntimeError(f"production health query failed: {error}")
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise RuntimeError("production health query returned invalid JSON") from exc
    if not isinstance(payload, list) or not all(
        isinstance(row, dict) for row in payload
    ):
        raise RuntimeError("production health query returned an invalid result")
    return payload


def age_hours(now: datetime, timestamp: str) -> float:
    return max(0.0, (now - parse_utc(timestamp)).total_seconds() / 3600)


def evaluate_health(
    records: list[dict],
    active_airports: list[str],
    now: datetime,
    threshold: timedelta,
    cron_stale_after: timedelta,
) -> dict:
    by_airport = {record["airport"]: record for record in records}
    latest_attempts = [
        parse_utc(record["last_attempt_at"])
        for record in records
        if record.get("last_attempt_at")
    ]
    latest_scraper_run = max(latest_attempts) if latest_attempts else None
    system_issues: list[str] = []
    if latest_scraper_run is None:
        system_issues.append("no scraper runs were found")
    elif now - latest_scraper_run >= cron_stale_after:
        system_issues.append(
            f"latest scraper run is {age_hours(now, format_utc(latest_scraper_run)):.1f} hours old"
        )

    incidents: list[dict] = []
    for airport in active_airports:
        record = by_airport.get(airport)
        reasons: list[str] = []
        if record is None:
            incidents.append(
                {
                    "airport": airport,
                    "reasons": ["no scrape statistics were found"],
                    "last_attempt_at": None,
                    "last_success_at": None,
                    "last_data_at": None,
                    "latest_ok": None,
                    "latest_error": None,
                }
            )
            continue

        last_success = record.get("last_success_at")
        last_data = record.get("last_data_at")
        if not last_success:
            reasons.append("no successful scrape was found")
        elif now - parse_utc(last_success) >= threshold:
            reasons.append(
                f"last successful scrape is {age_hours(now, last_success):.1f} hours old"
            )
        if not last_data:
            reasons.append("no wait-time data was found")
        elif now - parse_utc(last_data) >= threshold:
            reasons.append(
                f"last wait-time data is {age_hours(now, last_data):.1f} hours old"
            )

        if reasons:
            incidents.append(
                {
                    "airport": airport,
                    "reasons": reasons,
                    "last_attempt_at": record.get("last_attempt_at"),
                    "last_success_at": last_success,
                    "last_data_at": last_data,
                    "latest_ok": record.get("latest_ok"),
                    "latest_error": record.get("latest_error"),
                }
            )

    return {
        "checked_at_utc": format_utc(now),
        "healthy": not system_issues and not incidents,
        "threshold_hours": threshold.total_seconds() / 3600,
        "cron_stale_minutes": cron_stale_after.total_seconds() / 60,
        "latest_scraper_run_at": (
            format_utc(latest_scraper_run) if latest_scraper_run else None
        ),
        "system_issues": system_issues,
        "incidents": incidents,
    }


def check_health(
    *,
    now: datetime | None = None,
    threshold_hours: int = DEFAULT_THRESHOLD_HOURS,
    cron_stale_minutes: int = DEFAULT_CRON_STALE_MINUTES,
    db_path: Path | None = None,
    ssh_target: str = DEFAULT_SSH_TARGET,
    ssh_key: Path = DEFAULT_EC2_KEY,
    remote_db: str = DEFAULT_REMOTE_DB,
) -> dict:
    records = (
        query_local_db(db_path)
        if db_path is not None
        else query_remote_db(ssh_target, ssh_key, remote_db)
    )
    return evaluate_health(
        records,
        load_active_airports(),
        now or utc_now(),
        timedelta(hours=threshold_hours),
        timedelta(minutes=cron_stale_minutes),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, help="query a local database instead of EC2")
    parser.add_argument("--ssh-target", default=DEFAULT_SSH_TARGET)
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_EC2_KEY)
    parser.add_argument("--remote-db", default=DEFAULT_REMOTE_DB)
    parser.add_argument("--threshold-hours", type=int, default=DEFAULT_THRESHOLD_HOURS)
    parser.add_argument(
        "--cron-stale-minutes", type=int, default=DEFAULT_CRON_STALE_MINUTES
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = check_health(
            threshold_hours=args.threshold_hours,
            cron_stale_minutes=args.cron_stale_minutes,
            db_path=args.db,
            ssh_target=args.ssh_target,
            ssh_key=args.ssh_key,
            remote_db=args.remote_db,
        )
    except Exception as exc:
        print(json.dumps({"healthy": False, "monitor_error": str(exc)}, indent=2))
        return 1
    print(json.dumps(report, indent=2))
    return 0 if report["healthy"] else INCIDENT_EXIT


if __name__ == "__main__":
    sys.exit(main())
