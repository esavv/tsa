#!/usr/bin/env python3
"""Wait for and validate the first scheduled scrape after a deployment."""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__:
    from .scrape_health import (
        DEFAULT_EC2_KEY,
        DEFAULT_REMOTE_DB,
        DEFAULT_SSH_TARGET,
        parse_utc,
    )
else:
    from scrape_health import (
        DEFAULT_EC2_KEY,
        DEFAULT_REMOTE_DB,
        DEFAULT_SSH_TARGET,
        parse_utc,
    )

POLL_SECONDS = 60
DEFAULT_TIMEOUT_MINUTES = 30


def next_validation_time(deployed_at: datetime) -> datetime:
    minute = (deployed_at.minute // 15 + 1) * 15
    boundary = deployed_at.replace(second=0, microsecond=0)
    if minute == 60:
        boundary = boundary.replace(minute=0) + timedelta(hours=1)
    else:
        boundary = boundary.replace(minute=minute)
    return boundary + timedelta(minutes=4)


def query_validation(
    airports: list[str],
    deployed_at: str,
    ssh_target: str,
    ssh_key: Path,
    remote_db: str,
) -> list[dict]:
    airport_values = ", ".join(f"'{airport}'" for airport in airports)
    sql = f"""
WITH latest AS (
    SELECT airport, MAX(scraped_at_utc) AS scraped_at_utc
    FROM scrape_airport_stats
    WHERE airport IN ({airport_values})
      AND scraped_at_utc > '{deployed_at}'
    GROUP BY airport
)
SELECT
    stats.airport,
    stats.scraped_at_utc,
    stats.ok,
    stats.error,
    (SELECT COUNT(*) FROM wait_times AS waits
      WHERE waits.airport = stats.airport
        AND waits.scraped_at_utc = stats.scraped_at_utc) AS stored_rows
FROM scrape_airport_stats AS stats
JOIN latest
  ON latest.airport = stats.airport
 AND latest.scraped_at_utc = stats.scraped_at_utc
ORDER BY stats.airport;
"""
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
        input=sql,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or f"SSH exited {result.returncode}"
        raise RuntimeError(f"production validation query failed: {error}")
    payload = json.loads(result.stdout or "[]")
    if not isinstance(payload, list):
        raise RuntimeError("production validation query returned an invalid result")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--airport", action="append", required=True)
    parser.add_argument("--deployed-at", required=True)
    parser.add_argument("--timeout-minutes", type=int, default=DEFAULT_TIMEOUT_MINUTES)
    parser.add_argument("--ssh-target", default=DEFAULT_SSH_TARGET)
    parser.add_argument("--ssh-key", type=Path, default=DEFAULT_EC2_KEY)
    parser.add_argument("--remote-db", default=DEFAULT_REMOTE_DB)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    airports = sorted(set(airport.upper() for airport in args.airport))
    if any(len(airport) != 3 or not airport.isalnum() for airport in airports):
        print("Airport codes must contain three letters or digits.", file=sys.stderr)
        return 2
    try:
        deployed_at = parse_utc(args.deployed_at)
    except ValueError:
        print("--deployed-at must be an ISO 8601 timestamp.", file=sys.stderr)
        return 2

    validation_time = next_validation_time(deployed_at)
    now = datetime.now(timezone.utc)
    if now < validation_time:
        wait_seconds = (validation_time - now).total_seconds()
        print(f"Sleeping {int(wait_seconds)} seconds for the next scheduled scrape.")
        time.sleep(wait_seconds)

    deadline = time.monotonic() + args.timeout_minutes * 60
    while True:
        try:
            rows = query_validation(
                airports,
                args.deployed_at,
                args.ssh_target,
                args.ssh_key,
                args.remote_db,
            )
        except (RuntimeError, json.JSONDecodeError) as exc:
            print(str(exc), file=sys.stderr)
            rows = []
        by_airport = {row["airport"]: row for row in rows}
        if all(
            airport in by_airport
            and int(by_airport[airport]["ok"]) == 1
            and int(by_airport[airport]["stored_rows"]) > 0
            for airport in airports
        ):
            print(json.dumps({"validated": True, "results": rows}, indent=2))
            return 0
        if time.monotonic() >= deadline:
            print(json.dumps({"validated": False, "results": rows}, indent=2))
            return 1
        print("Scheduled scrape is not validated yet; sleeping 60 seconds.")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    sys.exit(main())
