#!/usr/bin/env python3
"""Cron entry point: ensure DB exists, then fetch and store supported airport wait times."""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from init_db import init_db
from scraper import run

if __name__ == "__main__":
    db_path = init_db()
    run(db_path=db_path)
