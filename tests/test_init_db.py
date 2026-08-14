import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.init_db import init_db


class InitDbTests(unittest.TestCase):
    def test_migrates_wait_times_to_without_rowid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "tsa.db"
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE wait_times (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scraped_at_utc TEXT NOT NULL,
                    airport TEXT NOT NULL,
                    terminal TEXT NOT NULL,
                    gate TEXT NOT NULL DEFAULT '',
                    queue_type TEXT NOT NULL,
                    wait_minutes INTEGER,
                    wait_min_minutes INTEGER,
                    wait_max_minutes INTEGER,
                    source_updated_at TEXT,
                    point_id INTEGER,
                    UNIQUE(scraped_at_utc, airport, terminal, queue_type, gate)
                );
                CREATE INDEX idx_wait_times_scraped
                    ON wait_times(scraped_at_utc);
                INSERT INTO wait_times (
                    scraped_at_utc, airport, terminal, gate, queue_type,
                    wait_minutes, source_updated_at, point_id
                ) VALUES (
                    '2026-08-14T05:00:01Z', 'JFK', '1', '', 'general',
                    12, '2026-08-14T05:00:00Z', 7
                );
                """
            )
            conn.commit()
            conn.close()

            init_db(str(db_path))
            init_db(str(db_path))

            conn = sqlite3.connect(db_path)
            table = conn.execute(
                "SELECT wr FROM pragma_table_list WHERE name = 'wait_times'"
            ).fetchone()
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(wait_times)").fetchall()
            }
            indexes = {
                row[1]
                for row in conn.execute("PRAGMA index_list(wait_times)").fetchall()
            }
            wait_row = conn.execute(
                """
                SELECT scraped_at_utc, airport, terminal, gate, queue_type,
                       wait_minutes, source_updated_at, point_id
                FROM wait_times
                """
            ).fetchone()
            conn.close()

            self.assertEqual(table, (1,))
            self.assertNotIn("id", columns)
            self.assertIn("idx_wait_times_history", indexes)
            self.assertNotIn("idx_wait_times_scraped", indexes)
            self.assertEqual(
                wait_row,
                (
                    "2026-08-14T05:00:01Z",
                    "JFK",
                    "1",
                    "",
                    "general",
                    12,
                    "2026-08-14T05:00:00Z",
                    7,
                ),
            )


if __name__ == "__main__":
    unittest.main()
