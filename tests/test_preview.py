import os
import sqlite3
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import app as tsa_app


class MarketingPreviewTests(unittest.TestCase):
    def setUp(self):
        db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_file.close()
        self.db_path = db_file.name
        self.original_db_path = tsa_app.DB_PATH
        tsa_app.DB_PATH = self.db_path

        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """
            CREATE TABLE wait_times (
                scraped_at_utc TEXT NOT NULL,
                airport TEXT NOT NULL,
                terminal TEXT NOT NULL,
                gate TEXT NOT NULL DEFAULT '',
                queue_type TEXT NOT NULL,
                wait_minutes INTEGER,
                wait_min_minutes INTEGER,
                wait_max_minutes INTEGER
            )
            """
        )
        conn.executemany(
            """
            INSERT INTO wait_times (
                scraped_at_utc, airport, terminal, gate, queue_type,
                wait_minutes, wait_min_minutes, wait_max_minutes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ("2026-07-23T12:00:00Z", "JFK", "5", "", "general", 20, None, None),
                ("2026-07-23T12:15:00Z", "JFK", "5", "", "general", 30, None, None),
                ("2026-07-23T12:15:00Z", "JFK", "5", "", "precheck", 15, None, None),
            ],
        )
        conn.commit()
        conn.close()
        self.client = tsa_app.app.test_client()

    def tearDown(self):
        tsa_app.DB_PATH = self.original_db_path
        os.unlink(self.db_path)

    def test_preview_page_and_options(self):
        response = self.client.get("/preview")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Marketing image preview", response.data)

        response = self.client.get("/api/preview/options")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["latest_scraped_at_utc"], "2026-07-23T12:15:00Z")
        self.assertEqual(payload["airports"][0]["code"], "JFK")
        self.assertEqual(
            payload["airports"][0]["terminals"],
            [{"gate": "", "terminal": "5"}],
        )

    def test_preview_embed_uses_airport_chart_with_preview_bounds(self):
        response = self.client.get(
            "/JFK",
            query_string={
                "terminal": "5",
                "marketing_preview": "1",
                "hours": "72",
                "start": "2026-07-20T12:00:00Z",
                "end": "2026-07-23T12:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="marketing-preview-embed"', response.data)
        self.assertIn(b"const marketingPreviewEmbed = true;", response.data)
        self.assertIn(b"const marketingPreviewHours = 72;", response.data)
        self.assertIn(b"2026-07-20T12:00:00Z", response.data)
        self.assertIn(b"2026-07-23T12:00:00Z", response.data)

    def test_preview_history_uses_explicit_bounds(self):
        response = self.client.get(
            "/api/preview/history",
            query_string={
                "airport": "JFK",
                "terminal": "5",
                "start": "2026-07-23T12:10:00Z",
                "end": "2026-07-23T12:20:00Z",
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["queues"]["general"]), 1)
        self.assertEqual(payload["queues"]["general"][0]["minutes"], 30)
        self.assertEqual(len(payload["queues"]["precheck"]), 1)

    def test_preview_history_rejects_naive_or_reversed_bounds(self):
        naive = self.client.get(
            "/api/preview/history",
            query_string={
                "airport": "JFK",
                "terminal": "5",
                "start": "2026-07-23T12:00:00",
                "end": "2026-07-23T13:00:00Z",
            },
        )
        self.assertEqual(naive.status_code, 400)
        self.assertIn("timezone", naive.get_json()["error"])

        reversed_range = self.client.get(
            "/api/preview/history",
            query_string={
                "airport": "JFK",
                "terminal": "5",
                "start": "2026-07-23T13:00:00Z",
                "end": "2026-07-23T12:00:00Z",
            },
        )
        self.assertEqual(reversed_range.status_code, 400)
        self.assertEqual(reversed_range.get_json()["error"], "start must be before end")


if __name__ == "__main__":
    unittest.main()
