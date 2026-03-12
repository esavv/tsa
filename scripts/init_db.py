#!/usr/bin/env python3
"""Create SQLite DB and wait_times table from schema. Run once (or idempotent)."""
import sqlite3
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)
SCHEMA_PATH = os.path.join(REPO_ROOT, "schema.sql")
DEFAULT_DB_PATH = os.path.join(REPO_ROOT, "tsa.db")


def init_db(db_path: str | None = None) -> str:
    db_path = db_path or os.environ.get("TSA_DB_PATH", DEFAULT_DB_PATH)
    with open(SCHEMA_PATH) as f:
        schema_sql = f.read()
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    path = init_db()
    print(f"Initialized DB: {path}")
