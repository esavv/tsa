#!/usr/bin/env python3
"""Cron entry point: ensure DB exists, then fetch and store supported airport wait times."""
import os
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from init_db import init_db
from scraper import run


def _reap_stale_chromium() -> None:
    """Kill any chromium owned by the current user before launching a new scrape.

    Belt to scraper.py's subprocess-group timeout suspenders: if a previous
    cron tick managed to leak a chromium somehow (timeout escalation race,
    manual kill that missed children, etc.), reap before we add more.
    """
    try:
        subprocess.run(
            ["pkill", "-9", "-u", str(os.getuid()), "-f", "chrom"],
            check=False,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


if __name__ == "__main__":
    _reap_stale_chromium()
    db_path = init_db()
    run(db_path=db_path)
