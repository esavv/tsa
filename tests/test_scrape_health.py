#!/usr/bin/env python3
"""Tests for deterministic scrape health monitoring."""

import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.automation.run_scrape_monitor import AGENT_MODEL, build_dry_run_prompt
from scripts.automation.scrape_health import HEALTH_SQL, evaluate_health

NOW = datetime(2026, 8, 26, 14, 0, tzinfo=timezone.utc)


def record(
    airport: str,
    *,
    attempt: str = "2026-08-26T13:45:00Z",
    success: str | None = "2026-08-26T13:45:00Z",
    data: str | None = "2026-08-26T13:45:00Z",
    ok: int = 1,
    error: str | None = None,
) -> dict:
    return {
        "airport": airport,
        "last_attempt_at": attempt,
        "last_success_at": success,
        "last_data_at": data,
        "latest_ok": ok,
        "latest_error": error,
    }


class ScrapeHealthTests(unittest.TestCase):
    def evaluate(self, records: list[dict], airports: list[str]) -> dict:
        return evaluate_health(
            records,
            airports,
            NOW,
            timedelta(hours=24),
            timedelta(minutes=45),
        )

    def test_healthy_when_scrapes_and_data_are_current(self) -> None:
        report = self.evaluate([record("ATL"), record("JFK")], ["ATL", "JFK"])
        self.assertTrue(report["healthy"])
        self.assertEqual(report["incidents"], [])
        self.assertEqual(report["system_issues"], [])

    def test_detects_sustained_airport_failure(self) -> None:
        report = self.evaluate(
            [
                record(
                    "ATL",
                    success="2026-08-22T06:45:01Z",
                    data="2026-08-22T06:45:01Z",
                    ok=0,
                    error="no checkpoint rows",
                )
            ],
            ["ATL"],
        )
        self.assertFalse(report["healthy"])
        incident = report["incidents"][0]
        self.assertEqual(incident["airport"], "ATL")
        self.assertEqual(incident["latest_error"], "no checkpoint rows")
        self.assertEqual(len(incident["reasons"]), 2)

    def test_detects_missing_airport_statistics(self) -> None:
        report = self.evaluate([record("JFK")], ["ATL", "JFK"])
        self.assertEqual(report["incidents"][0]["airport"], "ATL")
        self.assertIn("no scrape statistics", report["incidents"][0]["reasons"][0])

    def test_detects_stopped_scraper(self) -> None:
        stale = record(
            "ATL",
            attempt="2026-08-26T12:00:00Z",
            success="2026-08-26T12:00:00Z",
            data="2026-08-26T12:00:00Z",
        )
        report = self.evaluate([stale], ["ATL"])
        self.assertFalse(report["healthy"])
        self.assertIn("latest scraper run", report["system_issues"][0])

    def test_query_reports_latest_error_and_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tsa.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE scrape_airport_stats (
                    scraped_at_utc TEXT NOT NULL,
                    airport TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    ok INTEGER NOT NULL,
                    error TEXT
                );
                CREATE TABLE wait_times (
                    scraped_at_utc TEXT NOT NULL,
                    airport TEXT NOT NULL
                );
                INSERT INTO scrape_airport_stats VALUES
                    ('2026-08-22T06:45:01Z', 'ATL', 2000, 1, NULL),
                    ('2026-08-26T13:45:00Z', 'ATL', 6000, 0, 'new layout');
                INSERT INTO wait_times VALUES ('2026-08-22T06:45:01Z', 'ATL');
                """
            )
            conn.row_factory = sqlite3.Row
            result = dict(conn.execute(HEALTH_SQL).fetchone())
            conn.close()
        self.assertEqual(result["last_success_at"], "2026-08-22T06:45:01Z")
        self.assertEqual(result["last_data_at"], "2026-08-22T06:45:01Z")
        self.assertEqual(result["latest_error"], "new layout")

    def test_dry_run_prompt_pins_safety_and_agent_notifications(self) -> None:
        report = self.evaluate([record("ATL")], ["ATL"])
        prompt = build_dry_run_prompt(report)
        self.assertEqual(AGENT_MODEL, "openai/gpt-5.6-sol")
        self.assertIn("Do not edit files", prompt)
        self.assertIn("Do not notify for a suspected or unconfirmed incident", prompt)
        self.assertIn("dry-run diagnosis with no fix deployed", prompt)
        json.dumps(report)


if __name__ == "__main__":
    unittest.main()
