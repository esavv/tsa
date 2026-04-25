#!/usr/bin/env python3
"""Create SQLite DB and wait_times table from schema. Run once (or idempotent)."""
import os
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
SCHEMA_PATH = os.path.join(REPO_ROOT, "schema.sql")
DEFAULT_DB_PATH = os.path.join(REPO_ROOT, "tsa.db")


def migrate_wait_times_add_gate(conn: sqlite3.Connection) -> None:
    """Rebuild wait_times if it exists without a gate column (adds gate + new UNIQUE)."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wait_times'")
    if not cur.fetchone():
        return
    cur.execute("PRAGMA table_info(wait_times)")
    cols = {row[1] for row in cur.fetchall()}
    if "gate" in cols:
        return
    cur.executescript(
        """
        CREATE TABLE wait_times_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scraped_at_utc TEXT NOT NULL,
            airport TEXT NOT NULL,
            terminal TEXT NOT NULL,
            gate TEXT NOT NULL DEFAULT '',
            queue_type TEXT NOT NULL,
            wait_minutes INTEGER NOT NULL,
            wait_min_minutes INTEGER,
            wait_max_minutes INTEGER,
            source_updated_at TEXT,
            point_id INTEGER,
            UNIQUE(scraped_at_utc, airport, terminal, queue_type, gate)
        );
        INSERT INTO wait_times_new (
            id, scraped_at_utc, airport, terminal, gate, queue_type,
            wait_minutes, source_updated_at, point_id
        )
        SELECT
            id, scraped_at_utc, airport, terminal, '', queue_type,
            wait_minutes, source_updated_at, point_id
        FROM wait_times;
        DROP TABLE wait_times;
        ALTER TABLE wait_times_new RENAME TO wait_times;
        CREATE INDEX IF NOT EXISTS idx_wait_times_scraped ON wait_times(scraped_at_utc);
        CREATE INDEX IF NOT EXISTS idx_wait_times_airport_terminal ON wait_times(airport, terminal);
        """
    )


def migrate_wait_times_add_range_columns(conn: sqlite3.Connection) -> None:
    """Add nullable wait_min_minutes / wait_max_minutes when missing (SQLite ALTER ADD COLUMN)."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wait_times'")
    if not cur.fetchone():
        return
    cur.execute("PRAGMA table_info(wait_times)")
    cols = {row[1] for row in cur.fetchall()}
    if "wait_min_minutes" not in cols:
        cur.execute("ALTER TABLE wait_times ADD COLUMN wait_min_minutes INTEGER")
    if "wait_max_minutes" not in cols:
        cur.execute("ALTER TABLE wait_times ADD COLUMN wait_max_minutes INTEGER")


def init_db(db_path: str | None = None) -> str:
    db_path = db_path or os.environ.get("TSA_DB_PATH", DEFAULT_DB_PATH)
    with open(SCHEMA_PATH) as f:
        schema_sql = f.read()
    conn = sqlite3.connect(db_path)
    migrate_wait_times_add_gate(conn)
    conn.executescript(schema_sql)
    migrate_wait_times_add_range_columns(conn)
    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    path = init_db()
    print(f"Initialized DB: {path}")
