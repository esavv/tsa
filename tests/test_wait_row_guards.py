#!/usr/bin/env python3
"""Tests for the row guards applied before wait rows reach the database."""

import os
import sqlite3
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from scraper import MAX_TERMINAL_NAME_LEN, store

FABRIC_ERROR = (
    "Unable to complete the action because your organization\u2019s Fabric compute "
    "capacity has exceeded a surge protection usage limit set by your capacity "
    "administrator. Try again later."
)

SCHEMA = """
CREATE TABLE wait_times (
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
    UNIQUE (scraped_at_utc, airport, terminal, gate, queue_type)
);
"""


def _row(terminal: str) -> dict:
    return {
        "airport": "LAX",
        "terminal": terminal,
        "gate": "",
        "queue_type": "general",
        "wait_minutes": 5,
        "wait_min_minutes": None,
        "wait_max_minutes": None,
        "source_updated_at": None,
        "point_id": None,
    }


class TestStoreGuards(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        conn.executescript(SCHEMA)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.unlink(self.db_path)

    def _count(self) -> int:
        conn = sqlite3.connect(self.db_path)
        n = conn.execute("SELECT COUNT(*) FROM wait_times").fetchone()[0]
        conn.close()
        return n

    def test_stores_normal_terminal_names(self):
        rows = [_row("TBIT"), _row("International"), _row("D/E")]
        self.assertEqual(store(self.db_path, rows, "2026-08-12T12:00:00Z"), 3)

    def test_rejects_source_error_text_as_terminal(self):
        with self.assertRaises(ValueError) as ctx:
            store(self.db_path, [_row(FABRIC_ERROR)], "2026-08-12T12:00:00Z")
        self.assertIn("too long to be a real label", str(ctx.exception))

    def test_rejects_whole_batch_without_partial_write(self):
        rows = [_row("TBIT"), _row(FABRIC_ERROR)]
        with self.assertRaises(ValueError):
            store(self.db_path, rows, "2026-08-12T12:00:00Z")
        self.assertEqual(self._count(), 0)

    def test_boundary_length_is_allowed(self):
        rows = [_row("T" * MAX_TERMINAL_NAME_LEN)]
        self.assertEqual(store(self.db_path, rows, "2026-08-12T12:00:00Z"), 1)

    def test_rejects_row_with_no_wait_signal(self):
        row = _row("TBIT")
        row["wait_minutes"] = None
        with self.assertRaises(ValueError) as ctx:
            store(self.db_path, [row], "2026-08-12T12:00:00Z")
        self.assertIn("at least one of", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
