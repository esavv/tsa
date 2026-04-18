#!/usr/bin/env python3
"""Simple webapp: latest wait times + 24h terminal history charts."""
import json
import os
import sqlite3
from typing import Optional
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("TSA_DB_PATH", os.path.join(APP_DIR, "tsa.db"))
CATALOG_PATH = os.path.join(APP_DIR, "data", "airports.json")


def load_airport_catalog():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


try:
    AIRPORT_CATALOG = load_airport_catalog()
except (OSError, json.JSONDecodeError):
    AIRPORT_CATALOG = {"metros": {}, "airports": []}


def catalog_airport_entry(code: str) -> Optional[dict]:
    for ap in AIRPORT_CATALOG.get("airports", []):
        if ap.get("code") == code:
            return ap
    return None


_DEFAULT_TERMINAL_TAB = {
    "ignore_gate": False,
    "without_gate": "Terminal {terminal}",
    "with_gate": "Terminal {terminal}: Gates {gate}",
}


def airport_catalog_entry_for_js(code: str) -> dict:
    """Catalog row for the current airport; terminal_tab merged with template defaults if partial."""
    raw = dict(catalog_airport_entry(code) or {})
    raw["code"] = code
    tab = dict(raw.get("terminal_tab") or {})
    merged = {**_DEFAULT_TERMINAL_TAB, **tab}
    raw["terminal_tab"] = merged
    return raw

# Keep in sync with scripts/scraper.py SCRAPE_AIRPORTS
AIRPORT_CODES = frozenset(
    {
        "LGA",
        "JFK",
        "EWR",
        "LAX",
        "MIA",
        "SEA",
        "DCA",
        "ATL",
        "DFW",
        "DEN",
        "CLT",
        "LAS",
        "MCO",
        "PHX",
    }
)

app = Flask(__name__, template_folder=os.path.join(APP_DIR, "templates"))


def get_db():
    return sqlite3.connect(DB_PATH)


@app.route("/")
def index():
    return redirect(url_for("airport", code="JFK"), code=302)


@app.route("/all")
def all_airports():
    """Full multi-airport table (not linked from main UI)."""
    return render_template("all_airports.html")


@app.route("/<code>")
def airport(code: str):
    c = (code or "").strip().upper()
    if len(c) != 3 or not c.isalpha() or c not in AIRPORT_CODES:
        abort(404)
    initial_terminal = request.args.get("terminal") or ""
    initial_gate = request.args.get("gate") or ""
    entry = catalog_airport_entry(c)
    airport_display_name = (entry or {}).get("display_name") or c
    city = (entry or {}).get("city") or ""
    state = (entry or {}).get("state") or ""
    locale_bits = [x for x in (city, state) if x]
    airport_locale_line = ", ".join(locale_bits) if locale_bits else None
    return render_template(
        "airport.html",
        airport=c,
        airport_display_name=airport_display_name,
        airport_locale_line=airport_locale_line,
        airport_catalog_entry=airport_catalog_entry_for_js(c),
        initial_terminal=initial_terminal,
        initial_gate=initial_gate,
    )


@app.route("/terminal/<airport>/<terminal>")
def terminal_redirect(airport: str, terminal: str):
    ap = (airport or "").strip().upper()
    if ap not in AIRPORT_CODES:
        abort(404)
    gate = request.args.get("gate") or ""
    q = urlencode({"terminal": terminal, "gate": gate})
    return redirect(f"/{ap}?{q}", code=301)


@app.route("/api/catalog")
def api_catalog():
    """Airport + metro metadata for client-side search (see data/airports.json)."""
    return jsonify(AIRPORT_CATALOG)


@app.route("/api/latest")
def api_latest():
    """Latest scrape + 6h sparkline series per airport / terminal (+ gate) / queue_type."""
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT scraped_at_utc FROM wait_times ORDER BY scraped_at_utc DESC LIMIT 1"
    )
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify(scraped_at_utc=None, airports={})

    scraped_at_utc = row[0]
    cur.execute(
        """
        SELECT airport, terminal, gate, queue_type, wait_minutes
        FROM wait_times
        WHERE scraped_at_utc = ?
        ORDER BY airport, terminal, gate, queue_type
        """,
        (scraped_at_utc,),
    )
    rows = cur.fetchall()
    airports: dict[str, dict[tuple[str, str], dict]] = {}
    for airport, terminal, gate, queue_type, wait_minutes in rows:
        if airport not in airports:
            airports[airport] = {}
        g = gate or ""
        key = (terminal, g)
        if key not in airports[airport]:
            airports[airport][key] = {"queues": {}}
        slot = airports[airport][key]["queues"]
        if queue_type not in slot:
            slot[queue_type] = {"minutes": None, "spark": []}
        slot[queue_type]["minutes"] = wait_minutes

    since_6h = (datetime.now(timezone.utc) - timedelta(hours=6)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cur.execute(
        """
        SELECT airport, terminal, gate, queue_type, scraped_at_utc, wait_minutes
        FROM wait_times
        WHERE scraped_at_utc >= ?
        ORDER BY scraped_at_utc
        """,
        (since_6h,),
    )
    history_rows = cur.fetchall()
    conn.close()

    for airport, terminal, gate, queue_type, scraped_at_utc, wait_minutes in history_rows:
        g = gate or ""
        key = (terminal, g)
        if airport not in airports or key not in airports[airport]:
            continue
        queues = airports[airport][key]["queues"]
        if queue_type not in queues:
            queues[queue_type] = {"minutes": None, "spark": []}
        queues[queue_type]["spark"].append(
            {"t": scraped_at_utc, "minutes": wait_minutes}
        )

    result = {}
    for airport, terms in airports.items():
        result[airport] = [
            {
                "terminal": t,
                "gate": g,
                "queues": d["queues"],
            }
            for (t, g), d in sorted(terms.items(), key=lambda item: (item[0][0], item[0][1]))
        ]

    return jsonify(scraped_at_utc=scraped_at_utc, airports=result)


@app.route("/api/history")
def api_history():
    """History for one airport + terminal (+ optional gate). Returns queues keyed by queue_type."""
    airport = request.args.get("airport")
    terminal = request.args.get("terminal")
    if not airport or not terminal:
        return jsonify(error="airport and terminal required"), 400

    gate = request.args.get("gate") or ""

    hours = request.args.get("hours", "24")
    allowed_hours = {"6", "12", "24", "72", "168"}
    if hours not in allowed_hours:
        return jsonify(error="hours must be one of 6, 12, 24, 72, 168"), 400

    since = (datetime.now(timezone.utc) - timedelta(hours=int(hours))).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT scraped_at_utc
        FROM wait_times
        WHERE airport = ? AND terminal = ? AND gate = ?
        ORDER BY scraped_at_utc DESC
        LIMIT 1
        """,
        (airport, terminal, gate),
    )
    latest_row = cur.fetchone()
    latest_scraped_at_utc = latest_row[0] if latest_row else None

    cur.execute(
        """
        SELECT scraped_at_utc, queue_type, wait_minutes
        FROM wait_times
        WHERE airport = ? AND terminal = ? AND gate = ? AND scraped_at_utc >= ?
        ORDER BY scraped_at_utc
        """,
        (airport, terminal, gate, since),
    )
    rows = cur.fetchall()
    conn.close()

    queues: dict[str, list[dict]] = {}
    for scraped_at_utc, queue_type, wait_minutes in rows:
        point = {"t": scraped_at_utc, "minutes": wait_minutes}
        if queue_type not in queues:
            queues[queue_type] = []
        queues[queue_type].append(point)

    return jsonify(
        queues=queues,
        latest_scraped_at_utc=latest_scraped_at_utc,
    )


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    debug = os.environ.get("FLASK_DEBUG", "true").lower() in ("1", "true", "yes")
    app.run(host=host, port=5000, debug=debug)
